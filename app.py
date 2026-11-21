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

Plans (sql/002_chat_plans.sql): each signed-in person may ask their plan's number of questions a day and a week
(India time; weeks run Monday to Sunday); a question over either limit gets 429. Super admins (asked from authz-api)
have no limit.
  GET    /api/chat/usage                  plan, today and this week against the limits, an "at this pace" warning,
                                          questions per day for 30 days, saved chats
  GET    /api/chat/plans                  the plans, yours, and your latest upgrade request
  POST   /api/chat/plan-requests          {"plan", "note"?} ask for a bigger plan (no payments: an admin approves)
  DELETE /api/chat/plan-requests/current  cancel your pending request
  /api/chat/admin/...                     super admins: requests (approve/decline), everyone's plan and usage

History lives in MySQL chat_db (src/chat_store.py, sql/001_chat_db.sql); without the chat-secrets
Secret (CHAT_DB_HOST) chat works as before and nothing is kept.
"""
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from flask import Flask, jsonify, request
from src import authz_client
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
# Daily limits count India days (no daylight saving, so a fixed offset is exact)
DAY_ZONE = timezone(timedelta(minutes=int(os.getenv("CHAT_DAY_UTC_OFFSET_MINUTES", "330"))))
# nginx's per-visitor limit on questions (aisoup-locations.conf, zone ats_chat), shown on the usage page
RATE_PER_MINUTE = int(os.getenv("CHAT_RATE_PER_MINUTE", "10"))
USAGE_DAYS = 30
# Admin changes must carry this header (another site can't add it), as in auth-api
CSRF_HEADER_VALUE = "AITradeSoup"


def _error(message: str, status: int):
    return jsonify({"error": message}), status


def current_user():
    """The signed-in person's user id from nginx, or None (LAN server, no sign-in)."""
    raw = request.headers.get("X-Auth-User-Id", "").strip()
    return int(raw) if raw.isdigit() else None


def history_enabled(user) -> bool:
    return STORE is not None and user is not None


def today():
    return datetime.now(DAY_ZONE).date()


def week_start(day):
    """The Monday that starts day's week."""
    return day - timedelta(days=day.weekday())


def midnight(day) -> datetime:
    return datetime.combine(day, datetime.min.time(), DAY_ZONE)


def resets_at() -> str:
    """When today's count starts again: the next midnight, India time."""
    return midnight(today() + timedelta(days=1)).isoformat()


def week_resets_at() -> str:
    """When this week's count starts again: next Monday at midnight, India time."""
    return midnight(week_start(today()) + timedelta(days=7)).isoformat()


def usage_summary(reserved: dict) -> dict:
    return {"used": reserved["used"], "limit": reserved["limit"], "plan": reserved["plan"]["name"],
            "plan_code": reserved["plan"]["code"], "resets_at": resets_at(),
            "week_used": reserved["week_used"], "week_limit": reserved["week_limit"], "week_resets_at": week_resets_at()}


def limit_message(reserved: dict) -> str:
    plan = reserved["plan"]
    if reserved["reason"] == "week":
        return (f"You've asked all {reserved['week_limit']} of this week's questions on the {plan['name']} plan. "
                "The count starts again on Monday at midnight (India time). Upgrade your plan for more questions.")
    return (f"You've asked all {reserved['limit']} of today's questions on the {plan['name']} plan. "
            "The count starts again at midnight (India time). Upgrade your plan for more questions a day.")


def runs_out_at(now: datetime, used: int, limit, since: datetime, resets: datetime, min_hours: float):
    """When the limit would be used up if questions keep coming at the rate since `since` (at least min_hours,
    so a quick start doesn't sound an alarm), or None if that is after the reset or there's no limit."""
    if limit is None or used < 3 or used >= limit:
        return None
    hours = max(min_hours, (now - since).total_seconds() / 3600)
    out = now + timedelta(hours=(limit - used) * hours / used)
    return out if out < resets else None


