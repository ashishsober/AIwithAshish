"""Qwen chat API (chat-api pod, port 5002), behind the Mac's nginx at /api/chat and /api/chat/.

Who is asking: nginx passes the signed-in person's auth_db user id as X-Auth-User-Id (nginx always
overwrites it, so a browser cannot set its own). On the LAN server (:8080, no sign-in) it is absent.

  POST /api/chat                          {"prompt", "conversation_id"?}  ask a question
       signed in:     the conversation's earlier messages are sent to the model as context and the
                      question and answer are saved; no conversation_id starts a new conversation
       not signed in: nothing is saved; the page may send "history" ([{role, content}]) for context
  GET  /api/chat/conversations            the person's conversations, newest first
  GET  /api/chat/conversations/<id>       one conversation with its messages
  PATCH  /api/chat/conversations/<id>     {"title"} rename
  DELETE /api/chat/conversations/<id>     delete it and its messages

History lives in MySQL chat_db (src/chat_store.py, sql/001_chat_db.sql); without the chat-secrets
Secret (CHAT_DB_HOST) chat works as before and nothing is kept.
"""
import logging
import os
import re
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from flask import Flask, jsonify, request
from src.chat_store import ChatStore, StoreUnavailable
from src.openai.azureai_config import DEPLOYMENT, chat_with_messages

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("chat_api")

app = Flask(__name__)
STORE = ChatStore.from_env()

# How much of the conversation goes to the model with each question: the newest messages that fit
# (characters, about 4 per token; the model's context is far larger, this keeps answers quick)
CONTEXT_CHARS = int(os.getenv("CHAT_CONTEXT_CHARS", "60000"))
MAX_PROMPT_CHARS = int(os.getenv("CHAT_MAX_PROMPT_CHARS", "60000"))
MAX_TITLE_CHARS = 200
CONVERSATION_ID = re.compile(r"^[0-9a-f]{32}$")
# Qwen3's reasoning, if a reply carries it: shown to the reader, but not sent back as context
THINKING = re.compile(r"<think>.*?</think>\s*", re.S)


def _error(message: str, status: int):
    return jsonify({"error": message}), status


def current_user():
    """The signed-in person's user id from nginx, or None (LAN server, no sign-in)."""
    raw = request.headers.get("X-Auth-User-Id", "").strip()
    return int(raw) if raw.isdigit() else None


def history_enabled(user) -> bool:
    return STORE is not None and user is not None


def build_messages(history: list, prompt: str) -> list:
    """The newest earlier messages that fit in CONTEXT_CHARS, oldest first, then the new question.
    The kept part always starts with a question, as the model expects."""
    kept = []
    used = len(prompt)
    for message in reversed(history):
        text = message["content"]
        if message["role"] == "assistant":
            text = THINKING.sub("", text)
        if used + len(text) > CONTEXT_CHARS:
            break
        kept.append({"role": message["role"], "content": text})
        used += len(text)
    kept.reverse()
    while kept and kept[0]["role"] != "user":
        kept.pop(0)
    return kept + [{"role": "user", "content": prompt}]


def client_history(raw) -> list:
    """History sent by the page when nothing is saved (LAN): only well-formed user/assistant messages."""
    if not isinstance(raw, list):
        return []
    return [{"role": item["role"], "content": item["content"]} for item in raw[-200:]
            if isinstance(item, dict) and item.get("role") in ("user", "assistant") and isinstance(item.get("content"), str)]


