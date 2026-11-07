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