def pace_warning(now: datetime, today_used: int, today_limit, first_today, week_used: int, week_limit):
    """The sooner of today's and this week's run-out times, if either comes before its reset."""
    day = today()
    since_today = first_today.replace(tzinfo=timezone.utc) if first_today else midnight(day)
    candidates = [
        ("today", runs_out_at(now, today_used, today_limit, since_today, midnight(day + timedelta(days=1)), 1.0),
         resets_at()),
        ("week", runs_out_at(now, week_used, week_limit, midnight(week_start(day)),
                             midnight(week_start(day) + timedelta(days=7)), 12.0), week_resets_at()),
    ]
    found = [(when, window, resets) for window, when, resets in candidates if when is not None]
    if not found:
        return None
    when, window, resets = min(found)
    return {"window": window, "runs_out_at": when.isoformat(), "resets_at": resets}


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

    # The daily and weekly limits (signed in only): count this question first, give it back if the model fails
    reserved = None
    day = today()
    if history_enabled(user):
        try:
            reserved = STORE.reserve_question(user, day, week_start(day), datetime.now(timezone.utc).replace(tzinfo=None),
                                              unlimited=authz_client.is_super_admin_or_false(user))
        except StoreUnavailable:
            reserved = None  # can't count right now: answer anyway rather than refuse everyone
        if reserved is not None and not reserved["allowed"]:
            body = {"error": limit_message(reserved), "limit_reached": True, "usage": usage_summary(reserved)}
            return jsonify(body), 429

    started = time.monotonic()
    try:
        reply = chat_with_messages(build_messages(history, prompt), model=DEPLOYMENT)
    except Exception as exc:  # the model server is down or refused the request
        log.exception("model call failed")
        if reserved is not None:
            try:
                STORE.release_question(user, day)
            except StoreUnavailable:
                pass
        return _error(str(exc), 500)
    elapsed_ms = int((time.monotonic() - started) * 1000)

    if not history_enabled(user):
        return jsonify({"response": reply, "saved": False, "history_enabled": False})
    usage = usage_summary(reserved) if reserved is not None else None
    if reserved is not None:
        try:
            STORE.record_answer_time(user, day, elapsed_ms)
        except StoreUnavailable:
            pass
    try:
        saved = STORE.add_exchange(user, conversation_id, prompt, reply, DEPLOYMENT, elapsed_ms)
    except StoreUnavailable:
        # The answer is still worth showing; the page says it wasn't saved
        return jsonify({"response": reply, "saved": False, "history_enabled": True, "conversation_id": conversation_id,
                        "usage": usage})
    if saved is None:  # deleted in another tab while the model was answering
        return jsonify({"response": reply, "saved": False, "history_enabled": True, "usage": usage})
    return jsonify({"response": reply, "saved": True, "history_enabled": True,
                    "conversation_id": saved["id"], "title": saved["title"], "usage": usage})


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


# ---------------------------------------------------------------- usage and plans (the signed-in person's own)
def _signed_in_store_call(call):
    """call(user) for a signed-in person with the database; 404 on the LAN server (never 401: see above)."""
    user = current_user()
    if not history_enabled(user):
        return _error("Usage and plans need sign-in at aitradesoup.com.", 404)
    try:
        return call(user)
    except StoreUnavailable:
        return _error("Usage and plans are unavailable right now.", 503)


@app.get("/api/chat/usage")
def usage():
    def call(user):
        day = today()
        first = day - timedelta(days=USAGE_DAYS - 1)
        unlimited = authz_client.is_super_admin_or_false(user)
        plan = STORE.user_plan(user)
        data = STORE.usage(user, first, day)
        by_day = {item["day"]: item for item in data["days"]}
        days = []
        for offset in range(USAGE_DAYS):
            d = (first + timedelta(days=offset)).isoformat()
            item = by_day.get(d, {"questions": 0, "answer_ms": 0})
            days.append({"day": d, "questions": item["questions"]})
        answered = sum(item["questions"] for item in data["days"])
        answer_ms = sum(item["answer_ms"] for item in data["days"])
        month_start = day.replace(day=1).isoformat()
        monday = week_start(day)
        week_used = sum(item["questions"] for item in data["days"] if item["day"] >= monday.isoformat())
        today_limit = None if unlimited else plan["daily_questions"]
        week_limit = None if unlimited else plan["weekly_questions"]
        first_today = by_day.get(day.isoformat(), {}).get("first_question_at")
        return jsonify({
            "plan": plan,
            "unlimited": unlimited,
            "today": {"day": day.isoformat(), "questions": days[-1]["questions"],
                      "limit": today_limit, "resets_at": resets_at()},
            "week": {"start": monday.isoformat(), "questions": week_used, "limit": week_limit,
                     "resets_at": week_resets_at()},
            "pace": pace_warning(datetime.now(timezone.utc), days[-1]["questions"], today_limit, first_today,
                                 week_used, week_limit),
            "days": days,
            "month_questions": sum(item["questions"] for item in data["days"] if item["day"] >= month_start),
            "total_questions": data["total_questions"],
            "average_answer_seconds": round(answer_ms / answered / 1000, 1) if answered and answer_ms else None,
            "saved": data["saved"],
            "rate_per_minute": RATE_PER_MINUTE,
        })
    return _signed_in_store_call(call)


