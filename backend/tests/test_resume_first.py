"""Resume first (Anthony, 2026-11-21): the workflow asks for the resume
before the interview, and the client's skills are ALWAYS the skills used
or referenced in the resume — never a typed-in list."""
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

RESUME = b"""Anthony Dickerson
AI Engineer
Email: deoism@gmail.com | Phone: 718-914-0313
Skills: Python, FastAPI, React, RAG, LangChain, ChromaDB, Docker
"""


def _mk():
    return client.post("/api/profiles", json={"name": ""}).json()


def _upload(pid, content=RESUME, filename="resume.txt"):
    return client.post(f"/api/profiles/{pid}/documents",
                       files={"file": (filename, content)})


def _answer(pid, answer):
    return client.post(f"/api/profiles/{pid}/interview/answer",
                       json={"answer": answer}).json()


def test_workflow_starts_with_documents():
    p = _mk()
    got = client.get(f"/api/profiles/{p['id']}").json()
    steps = [s["step"] for s in got["workflow"]["steps"]]
    assert steps == ["documents", "interview", "preferences",
                     "job_search", "applications", "follow_up"]
    # A fresh profile's current step is the resume, not the interview.
    assert got["workflow"]["current_step"] == "documents"


def test_upload_moves_current_step_to_interview():
    p = _mk()
    _upload(p["id"])
    got = client.get(f"/api/profiles/{p['id']}").json()
    assert got["workflow"]["current_step"] == "interview"


def test_skills_come_from_the_resume():
    p = _mk()
    r = _upload(p["id"])
    extracted = r.json()["extracted"]["skills"]
    got = client.get(f"/api/profiles/{p['id']}").json()
    assert got["client"]["skills"] == sorted(extracted)
    assert "python" in got["client"]["skills"]


def test_skills_question_names_the_resume_skills():
    p = _mk()
    _upload(p["id"])
    _answer(p["id"], "Anthony Dickerson")
    _answer(p["id"], "AI Engineer")
    _answer(p["id"], "AI Engineer, Web Developer")
    st = client.get(f"/api/profiles/{p['id']}/interview").json()
    assert st["question_key"] == "skills"
    assert "resume" in st["next_question"].lower()
    assert "python" in st["next_question"].lower()


def test_typed_skills_are_never_adopted():
    p = _mk()
    _upload(p["id"])
    before = client.get(f"/api/profiles/{p['id']}").json()["client"]["skills"]
    _answer(p["id"], "Anthony Dickerson")
    _answer(p["id"], "AI Engineer")
    _answer(p["id"], "AI Engineer")
    res = _answer(p["id"], "Perl, COBOL, Fortran")
    assert "Confirmed" in res["saved"]
    got = client.get(f"/api/profiles/{p['id']}").json()
    assert got["client"]["skills"] == before
    assert "perl" not in got["client"]["skills"]


def test_skills_question_without_resume_points_to_documents():
    p = _mk()
    _answer(p["id"], "Anthony Dickerson")
    _answer(p["id"], "AI Engineer")
    _answer(p["id"], "AI Engineer")
    st = client.get(f"/api/profiles/{p['id']}/interview").json()
    assert st["question_key"] == "skills"
    assert "documents" in st["next_question"].lower()


def test_replace_resume_recomputes_skills():
    p = _mk()
    doc = _upload(p["id"]).json()["document"]
    assert "python" in client.get(f"/api/profiles/{p['id']}").json()["client"]["skills"]
    client.post(f"/api/profiles/{p['id']}/documents/{doc['id']}/replace",
                files={"file": ("resume2.txt", b"Skills: AWS, Terraform")})
    skills = client.get(f"/api/profiles/{p['id']}").json()["client"]["skills"]
    assert "aws" in skills
    # The old resume's skills leave when its file is replaced.
    assert "python" not in skills


def test_delete_resume_clears_skills():
    p = _mk()
    doc = _upload(p["id"]).json()["document"]
    assert client.get(f"/api/profiles/{p['id']}").json()["client"]["skills"]
    client.delete(f"/api/profiles/{p['id']}/documents/{doc['id']}")
    got = client.get(f"/api/profiles/{p['id']}").json()
    assert got["client"]["skills"] == []
