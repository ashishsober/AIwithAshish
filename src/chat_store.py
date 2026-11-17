"""Qwen Chat history in MySQL (database chat_db, tables from sql/001_chat_db.sql).

Every call takes the signed-in person's user id and only ever reads or changes that person's own
conversations: a conversation id that belongs to someone else behaves exactly like one that doesn't exist.

The connection pool is made on first use, so chat-api starts (and answers questions) even while MySQL
is down; history calls then raise StoreUnavailable.
"""
import logging
import os
import threading
import uuid
from typing import Optional

import mysql.connector
from mysql.connector import pooling

log = logging.getLogger("chat_api.store")

TITLE_CHARS = 60


class StoreUnavailable(Exception):
    """MySQL could not be reached or the query failed."""


def make_title(prompt: str) -> str:
    """A conversation's title: its first question on one line, cut at a word near TITLE_CHARS."""
    text = " ".join(prompt.split())
    if len(text) <= TITLE_CHARS:
        return text or "New chat"
    cut = text[:TITLE_CHARS].rsplit(" ", 1)[0] or text[:TITLE_CHARS]
    return cut.rstrip(" .,;:-") + "…"


def _iso(value) -> Optional[str]:
    return value.isoformat(timespec="milliseconds") if value is not None else None


class ChatStore:
    def __init__(self, host: str, user: str, password: str, port: int = 3306, database: str = "chat_db"):
        self._db = dict(host=host, user=user, password=password, port=port, database=database,
                        connection_timeout=5, autocommit=False)
        self._pool: Optional[pooling.MySQLConnectionPool] = None
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> Optional["ChatStore"]:
        """None when CHAT_DB_HOST is not set (no Secret yet): chat works, nothing is kept."""
        host = os.getenv("CHAT_DB_HOST", "").strip()
        if not host:
            return None
        return cls(host=host, user=os.getenv("CHAT_DB_USER", "chat_api"), password=os.getenv("CHAT_DB_PASSWORD", ""),
                   port=int(os.getenv("CHAT_DB_PORT", "3306")))

    def _connect(self):
        try:
            with self._lock:
                if self._pool is None:
                    self._pool = pooling.MySQLConnectionPool(pool_name="chat", pool_size=4, pool_reset_session=True,
                                                             **self._db)
            return self._pool.get_connection()
        except mysql.connector.Error as exc:
            raise StoreUnavailable(str(exc)) from exc

    def _run(self, work):
        """Runs work(cursor) in one transaction and returns its result."""
        conn = self._connect()
        try:
            cur = conn.cursor(dictionary=True)
            try:
                result = work(cur)
                conn.commit()
                return result
            finally:
                cur.close()
        except mysql.connector.Error as exc:
            try:
                conn.rollback()
            except mysql.connector.Error:
                pass
            log.exception("chat_db query failed")
            raise StoreUnavailable(str(exc)) from exc
        finally:
            conn.close()

    # ------------------------------------------------------------------ reads
    def list_conversations(self, user_id: int, limit: int = 200) -> list:
        def work(cur):
            cur.execute(
                "SELECT c.id, c.title, c.created_at, c.updated_at, "
                "       (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count "
                "FROM conversations c WHERE c.user_id = %s ORDER BY c.updated_at DESC LIMIT %s",
                (user_id, limit))
            return [{"id": row["id"], "title": row["title"], "created_at": _iso(row["created_at"]),
                     "updated_at": _iso(row["updated_at"]), "message_count": int(row["message_count"])}
                    for row in cur.fetchall()]
        return self._run(work)

    def get_conversation(self, user_id: int, conversation_id: str) -> Optional[dict]:
        """The conversation with its messages in order, or None if it isn't this person's."""
        def work(cur):
            cur.execute("SELECT id, title, created_at, updated_at FROM conversations WHERE id = %s AND user_id = %s",
                        (conversation_id, user_id))
            conv = cur.fetchone()
            if not conv:
                return None
            cur.execute("SELECT role, content, model, elapsed_ms, created_at FROM messages "
                        "WHERE conversation_id = %s ORDER BY id", (conversation_id,))
            messages = [{"role": row["role"], "content": row["content"], "model": row["model"],
                         "elapsed_ms": row["elapsed_ms"], "created_at": _iso(row["created_at"])}
                        for row in cur.fetchall()]
            return {"id": conv["id"], "title": conv["title"], "created_at": _iso(conv["created_at"]),
                    "updated_at": _iso(conv["updated_at"]), "messages": messages}
        return self._run(work)

    # ------------------------------------------------------------------ writes
    def add_exchange(self, user_id: int, conversation_id: Optional[str], prompt: str, reply: str,
                     model: str, elapsed_ms: int) -> Optional[dict]:
        """Saves a question and its answer. No conversation_id starts a new conversation titled after the
        question. Returns {"id", "title"}, or None if conversation_id isn't this person's."""
        def work(cur):
            if conversation_id:
                cur.execute("UPDATE conversations SET updated_at = CURRENT_TIMESTAMP(3) WHERE id = %s AND user_id = %s",
                            (conversation_id, user_id))
                if cur.rowcount == 0:
                    return None
                cur.execute("SELECT title FROM conversations WHERE id = %s", (conversation_id,))
                conv = {"id": conversation_id, "title": cur.fetchone()["title"]}
            else:
                conv = {"id": uuid.uuid4().hex, "title": make_title(prompt)}
                cur.execute("INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, %s)",
                            (conv["id"], user_id, conv["title"]))
            cur.execute("INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', %s)",
                        (conv["id"], prompt))
            cur.execute("INSERT INTO messages (conversation_id, role, content, model, elapsed_ms) "
                        "VALUES (%s, 'assistant', %s, %s, %s)", (conv["id"], reply, model[:64], max(0, elapsed_ms)))
            return conv
        return self._run(work)

    def rename(self, user_id: int, conversation_id: str, title: str) -> bool:
        def work(cur):
            cur.execute("UPDATE conversations SET title = %s WHERE id = %s AND user_id = %s",
                        (title, conversation_id, user_id))
            if cur.rowcount:
                return True
            # MySQL reports 0 rows when the title is unchanged: still a success if it's this person's
            cur.execute("SELECT 1 FROM conversations WHERE id = %s AND user_id = %s", (conversation_id, user_id))
            return cur.fetchone() is not None
        return self._run(work)

    def delete(self, user_id: int, conversation_id: str) -> bool:
        def work(cur):
            cur.execute("DELETE FROM conversations WHERE id = %s AND user_id = %s", (conversation_id, user_id))
            return cur.rowcount > 0
        return self._run(work)
