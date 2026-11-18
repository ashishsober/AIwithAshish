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

    # ------------------------------------------------------------------ plans and daily limits (sql/002_chat_plans.sql)
    DEFAULT_PLAN = "free"

    @staticmethod
    def _plan(row) -> dict:
        return {"code": row["code"], "name": row["name"],
                "daily_questions": None if row["daily_questions"] is None else int(row["daily_questions"]),
                "weekly_questions": None if row.get("weekly_questions") is None else int(row["weekly_questions"]),
                "description": row["description"], "sort_order": int(row["sort_order"]),
                "requestable": bool(row["requestable"])}

    @staticmethod
    def _request(row) -> Optional[dict]:
        if not row:
            return None
        return {"id": int(row["id"]), "user_id": int(row["user_id"]), "plan": row["plan_code"],
                "from_plan": row["from_plan"], "note": row["note"], "status": row["status"],
                "created_at": _iso(row["created_at"]), "decided_at": _iso(row["decided_at"])}

    def plans(self) -> list:
        def work(cur):
            cur.execute("SELECT * FROM plans ORDER BY sort_order, code")
            return [self._plan(row) for row in cur.fetchall()]
        return self._run(work)

    def _user_plan(self, cur, user_id: int) -> dict:
        cur.execute("SELECT p.* FROM user_plans u JOIN plans p ON p.code = u.plan_code WHERE u.user_id = %s", (user_id,))
        row = cur.fetchone()
        if row is None:
            cur.execute("SELECT * FROM plans WHERE code = %s", (self.DEFAULT_PLAN,))
            row = cur.fetchone()
        if row is None:  # plans table empty: behave as no limit rather than refuse everyone
            return {"code": self.DEFAULT_PLAN, "name": "Free", "daily_questions": None, "weekly_questions": None,
                    "description": "", "sort_order": 0, "requestable": False}
        return self._plan(row)

    def user_plan(self, user_id: int) -> dict:
        return self._run(lambda cur: self._user_plan(cur, user_id))

    def reserve_question(self, user_id: int, day, week_start, now_utc, unlimited: bool = False) -> dict:
        """Counts one question if the plan has room today and this week (week_start..day). Returns
        {"allowed", "reason" ("day"/"week" when refused), "used", "limit", "week_used", "week_limit", "plan"};
        the counts include this question when allowed. Atomic: two questions at once can't both take the last one."""
        def work(cur):
            plan = self._user_plan(cur, user_id)
            daily = None if unlimited else plan["daily_questions"]
            weekly = None if unlimited else plan["weekly_questions"]
            # The upsert takes the row's exclusive lock at once (INSERT IGNORE would take a shared one, and two
            # questions at once would deadlock upgrading it); the row stays locked until this transaction ends,
            # so the person's questions are counted one at a time.
            cur.execute("INSERT INTO usage_daily (user_id, day) VALUES (%s, %s) "
                        "ON DUPLICATE KEY UPDATE questions = questions", (user_id, day))
            cur.execute("SELECT questions FROM usage_daily WHERE user_id = %s AND day = %s FOR UPDATE", (user_id, day))
            used = int(cur.fetchone()["questions"])
            # The week = its earlier days (they no longer change) + today's count just read under the lock. (Summing
            # today's row here too would read the transaction's snapshot, taken before the lock was granted, and
            # miss questions counted meanwhile.)
            cur.execute("SELECT COALESCE(SUM(questions), 0) AS n FROM usage_daily "
                        "WHERE user_id = %s AND day >= %s AND day < %s", (user_id, week_start, day))
            week_used = int(cur.fetchone()["n"]) + used
            result = {"allowed": False, "reason": None, "used": used, "limit": daily,
                      "week_used": week_used, "week_limit": weekly, "plan": plan}
            if daily is not None and used >= daily:
                return {**result, "reason": "day"}
            if weekly is not None and week_used >= weekly:
                return {**result, "reason": "week"}
            cur.execute("UPDATE usage_daily SET questions = questions + 1, "
                        "first_question_at = COALESCE(first_question_at, %s) WHERE user_id = %s AND day = %s",
                        (now_utc, user_id, day))
            return {**result, "allowed": True, "used": used + 1, "week_used": week_used + 1}
        return self._run(work)

    def release_question(self, user_id: int, day) -> None:
        """Gives back a reserved question (the model failed, so nothing was answered)."""
        self._run(lambda cur: cur.execute(
            "UPDATE usage_daily SET questions = questions - 1 WHERE user_id = %s AND day = %s AND questions > 0",
            (user_id, day)))

    def record_answer_time(self, user_id: int, day, elapsed_ms: int) -> None:
        self._run(lambda cur: cur.execute(
            "UPDATE usage_daily SET answer_ms = answer_ms + %s WHERE user_id = %s AND day = %s",
            (max(0, int(elapsed_ms)), user_id, day)))

    def usage(self, user_id: int, first_day, today) -> dict:
        """Questions per day from first_day to today (only days with questions), all-time total and saved chats."""
        def work(cur):
            cur.execute("SELECT day, questions, answer_ms, first_question_at FROM usage_daily "
                        "WHERE user_id = %s AND day BETWEEN %s AND %s ORDER BY day", (user_id, first_day, today))
            days = [{"day": row["day"].isoformat(), "questions": int(row["questions"]), "answer_ms": int(row["answer_ms"]),
                     "first_question_at": row["first_question_at"]}  # naive UTC datetime or None
                    for row in cur.fetchall()]
            cur.execute("SELECT COALESCE(SUM(questions), 0) AS n FROM usage_daily WHERE user_id = %s", (user_id,))
            total = int(cur.fetchone()["n"])
            cur.execute("SELECT COUNT(*) AS chats, COALESCE(SUM((SELECT COUNT(*) FROM messages m "
                        "WHERE m.conversation_id = c.id)), 0) AS messages FROM conversations c WHERE c.user_id = %s",
                        (user_id,))
            saved = cur.fetchone()
            return {"days": days, "total_questions": total,
                    "saved": {"chats": int(saved["chats"]), "messages": int(saved["messages"])}}
        return self._run(work)

    # ------------------------------------------------------------------ upgrade requests
    def latest_request(self, user_id: int) -> Optional[dict]:
        """The person's pending request, else their most recent decided one."""
        def work(cur):
            cur.execute("SELECT * FROM plan_requests WHERE user_id = %s AND status <> 'cancelled' "
                        "ORDER BY status = 'pending' DESC, id DESC LIMIT 1", (user_id,))
            return self._request(cur.fetchone())
        return self._run(work)

    def request_plan(self, user_id: int, plan_code: str, note: Optional[str]) -> dict:
        """Asks for a bigger plan; replaces an earlier pending request. Raises ValueError when not allowed."""
        def work(cur):
            current = self._user_plan(cur, user_id)
            cur.execute("SELECT * FROM plans WHERE code = %s", (plan_code,))
            row = cur.fetchone()
            if row is None:
                raise ValueError("There is no such plan.")
            wanted = self._plan(row)
            if not wanted["requestable"]:
                raise ValueError(f"The {wanted['name']} plan can't be requested.")
            if wanted["sort_order"] <= current["sort_order"]:
                raise ValueError(f"You're already on {current['name']}, which is the same or more than {wanted['name']}.")
            cur.execute("UPDATE plan_requests SET status = 'cancelled', decided_at = CURRENT_TIMESTAMP(3) "
                        "WHERE user_id = %s AND status = 'pending'", (user_id,))
            cur.execute("INSERT INTO plan_requests (user_id, plan_code, from_plan, note) VALUES (%s, %s, %s, %s)",
                        (user_id, plan_code, current["code"], (note or None)))
            cur.execute("SELECT * FROM plan_requests WHERE id = LAST_INSERT_ID()")
            return self._request(cur.fetchone())
        return self._run(work)

    def cancel_request(self, user_id: int) -> bool:
        def work(cur):
            cur.execute("UPDATE plan_requests SET status = 'cancelled', decided_at = CURRENT_TIMESTAMP(3) "
                        "WHERE user_id = %s AND status = 'pending'", (user_id,))
            return cur.rowcount > 0
        return self._run(work)

    # ------------------------------------------------------------------ super admins
    def admin_requests(self, status: Optional[str] = None, limit: int = 200) -> list:
        def work(cur):
            if status:
                cur.execute("SELECT * FROM plan_requests WHERE status = %s ORDER BY id DESC LIMIT %s", (status, limit))
            else:
                cur.execute("SELECT * FROM plan_requests WHERE status <> 'cancelled' ORDER BY id DESC LIMIT %s", (limit,))
            return [self._request(row) for row in cur.fetchall()]
        return self._run(work)

    def decide_request(self, request_id: int, approve: bool, admin_id: int) -> Optional[dict]:
        """Approves (the person moves to the plan) or declines a pending request. None if not pending."""
        def work(cur):
            cur.execute("SELECT * FROM plan_requests WHERE id = %s AND status = 'pending' FOR UPDATE", (request_id,))
            row = cur.fetchone()
            if row is None:
                return None
            cur.execute("UPDATE plan_requests SET status = %s, decided_at = CURRENT_TIMESTAMP(3), decided_by = %s "
                        "WHERE id = %s", ("approved" if approve else "declined", admin_id, request_id))
            if approve:
                cur.execute("INSERT INTO user_plans (user_id, plan_code, updated_by) VALUES (%s, %s, %s) "
                            "ON DUPLICATE KEY UPDATE plan_code = VALUES(plan_code), updated_by = VALUES(updated_by)",
                            (row["user_id"], row["plan_code"], admin_id))
            cur.execute("SELECT * FROM plan_requests WHERE id = %s", (request_id,))
            return self._request(cur.fetchone())
        return self._run(work)

    def set_plan(self, user_id: int, plan_code: str, admin_id: int) -> bool:
        """A super admin puts someone on a plan (any plan). False if there is no such plan."""
        def work(cur):
            cur.execute("SELECT 1 FROM plans WHERE code = %s", (plan_code,))
            if cur.fetchone() is None:
                return False
            cur.execute("INSERT INTO user_plans (user_id, plan_code, updated_by) VALUES (%s, %s, %s) "
                        "ON DUPLICATE KEY UPDATE plan_code = VALUES(plan_code), updated_by = VALUES(updated_by)",
                        (user_id, plan_code, admin_id))
            # a pending request is answered by this
            cur.execute("UPDATE plan_requests SET status = 'approved', decided_at = CURRENT_TIMESTAMP(3), decided_by = %s "
                        "WHERE user_id = %s AND status = 'pending' AND plan_code = %s", (admin_id, user_id, plan_code))
            return True
        return self._run(work)

    def admin_users(self, today, month_start) -> list:
        """Everyone with a plan or any questions: plan, questions today and this month, all time."""
        def work(cur):
            cur.execute(
                "SELECT ids.user_id, u.plan_code, u.updated_at, "
                "  (SELECT COALESCE(SUM(questions), 0) FROM usage_daily d WHERE d.user_id = ids.user_id AND d.day = %s) AS today, "
                "  (SELECT COALESCE(SUM(questions), 0) FROM usage_daily d WHERE d.user_id = ids.user_id AND d.day >= %s) AS month, "
                "  (SELECT COALESCE(SUM(questions), 0) FROM usage_daily d WHERE d.user_id = ids.user_id) AS total "
                "FROM (SELECT user_id FROM user_plans UNION SELECT user_id FROM usage_daily) ids "
                "LEFT JOIN user_plans u ON u.user_id = ids.user_id ORDER BY ids.user_id",
                (today, month_start))
            return [{"user_id": int(row["user_id"]), "plan": row["plan_code"] or self.DEFAULT_PLAN,
                     "plan_updated_at": _iso(row["updated_at"]), "today": int(row["today"]),
                     "month": int(row["month"]), "total": int(row["total"])} for row in cur.fetchall()]
        return self._run(work)
