"""Apply pack (Anthony, 2026-11-22): fit check + cover letter + draft
answers for one saved job, generated from the client's own profile.
Preparation only — nothing is ever submitted."""
from fastapi.testclient import TestClient

from backend import apply_pack, llm
from backend.main import app

client = TestClient(app)

JOB = {"id": "job1", "title": "Python Developer", "company": "Acme",
       "location": "Remote", "source": "adzuna", "url": "https://example.com/job1",
       "snippet": "Build FastAPI services with Python, Docker and React dashboards."}


def _profile_with_job():
    p = client.post("/api/profiles", json={"name": "Anthony Dickerson"}).json()
    # Give the client a resume so skills come from the document, then a
    # saved job (the way a search would leave one).
    client.post(f"/api/profiles/{p['id']}/documents",
                files={"file": ("resume.txt",
                                b"Anthony Dickerson\nPython, FastAPI, React developer.\n"
                                b"Certifications: IBM AI Engineering Professional Certificate\n"
                                b"Email: deoism@gmail.com")})
    from backend import profiles as profiles_mod
    store = profiles_mod._load()
    store[p["id"]]["saved_jobs"].append(dict(JOB))
    store[p["id"]]["client"]["cover_letter_highlights"] = "Built three AI products end to end"
    store[p["id"]]["client"]["current_role"] = "Freelance AI Consultant"
    profiles_mod._save(store)
    return p


def test_fit_check_matches_posting_skills_against_resume():
    p = _profile_with_job()
    got = client.get(f"/api/profiles/{p['id']}").json()
    fit = apply_pack.fit_for(got["client"], JOB)
    assert "python" in fit["matched"] and "fastapi" in fit["matched"]
    assert "docker" in fit["missing"]  # named by the posting, not the resume
    assert fit["coverage"] is not None and 0 < fit["coverage"] < 1


def test_pack_template_path_builds_letter_and_answers():
    p = _profile_with_job()
    r = client.post(f"/api/profiles/{p['id']}/saved-jobs/job1/apply-pack")
    assert r.status_code == 200
    pack = r.json()["apply_pack"]
    # No LLM keys in the test env: the honest template wrote the letter.
    assert pack["provider"] == "template"
    assert "Python Developer" in pack["cover_letter"]
    assert "Acme" in pack["cover_letter"]
    assert "Anthony Dickerson" in pack["cover_letter"]
    assert "Built three AI products end to end" in pack["cover_letter"]
    questions = [a["question"] for a in pack["answers"]]
    assert "Why are you interested in this role?" in questions
    assert "What makes you a strong fit for this position?" in questions
    assert "submit it yourself" in pack["note"]
    # Stored on the job: a fresh GET serves the same pack.
    got = client.get(f"/api/profiles/{p['id']}/saved-jobs/job1/apply-pack")
    assert got.json()["apply_pack"]["cover_letter"] == pack["cover_letter"]


def test_pack_uses_llm_when_a_rung_answers(monkeypatch):
    monkeypatch.setattr(llm, "generate",
                        lambda prompt: {"text": "Dear Acme,\n\nLM-written letter.",
                                        "provider": "gemini", "errors": {}})
    p = _profile_with_job()
    r = client.post(f"/api/profiles/{p['id']}/saved-jobs/job1/apply-pack")
    pack = r.json()["apply_pack"]
    assert pack["provider"] == "gemini"
    assert pack["cover_letter"].startswith("Dear Acme,")
    # Fit and answers stay fact-based even when the LM writes the letter.
    assert pack["fit"]["matched"]


def test_pack_errors_are_honest():
    p = _profile_with_job()
    assert client.post(f"/api/profiles/{p['id']}/saved-jobs/nope/apply-pack").status_code == 400
    assert client.post("/api/profiles/nope/saved-jobs/job1/apply-pack").status_code == 404
    got = client.get(f"/api/profiles/{p['id']}/saved-jobs/job1/apply-pack")
    assert got.json()["apply_pack"] is None  # not generated yet


def test_llm_chain_reports_no_provider_without_keys(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    st = llm.status()
    assert st["provider"] is None and st["fallback"] == "template"
    out = llm.generate("hello")
    assert out["text"] is None and out["provider"] is None
    assert "gemini" in out["errors"] and "groq" in out["errors"]