@app.get("/api/chat/plans")
def plans():
    def call(user):
        current = STORE.user_plan(user)
        return jsonify({"plans": STORE.plans(), "current": current["code"],
                        "unlimited": authz_client.is_super_admin_or_false(user),
                        "request": STORE.latest_request(user)})
    return _signed_in_store_call(call)


@app.post("/api/chat/plan-requests")
def request_plan():
    payload = request.get_json(silent=True) or {}
    plan = str(payload.get("plan") or "").strip()
    note = " ".join(str(payload.get("note") or "").split())[:500] or None
    if not plan:
        return _error("Choose a plan.", 400)

    def call(user):
        try:
            return jsonify(STORE.request_plan(user, plan, note)), 201
        except ValueError as exc:
            return _error(str(exc), 400)
    return _signed_in_store_call(call)


@app.delete("/api/chat/plan-requests/current")
def cancel_plan_request():
    def call(user):
        if not STORE.cancel_request(user):
            return _error("You have no pending request.", 404)
        return jsonify({"cancelled": True})
    return _signed_in_store_call(call)


# ---------------------------------------------------------------- super admins
def _admin_call(call, mutate: bool = False):
    """call(admin_user_id) for a super admin. nginx's authz already limits /api/chat/admin/ to super admins;
    this checks again, so the endpoints stay closed whatever mode authorization is in."""
    user = current_user()
    if not history_enabled(user):
        return _error("Not available here.", 404)
    try:
        if not authz_client.is_super_admin(user):
            return _error("Only a super admin can manage Ramen Chat plans.", 403)
    except authz_client.AuthzUnavailable:
        return _error("The authorization service is not reachable.", 503)
    if mutate and request.headers.get("X-Requested-With") != CSRF_HEADER_VALUE:
        return _error("Missing X-Requested-With header.", 403)
    try:
        return call(user)
    except StoreUnavailable:
        return _error("Ramen Chat plans are unavailable right now.", 503)


@app.get("/api/chat/admin/overview")
def admin_overview():
    def call(_admin):
        day = today()
        return jsonify({"plans": STORE.plans(), "requests": STORE.admin_requests(),
                        "users": STORE.admin_users(day, day.replace(day=1)), "default_plan": STORE.DEFAULT_PLAN})
    return _admin_call(call)


@app.post("/api/chat/admin/plan-requests/<int:request_id>/decision")
def admin_decide(request_id: int):
    approve = (request.get_json(silent=True) or {}).get("approve")
    if not isinstance(approve, bool):
        return _error("Say approve: true or false.", 400)

    def call(admin):
        decided = STORE.decide_request(request_id, approve, admin)
        return jsonify(decided) if decided else _error("That request isn't pending any more.", 404)
    return _admin_call(call, mutate=True)


@app.put("/api/chat/admin/users/<int:user_id>/plan")
def admin_set_plan(user_id: int):
    plan = str((request.get_json(silent=True) or {}).get("plan") or "").strip()

    def call(admin):
        if not STORE.set_plan(user_id, plan, admin):
            return _error("There is no such plan.", 400)
        return jsonify({"user_id": user_id, "plan": plan})
    return _admin_call(call, mutate=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=True)
