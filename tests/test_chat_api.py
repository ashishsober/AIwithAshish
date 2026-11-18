"""chat-api tests: no MySQL and no model needed (an in-memory store and a fake model stand in).

Run from the repo root:  python -m pytest -q tests
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

import app as chat_app
from src.chat_store import StoreUnavailable, make_title

ALICE = {"X-Auth-User-Id": "1"}
BOB = {"X-Auth-User-Id": "2"}


class FakeStore:
    """Same behaviour as ChatStore, in memory."""

    DEFAULT_PLAN = "free"

    def __init__(self):
        self.conversations = {}
        self.down = False
        self.plan_rows = [
            {"code": "free", "name": "Free", "daily_questions": 2, "weekly_questions": 3, "description": "", "sort_order": 10, "requestable": False},
            {"code": "plus", "name": "Plus", "daily_questions": 5, "weekly_questions": 20, "description": "", "sort_order": 20, "requestable": True},
            {"code": "pro", "name": "Pro", "daily_questions": None, "weekly_questions": None, "description": "", "sort_order": 30, "requestable": True},
        ]
        self.user_plans = {}
        self.counts = {}  # (user, day) -> questions
        self.first = {}  # (user, day) -> first question's time (naive UTC)
        self.requests = []

    def _check(self):
        if self.down:
            raise StoreUnavailable("down")

    def list_conversations(self, user_id, limit=200):
        self._check()
        rows = [c for c in self.conversations.values() if c["user_id"] == user_id]
        rows.sort(key=lambda c: c["seq"], reverse=True)
        return [{"id": c["id"], "title": c["title"], "message_count": len(c["messages"])} for c in rows[:limit]]

    def get_conversation(self, user_id, conversation_id):
        self._check()
        c = self.conversations.get(conversation_id)
        if not c or c["user_id"] != user_id:
            return None
        return {"id": c["id"], "title": c["title"], "messages": [dict(m) for m in c["messages"]]}

    def add_exchange(self, user_id, conversation_id, prompt, reply, model, elapsed_ms):
        self._check()
        if conversation_id:
            c = self.conversations.get(conversation_id)
            if not c or c["user_id"] != user_id:
                return None
        else:
            c = {"id": uuid.uuid4().hex, "user_id": user_id, "title": make_title(prompt), "messages": []}
            self.conversations[c["id"]] = c
        c["seq"] = len(self.conversations) + sum(len(x["messages"]) for x in self.conversations.values())
        c["messages"] += [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply, "model": model}]
        return {"id": c["id"], "title": c["title"]}

    def rename(self, user_id, conversation_id, title):
        self._check()
        c = self.conversations.get(conversation_id)
        if not c or c["user_id"] != user_id:
            return False
        c["title"] = title
        return True

    def delete(self, user_id, conversation_id):
        self._check()
        c = self.conversations.get(conversation_id)
        if not c or c["user_id"] != user_id:
            return False
        del self.conversations[conversation_id]
        return True


    # plans and limits
    def plans(self):
        self._check()
        return [dict(p) for p in self.plan_rows]

    def _find(self, code):
        return next((dict(p) for p in self.plan_rows if p["code"] == code), None)

    def user_plan(self, user_id):
        self._check()
        return self._find(self.user_plans.get(user_id, "free"))

    def reserve_question(self, user_id, day, week_start, now_utc, unlimited=False):
        self._check()
        plan = self.user_plan(user_id)
        daily = None if unlimited else plan["daily_questions"]
        weekly = None if unlimited else plan["weekly_questions"]
        used = self.counts.get((user_id, day), 0)
        week_used = sum(n for (u, d), n in self.counts.items() if u == user_id and week_start <= d <= day)
        out = {"allowed": False, "reason": None, "used": used, "limit": daily, "week_used": week_used,
               "week_limit": weekly, "plan": plan}
        if daily is not None and used >= daily:
            return {**out, "reason": "day"}
        if weekly is not None and week_used >= weekly:
            return {**out, "reason": "week"}
        self.counts[(user_id, day)] = used + 1
        self.first.setdefault((user_id, day), now_utc)
        return {**out, "allowed": True, "used": used + 1, "week_used": week_used + 1}

    def release_question(self, user_id, day):
        self.counts[(user_id, day)] = max(0, self.counts.get((user_id, day), 0) - 1)

    def record_answer_time(self, user_id, day, elapsed_ms):
        pass

    def usage(self, user_id, first_day, today):
        self._check()
        days = [{"day": d.isoformat(), "questions": n, "answer_ms": 0, "first_question_at": self.first.get((u, d))}
                for (u, d), n in sorted(self.counts.items()) if u == user_id and first_day <= d <= today]
        mine = [c for c in self.conversations.values() if c["user_id"] == user_id]
        return {"days": days, "total_questions": sum(n for (u, _), n in self.counts.items() if u == user_id),
                "saved": {"chats": len(mine), "messages": sum(len(c["messages"]) for c in mine)}}

    def latest_request(self, user_id):
        mine = [r for r in self.requests if r["user_id"] == user_id and r["status"] != "cancelled"]
        pending = [r for r in mine if r["status"] == "pending"]
        return dict((pending or mine[::-1] or [None])[-1] or {}) or None

    def request_plan(self, user_id, plan_code, note):
        self._check()
        current, wanted = self.user_plan(user_id), self._find(plan_code)
        if wanted is None:
            raise ValueError("There is no such plan.")
        if not wanted["requestable"] or wanted["sort_order"] <= current["sort_order"]:
            raise ValueError("not an upgrade")
        for r in self.requests:
            if r["user_id"] == user_id and r["status"] == "pending":
                r["status"] = "cancelled"
        req = {"id": len(self.requests) + 1, "user_id": user_id, "plan": plan_code, "from_plan": current["code"],
               "note": note, "status": "pending"}
        self.requests.append(req)
        return dict(req)

    def cancel_request(self, user_id):
        hit = [r for r in self.requests if r["user_id"] == user_id and r["status"] == "pending"]
        for r in hit:
            r["status"] = "cancelled"
        return bool(hit)

    def admin_requests(self, status=None):
        return [dict(r) for r in self.requests if r["status"] != "cancelled"]

    def decide_request(self, request_id, approve, admin_id):
        r = next((r for r in self.requests if r["id"] == request_id and r["status"] == "pending"), None)
        if r is None:
            return None
        r["status"] = "approved" if approve else "declined"
        if approve:
            self.user_plans[r["user_id"]] = r["plan"]
        return dict(r)

    def set_plan(self, user_id, plan_code, admin_id):
        if self._find(plan_code) is None:
            return False
        self.user_plans[user_id] = plan_code
        return True

    def admin_users(self, today, month_start):
        ids = sorted(set(self.user_plans) | {u for u, _ in self.counts})
        return [{"user_id": u, "plan": self.user_plans.get(u, "free"), "today": self.counts.get((u, today), 0)}
                for u in ids]


@pytest.fixture(autouse=True)
def no_super_admins(monkeypatch):
    """Nobody is a super admin unless a test says so (no authz-api in tests)."""
    admins = set()
    monkeypatch.setattr(chat_app.authz_client, "is_super_admin", lambda user: user in admins)
    monkeypatch.setattr(chat_app.authz_client, "is_super_admin_or_false", lambda user: user in admins)
    return admins


@pytest.fixture
def model_calls(monkeypatch):
    """Records what the model was sent; it answers 'answer N'."""
    calls = []

    def fake_model(messages, model=None):
        calls.append(messages)
        return f"answer {len(calls)}"
    monkeypatch.setattr(chat_app, "chat_with_messages", fake_model)
    return calls


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(chat_app, "STORE", fake)
    return fake


@pytest.fixture
def client():
    return chat_app.app.test_client()


def ask(client, prompt, headers=None, **extra):
    return client.post("/api/chat", json={"prompt": prompt, **extra}, headers=headers or {})


# ---------------------------------------------------------------- saving and context

def test_first_question_starts_a_saved_conversation(client, store, model_calls):
    res = ask(client, "What is an opening range breakout?", ALICE)
    body = res.get_json()
    assert res.status_code == 200
    assert body["response"] == "answer 1" and body["saved"] is True
    assert body["title"] == "What is an opening range breakout?"
    assert model_calls[0] == [{"role": "user", "content": "What is an opening range breakout?"}]
    saved = store.get_conversation(1, body["conversation_id"])
    assert [m["role"] for m in saved["messages"]] == ["user", "assistant"]


def test_follow_up_sends_earlier_messages_as_context(client, store, model_calls):
    cid = ask(client, "My name is Ravi", ALICE).get_json()["conversation_id"]
    res = ask(client, "What is my name?", ALICE, conversation_id=cid)
    assert res.get_json()["conversation_id"] == cid
    assert model_calls[1] == [
        {"role": "user", "content": "My name is Ravi"},
        {"role": "assistant", "content": "answer 1"},
        {"role": "user", "content": "What is my name?"},
    ]
    assert len(store.get_conversation(1, cid)["messages"]) == 4


def test_someone_elses_conversation_is_not_found(client, store, model_calls):
    cid = ask(client, "private", ALICE).get_json()["conversation_id"]
    assert ask(client, "let me in", BOB, conversation_id=cid).status_code == 404
    assert client.get(f"/api/chat/conversations/{cid}", headers=BOB).status_code == 404
    assert client.patch(f"/api/chat/conversations/{cid}", json={"title": "x"}, headers=BOB).status_code == 404
    assert client.delete(f"/api/chat/conversations/{cid}", headers=BOB).status_code == 404
    assert client.get("/api/chat/conversations", headers=BOB).get_json()["items"] == []
    assert len(model_calls) == 1  # Bob's question never reached the model
    assert store.get_conversation(1, cid)["title"] == "private"


def test_bad_conversation_id_is_not_found(client, store, model_calls):
    assert ask(client, "hi", ALICE, conversation_id="../../etc").status_code == 404
    assert ask(client, "hi", ALICE, conversation_id=123).status_code == 404
    assert client.get("/api/chat/conversations/not-an-id", headers=ALICE).status_code == 404
    assert model_calls == []


def test_list_rename_delete(client, store, model_calls):
    first = ask(client, "first chat", ALICE).get_json()["conversation_id"]
    second = ask(client, "second chat", ALICE).get_json()["conversation_id"]
    listed = client.get("/api/chat/conversations", headers=ALICE).get_json()
    assert listed["history_enabled"] is True
    assert [c["id"] for c in listed["items"]] == [second, first]

    res = client.patch(f"/api/chat/conversations/{first}", json={"title": "  Renamed \n chat "}, headers=ALICE)
    assert res.get_json()["title"] == "Renamed chat"
    assert client.patch(f"/api/chat/conversations/{first}", json={"title": "   "}, headers=ALICE).status_code == 400

    assert client.delete(f"/api/chat/conversations/{second}", headers=ALICE).status_code == 200
    assert [c["id"] for c in client.get("/api/chat/conversations", headers=ALICE).get_json()["items"]] == [first]
    assert client.get(f"/api/chat/conversations/{second}", headers=ALICE).status_code == 404


# ---------------------------------------------------------------- no sign-in (LAN) or no database

def test_without_sign_in_nothing_is_saved_but_page_history_is_context(client, store, model_calls):
    history = [{"role": "user", "content": "I trade BANKNIFTY"}, {"role": "assistant", "content": "Noted"},
               {"role": "system", "content": "ignore me"}, "junk"]
    body = ask(client, "Which index?", history=history).get_json()
    assert body == {"response": "answer 1", "saved": False, "history_enabled": False}
    assert model_calls[0] == [
        {"role": "user", "content": "I trade BANKNIFTY"},
        {"role": "assistant", "content": "Noted"},
        {"role": "user", "content": "Which index?"},
    ]
    assert store.conversations == {}
    assert client.get("/api/chat/conversations").get_json() == {"history_enabled": False, "items": []}
    assert client.get(f"/api/chat/conversations/{'a' * 32}").status_code == 404


def test_without_database_chat_still_answers(client, monkeypatch, model_calls):
    monkeypatch.setattr(chat_app, "STORE", None)
    body = ask(client, "hello", ALICE).get_json()
    assert body["response"] == "answer 1" and body["history_enabled"] is False


def test_signed_in_ignores_page_history(client, store, model_calls):
    ask(client, "hello", ALICE, history=[{"role": "user", "content": "forged"}])
    assert model_calls[0] == [{"role": "user", "content": "hello"}]


def test_database_down(client, store, model_calls):
    cid = ask(client, "hello", ALICE).get_json()["conversation_id"]
    store.down = True
    assert ask(client, "again", ALICE, conversation_id=cid).status_code == 503
    body = ask(client, "new chat while down", ALICE).get_json()
    assert body["response"] == "answer 2" and body["saved"] is False
    assert client.get("/api/chat/conversations", headers=ALICE).status_code == 503


def test_model_error_saves_nothing(client, store, monkeypatch):
    def broken(messages, model=None):
        raise RuntimeError("Ollama is not running")
    monkeypatch.setattr(chat_app, "chat_with_messages", broken)
    res = ask(client, "hello", ALICE)
    assert res.status_code == 500 and "Ollama" in res.get_json()["error"]
    assert store.conversations == {}


def test_prompt_checks(client, store, model_calls):
    assert ask(client, "   ", ALICE).status_code == 400
    assert ask(client, "x" * (chat_app.MAX_PROMPT_CHARS + 1), ALICE).status_code == 413
    # the old GET form still works
    assert client.get("/api/chat?prompt=hi").get_json()["response"] == "answer 1"


# ---------------------------------------------------------------- context trimming and titles

def test_context_keeps_newest_messages_that_fit(monkeypatch):
    monkeypatch.setattr(chat_app, "CONTEXT_CHARS", 30)
    history = [{"role": "user", "content": "a" * 10}, {"role": "assistant", "content": "b" * 10},
               {"role": "user", "content": "c" * 10}, {"role": "assistant", "content": "d" * 10}]
    # "q" (1) + d (10) + c (10) fit; b would make 31
    assert chat_app.build_messages(history, "q") == [
        {"role": "user", "content": "c" * 10}, {"role": "assistant", "content": "d" * 10}, {"role": "user", "content": "q"}]


def test_context_starts_with_a_question(monkeypatch):
    monkeypatch.setattr(chat_app, "CONTEXT_CHARS", 15)
    history = [{"role": "user", "content": "a" * 10}, {"role": "assistant", "content": "b" * 10}]
    # only b fits, and a reply can't open the context
    assert chat_app.build_messages(history, "q") == [{"role": "user", "content": "q"}]


def test_thinking_is_not_sent_back():
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "<think>long reasoning</think>\n\nHello!"}]
    assert chat_app.build_messages(history, "q")[1] == {"role": "assistant", "content": "Hello!"}


def test_titles():
    assert make_title("  What is\n an ORB? ") == "What is an ORB?"
    long = make_title("Explain the opening range breakout strategy for BANKNIFTY options with a stop at the middle")
    assert len(long) <= 61 and long.endswith("…") and not long[:-1].endswith(" ")
    assert make_title("   ") == "New chat"


# ---------------------------------------------------------------- daily limits and plans
ADMIN_HEADERS = {**ALICE, "X-Requested-With": "AITradeSoup"}


def test_the_daily_limit_refuses_the_question_after_the_last(client, store, model_calls):
    first = ask(client, "one", BOB).get_json()
    usage = first["usage"]
    assert (usage["used"], usage["limit"], usage["week_used"], usage["week_limit"], usage["plan"]) == (1, 2, 1, 3, "Free")
    assert ask(client, "two", BOB).status_code == 200
    over = ask(client, "three", BOB)
    assert over.status_code == 429
    body = over.get_json()
    assert body["limit_reached"] is True and "all 2 of today's questions on the Free plan" in body["error"]
    assert len(model_calls) == 2  # the third never reached the model
    # someone else still has their own two
    assert ask(client, "mine", ALICE).status_code == 200


def test_a_failed_answer_does_not_use_up_a_question(client, store, monkeypatch):
    def broken(messages, model=None):
        raise RuntimeError("Ollama is not running")
    monkeypatch.setattr(chat_app, "chat_with_messages", broken)
    for _ in range(3):
        assert ask(client, "hello", BOB).status_code == 500
    assert sum(store.counts.values()) == 0


def test_super_admins_have_no_limit(client, store, model_calls, no_super_admins):
    no_super_admins.add(2)
    for _ in range(4):
        assert ask(client, "q", BOB).status_code == 200
    usage = client.get("/api/chat/usage", headers=BOB).get_json()
    assert usage["unlimited"] is True and usage["today"]["limit"] is None and usage["today"]["questions"] == 4


def test_no_sign_in_has_no_limit_and_no_usage_page(client, store, model_calls):
    for _ in range(4):
        assert ask(client, "q").status_code == 200
    assert client.get("/api/chat/usage").status_code == 404
    assert client.get("/api/chat/plans").status_code == 404


def test_usage_page(client, store, model_calls):
    ask(client, "first", BOB)
    usage = client.get("/api/chat/usage", headers=BOB).get_json()
    assert usage["plan"]["code"] == "free" and usage["unlimited"] is False
    assert usage["today"] == {"day": usage["days"][-1]["day"], "questions": 1, "limit": 2,
                              "resets_at": usage["today"]["resets_at"]}
    assert len(usage["days"]) == 30 and sum(d["questions"] for d in usage["days"]) == 1
    assert usage["saved"] == {"chats": 1, "messages": 2} and usage["rate_per_minute"] == 10


def test_asking_for_a_bigger_plan_and_an_admin_approving_it(client, store, model_calls, no_super_admins):
    assert client.post("/api/chat/plan-requests", json={"plan": "free"}, headers=BOB).status_code == 400
    made = client.post("/api/chat/plan-requests", json={"plan": "plus", "note": "  for   reviews "}, headers=BOB)
    assert made.status_code == 201 and made.get_json()["note"] == "for reviews"
    plans = client.get("/api/chat/plans", headers=BOB).get_json()
    assert plans["current"] == "free" and plans["request"]["status"] == "pending" and plans["request"]["plan"] == "plus"

    # not a super admin: the admin endpoints are closed
    assert client.get("/api/chat/admin/overview", headers=ALICE).status_code == 403
    no_super_admins.add(1)
    overview = client.get("/api/chat/admin/overview", headers=ALICE).get_json()
    request_id = overview["requests"][0]["id"]
    # changes need the X-Requested-With header
    assert client.post(f"/api/chat/admin/plan-requests/{request_id}/decision", json={"approve": True},
                       headers=ALICE).status_code == 403
    decided = client.post(f"/api/chat/admin/plan-requests/{request_id}/decision", json={"approve": True},
                          headers=ADMIN_HEADERS)
    assert decided.get_json()["status"] == "approved"
    assert client.get("/api/chat/plans", headers=BOB).get_json()["current"] == "plus"
    # Plus: 5 a day
    for _ in range(5):
        assert ask(client, "q", BOB).status_code == 200
    assert ask(client, "q", BOB).get_json()["error"].startswith("You've asked all 5 of today's")


def test_cancel_a_request_and_admin_sets_a_plan(client, store, model_calls, no_super_admins):
    client.post("/api/chat/plan-requests", json={"plan": "pro"}, headers=BOB)
    assert client.delete("/api/chat/plan-requests/current", headers=BOB).status_code == 200
    assert client.delete("/api/chat/plan-requests/current", headers=BOB).status_code == 404
    no_super_admins.add(1)
    assert client.put("/api/chat/admin/users/2/plan", json={"plan": "nope"}, headers=ADMIN_HEADERS).status_code == 400
    assert client.put("/api/chat/admin/users/2/plan", json={"plan": "pro"}, headers=ADMIN_HEADERS).status_code == 200
    for _ in range(8):  # Pro: no daily limit
        assert ask(client, "q", BOB).status_code == 200


def test_the_weekly_limit_counts_the_whole_week(client, store, model_calls):
    day = chat_app.today()
    monday = chat_app.week_start(day)
    # Free: 3 a week. Two asked earlier this week (or, on a Monday, nothing earlier: then today's limit decides)
    if day != monday:
        store.counts[(2, monday)] = 2
        assert ask(client, "one more", BOB).status_code == 200
        over = ask(client, "too many", BOB)
        assert over.status_code == 429
        assert "all 3 of this week's questions" in over.get_json()["error"]
        assert over.get_json()["usage"]["week_used"] == 3
    # last week's questions don't count
    store.counts.clear()
    store.counts[(2, monday - timedelta(days=1))] = 50
    assert ask(client, "new week", BOB).status_code == 200


def test_usage_shows_the_week_and_warns_at_a_fast_pace(client, store, model_calls, monkeypatch):
    monkeypatch.setattr(chat_app, "today", lambda: date(2026, 11, 18))  # a Wednesday
    store.plan_rows[0].update(daily_questions=40, weekly_questions=100)
    # 30 questions this morning since 09:00 IST (03:30 UTC), checked at 12:00 IST: 10 an hour, 10 left -> runs out ~13:00
    store.counts[(2, date(2026, 11, 18))] = 30
    store.first[(2, date(2026, 11, 18))] = datetime(2026, 11, 18, 3, 30)
    monkeypatch.setattr(chat_app, "datetime", _FrozenDatetime)
    usage = client.get("/api/chat/usage", headers=BOB).get_json()
    assert usage["week"] == {"start": "2026-11-16", "questions": 30, "limit": 100,
                             "resets_at": "2026-11-23T00:00:00+05:30"}
    assert usage["pace"]["window"] == "today"
    assert usage["pace"]["runs_out_at"].startswith("2026-11-18T07:30")  # 13:00 IST
    # a slow day: no warning
    store.counts[(2, date(2026, 11, 18))] = 4
    assert client.get("/api/chat/usage", headers=BOB).get_json()["pace"] is None


class _FrozenDatetime(datetime):
    """datetime with now() fixed at 2026-11-18 12:00 IST."""
    @classmethod
    def now(cls, tz=None):
        moment = datetime(2026, 11, 18, 6, 30, tzinfo=timezone.utc)
        return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)