@app.route("/api/chat", methods=["GET", "POST"])
def chat_api():
    if request.method == "GET":
        payload = {"prompt": request.args.get("prompt", "")}
    else:
        payload = request.get_json(silent=True) or {}
    prompt = str(payload.get("prompt") or payload.get("context") or "").strip()
    if not prompt:
        return _error("Prompt is required.", 400)
    if len(prompt) > MAX_PROMPT_CHARS:
        return _error(f"The message is too long ({len(prompt):,} characters; the limit is {MAX_PROMPT_CHARS:,}).", 413)

    user = current_user()
    conversation_id = payload.get("conversation_id") or None
    if conversation_id is not None and (not isinstance(conversation_id, str) or not CONVERSATION_ID.match(conversation_id)):
        return _error("Conversation not found.", 404)

    if history_enabled(user):
        history = []
        if conversation_id:
            try:
                conversation = STORE.get_conversation(user, conversation_id)
            except StoreUnavailable:
                return _error("Chat history is unavailable right now, so this conversation can't be continued. "
                              "Start a new chat or try again shortly.", 503)
            if conversation is None:
                return _error("Conversation not found.", 404)
            history = conversation["messages"]
    else:
        history = client_history(payload.get("history"))

    started = time.monotonic()
    try:
        reply = chat_with_messages(build_messages(history, prompt), model=DEPLOYMENT)
    except Exception as exc:  # the model server is down or refused the request
        log.exception("model call failed")
        return _error(str(exc), 500)
    elapsed_ms = int((time.monotonic() - started) * 1000)

    if not history_enabled(user):
        return jsonify({"response": reply, "saved": False, "history_enabled": False})
    try:
        saved = STORE.add_exchange(user, conversation_id, prompt, reply, DEPLOYMENT, elapsed_ms)
    except StoreUnavailable:
        # The answer is still worth showing; the page says it wasn't saved
        return jsonify({"response": reply, "saved": False, "history_enabled": True, "conversation_id": conversation_id})
    if saved is None:  # deleted in another tab while the model was answering
        return jsonify({"response": reply, "saved": False, "history_enabled": True})
    return jsonify({"response": reply, "saved": True, "history_enabled": True,
                    "conversation_id": saved["id"], "title": saved["title"]})


@app.get("/api/chat/conversations")
def list_conversations():
    user = current_user()
    if not history_enabled(user):
        # LAN server (no sign-in) or no database: the page keeps the chat in memory only
        return jsonify({"history_enabled": False, "items": []})
    try:
        return jsonify({"history_enabled": True, "items": STORE.list_conversations(user)})
    except StoreUnavailable:
        return _error("Chat history is unavailable right now.", 503)


def _owned_conversation_call(conversation_id: str, call):
    user = current_user()
    if not history_enabled(user):
        # Not 401: the app treats a 401 from /api as an ended session and sends the person to sign in
        return _error("Chat history isn't available here (it needs sign-in at aitradesoup.com).", 404)
    if not CONVERSATION_ID.match(conversation_id):
        return _error("Conversation not found.", 404)
    try:
        return call(user)
    except StoreUnavailable:
        return _error("Chat history is unavailable right now.", 503)


@app.get("/api/chat/conversations/<conversation_id>")
def get_conversation(conversation_id: str):
    def call(user):
        conversation = STORE.get_conversation(user, conversation_id)
        return jsonify(conversation) if conversation else _error("Conversation not found.", 404)
    return _owned_conversation_call(conversation_id, call)


@app.patch("/api/chat/conversations/<conversation_id>")
def rename_conversation(conversation_id: str):
    title = " ".join(str((request.get_json(silent=True) or {}).get("title") or "").split())[:MAX_TITLE_CHARS]
    if not title:
        return _error("Title is required.", 400)

    def call(user):
        if not STORE.rename(user, conversation_id, title):
            return _error("Conversation not found.", 404)
        return jsonify({"id": conversation_id, "title": title})
    return _owned_conversation_call(conversation_id, call)


@app.delete("/api/chat/conversations/<conversation_id>")
def delete_conversation(conversation_id: str):
    def call(user):
        if not STORE.delete(user, conversation_id):
            return _error("Conversation not found.", 404)
        return jsonify({"deleted": conversation_id})
    return _owned_conversation_call(conversation_id, call)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=True)
