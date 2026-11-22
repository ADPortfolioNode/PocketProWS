"""Concierge verbosity (Anthony, 2026-11-22): helpful and verbose, for
transparency — the assistant helps the user understand the workflow.
Guide intent, narrated status, 'How I answered' lines, and a why for
every interview question."""
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def _profile():
    return client.post("/api/profiles", json={"name": "Anthony Dickerson"}).json()


def _chat(pid, q, mode=""):
    return client.post("/api/chat", json={"message": q, "profile_id": pid, "mode": mode}).json()


def test_guide_walks_the_workflow_with_position():
    p = _profile()
    r = _chat(p["id"], "Explain my workflow")
    assert r["mode"] == "guide"
    a = r["answer"]
    for step in ("Documents", "Interview", "Preferences", "Job search", "Applications", "Follow-up"):
        assert step in a
    assert "you are here" in a  # the client's position is marked
    assert "disqualify" in a  # the filter is explained, not hidden
    assert "nothing is ever sent automatically" in a


def test_guide_without_profile_still_teaches():
    r = client.post("/api/chat", json={"message": "how does this work"}).json()
    assert r["mode"] == "guide"
    assert "Create a client profile to start" in r["answer"]


def test_status_answer_is_a_narrated_briefing():
    p = _profile()
    r = _chat(p["id"], "How are we doing?")
    assert r["mode"] == "status"
    a = r["answer"]
    assert "What that step is:" in a
    assert "Next best step:" in a
    assert "Add the resume" in a  # no documents yet -> the honest next step
    assert "explain my workflow" in a


def test_qa_answer_shows_how_it_answered():
    p = _profile()
    client.post(f"/api/profiles/{p['id']}/documents",
                files={"file": ("resume.txt",
                                b"Anthony Dickerson\nPython developer with FastAPI and React.\nEmail: deoism@gmail.com")})
    r = _chat(p["id"], "Python developer")
    assert "How I answered:" in r["answer"]
    assert "nothing added" in r["answer"]


def test_interview_questions_carry_a_why():
    p = _profile()
    st = client.get(f"/api/profiles/{p['id']}/interview").json()
    assert st["why"]  # first question explains itself
    r = _chat(p["id"], "Anthony Dickerson", mode="interview")
    assert r["interview"]["why"]  # next question's why rides along
    assert "Why I ask:" in r["answer"]


def test_every_interview_question_has_a_why():
    from backend.profiles import INTERVIEW_QUESTIONS
    assert all(q.get("why") for q in INTERVIEW_QUESTIONS)
    assert len(INTERVIEW_QUESTIONS) == 11
