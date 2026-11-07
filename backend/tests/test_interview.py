"""Interview: one question at a time, answers saved, identity first."""
from fastapi.testclient import TestClient

from backend.main import app
from backend.profiles import INTERVIEW_QUESTIONS

client = TestClient(app)


def _mk():
    return client.post("/api/profiles", json={"name": ""}).json()


def test_first_question_is_who():
    p = _mk()
    r = client.get(f"/api/profiles/{p['id']}/interview")
    assert r.status_code == 200
    assert r.json()["complete"] is False
    assert "who is our client" in r.json()["next_question"].lower()
    assert r.json()["question_key"] == "name"


def test_answer_saves_and_advances_one_question():
    p = _mk()
    r = client.post(f"/api/profiles/{p['id']}/interview/answer",
                    json={"answer": "Anthony Dickerson"})
    assert r.status_code == 200
    assert "Anthony Dickerson" in r.json()["saved"]
    assert r.json()["step"] == 1
    assert "current or most recent role" in r.json()["next_question"].lower()
    # identity is now defined on the profile's client
    got = client.get(f"/api/profiles/{p['id']}").json()
    assert got["client"]["name"] == "Anthony Dickerson"


def test_full_interview_completes_and_summarises():
    p = _mk()
    answers = ["Anthony Dickerson", "AI Engineer", "AI Engineer, Web Developer",
               "Python, FastAPI, React, RAG", "Freelance AI Developer 2024–present",
               "IBM AI Engineering", "A.A.S. Information Technology, TCI",
               "Queens, NY — remote", "Either", "$100,000",
               "Highlight my PocketPro RAG apps, confident and direct"]
    assert len(answers) == len(INTERVIEW_QUESTIONS)
    last = None
    for a in answers:
        last = client.post(f"/api/profiles/{p['id']}/interview/answer",
                           json={"answer": a}).json()
    assert last["complete"] is True
    assert "Anthony Dickerson" in last["summary"]
    assert "AI Engineer" in last["summary"]
    got = client.get(f"/api/profiles/{p['id']}").json()
    assert got["client"]["target_roles"] == ["AI Engineer", "Web Developer"]
    assert "Python" in got["client"]["skills"]
    assert got["client"]["remote_preference"] == "remote"
    assert got["client"]["employment_type"] == "Either"
    assert got["workflow"]["steps"][0]["done"] is True  # interview step done


def test_interview_answers_are_retrievable_per_client():
    from backend.vector_store import search_profile_text
    p = _mk()
    client.post(f"/api/profiles/{p['id']}/interview/answer",
                json={"answer": "Anthony Dickerson"})
    client.post(f"/api/profiles/{p['id']}/interview/answer",
                json={"answer": "AI Engineer at PocketPro"})
    hits = search_profile_text(p["id"], "AI Engineer")
    assert any("PocketPro" in h["text"] for h in hits)


def test_chat_interview_mode_asks_first_question():
    p = _mk()
    r = client.post("/api/chat", json={"message": "", "profile_id": p["id"], "mode": "interview"})
    assert r.status_code == 200
    assert "who is our client" in r.json()["answer"].lower()
