from fastapi.testclient import TestClient

from backend.main import app
from backend.vector_store import upsert_jobs

client = TestClient(app)


def test_chat_empty_question():
    r = client.post("/api/chat", json={"message": ""})
    assert r.status_code == 200
    assert r.json()["mode"] == "fallback"


def test_chat_no_saved_jobs_is_honest():
    r = client.post("/api/chat", json={"message": "remote Python jobs"})
    assert r.status_code == 200
    assert "don't have any saved jobs" in r.json()["answer"]
    assert r.json()["jobs"] == []


def test_chat_finds_saved_job():
    upsert_jobs([{"id": "t1", "title": "AI Engineer", "company": "Acme",
                  "location": "Remote", "source": "adzuna",
                  "url": "https://example.com", "snippet": "RAG pipelines"}])
    r = client.post("/api/chat", json={"message": "AI Engineer RAG"})
    assert r.status_code == 200
    assert len(r.json()["jobs"]) >= 1
    assert "AI Engineer" in r.json()["answer"]


def _profile():
    return client.post("/api/profiles", json={"name": "Chat Client"}).json()


def test_chat_history_is_recorded_and_served():
    p = _profile()
    r1 = client.post("/api/chat", json={"message": "remote Python jobs",
                                        "profile_id": p["id"]})
    assert r1.status_code == 200
    hist = r1.json()["history"]
    assert [m["role"] for m in hist] == ["user", "assistant"]
    assert hist[0]["text"] == "remote Python jobs"
    r2 = client.post("/api/chat", json={"message": "How are we doing?",
                                        "profile_id": p["id"]})
    assert len(r2.json()["history"]) == 4  # status turns are recorded too
    got = client.get(f"/api/profiles/{p['id']}/chat")
    assert got.status_code == 200
    assert len(got.json()["messages"]) == 4
    # Another profile's conversation is separate.
    other = _profile()
    assert client.get(f"/api/profiles/{other['id']}/chat").json()["messages"] == []


def test_chat_history_clear_and_cap():
    from backend.chat import answer
    from backend.profiles import CHAT_CAP
    p = _profile()
    for i in range(CHAT_CAP // 2 + 5):
        answer(f"question {i}", profile_id=p["id"])
    got = client.get(f"/api/profiles/{p['id']}/chat").json()["messages"]
    assert len(got) == CHAT_CAP
    assert got[0]["text"] != "question 0"  # the oldest were trimmed
    r = client.delete(f"/api/profiles/{p['id']}/chat")
    assert r.status_code == 200
    assert client.get(f"/api/profiles/{p['id']}/chat").json()["messages"] == []
    assert client.get("/api/profiles/nope/chat").status_code == 404


def test_interview_turns_are_not_recorded_in_chat():
    p = _profile()
    client.post("/api/chat", json={"message": "Anthony Dickerson",
                                   "profile_id": p["id"], "mode": "interview"})
    assert client.get(f"/api/profiles/{p['id']}/chat").json()["messages"] == []


def test_followup_query_uses_previous_question():
    from backend.chat import _effective_query
    hist = [{"role": "user", "text": "remote Python jobs"},
            {"role": "assistant", "text": "…"}]
    assert _effective_query("and in Texas?", hist) == "remote Python jobs and in Texas?"
    assert _effective_query("what about Austin?", hist).startswith("remote Python jobs")
    # A full new question stands on its own; no history, no merge.
    assert _effective_query("data analyst roles in Chicago", hist) == "data analyst roles in Chicago"
    assert _effective_query("and remote?", []) == "and remote?"
