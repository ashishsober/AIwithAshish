"""chat-api tests: no MySQL and no model needed (an in-memory store and a fake model stand in).

Run from the repo root:  python -m pytest -q tests
"""
import uuid

import pytest

import app as chat_app
from src.chat_store import StoreUnavailable, make_title

ALICE = {"X-Auth-User-Id": "1"}
BOB = {"X-Auth-User-Id": "2"}


class FakeStore:
    """Same behaviour as ChatStore, in memory."""

    def __init__(self):
        self.conversations = {}
        self.down = False

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
