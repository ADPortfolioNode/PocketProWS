"""Submission readiness + the submission agent (Anthony, 2026-11-24).

The Submit button appears when everything is collected — the pack
is built — and the submission agent reports readiness across the
pipeline. The agent prepares and reports; it never sends.
"""
from fastapi.testclient import TestClient

from backend import agents as agents_mod
from backend import profiles as profiles_mod
from backend import submission as submission_mod
from backend.main import app

client = TestClient(app)


def _profile(jobs, with_doc=True, email="client@example.com"):
    r = client.post("/api/profiles", json={"name": "Submit Client"})
    pid = r.json()["id"]
    profiles = profiles_mod._load()
    p = profiles[pid]
    p["client"]["email"] = email
    for j in jobs:
        p["saved_jobs"].append(j)
    profiles_mod._save(profiles)
    if with_doc:
        r = client.post(f"/api/profiles/{pid}/documents",
                        files={"file": ("resume.txt",
                                        b"Submit Client\npython")})
        assert r.status_code == 200, r.text
    return pid


def _job(jid, snippet="Build things.", pack=False, emailed=None):
    j = {"id": jid, "title": f"Role {jid}", "company": "Acme",
         "location": "Remote", "source": "fakeboard",
         "url": f"https://example.com/{jid}", "snippet": snippet,
         "application_status": "saved", "status_history": [],
         "last_status_at": None, "follow_up_draft": ""}
    if pack:
        j["apply_pack"] = {"job_id": jid, "cover_letter": "Dear Acme,",
                           "answers": [], "provider": "template"}
        if emailed:
            j["apply_pack"]["emailed"] = emailed
    return j


def test_find_application_email_in_snippet():
    job = _job("j1", snippet="Apply by email to jobs@acme.com today.")
    assert submission_mod.find_application_email(job) == "jobs@acme.com"
    assert submission_mod.find_application_email(_job("j2")) == ""
    # Sentence punctuation is not part of the address (live-walk find).
    job = _job("j3", snippet="React role. Apply by email to jobs@acme.com.")
    assert submission_mod.find_application_email(job) == "jobs@acme.com"


def test_readiness_ready_with_found_email():
    pid = _profile([_job("j1", snippet="Email jobs@acme.com to apply",
                         pack=True)])
    r = client.get(f"/api/profiles/{pid}/saved-jobs/j1/submission")
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["ready"] is True
    assert res["application_email"] == "jobs@acme.com"
    assert all(c["ok"] for c in res["checks"])


def test_readiness_needs_pack_and_recipient_can_be_supplied():
    pid = _profile([_job("j1")])
    res = client.get(f"/api/profiles/{pid}/saved-jobs/j1/submission").json()
    assert res["ready"] is False
    by_key = {c["key"]: c for c in res["checks"]}
    assert by_key["pack"]["ok"] is False
    assert by_key["recipient"]["ok"] is False
    assert "enter the employer's application email" in by_key["recipient"]["detail"]


def test_readiness_submitted_job_is_not_ready():
    pid = _profile([_job("j1", pack=True,
                         emailed={"to": "jobs@acme.com",
                                  "at": "2026-11-24T00:00:00Z"})])
    res = client.get(f"/api/profiles/{pid}/saved-jobs/j1/submission").json()
    assert res["ready"] is False
    assert res["submitted"]["to"] == "jobs@acme.com"


def test_submission_404s():
    pid = _profile([])
    assert client.get(f"/api/profiles/{pid}/saved-jobs/nope/submission").status_code == 404
    assert client.get("/api/profiles/nope/saved-jobs/j1/submission").status_code == 404


def test_submission_agent_reports_the_pipeline():
    pid = _profile([
        _job("j1", snippet="Email jobs@acme.com", pack=True),
        _job("j2", pack=True,
             emailed={"to": "x@acme.com", "at": "2026-11-24T00:00:00Z"}),
        _job("j3"),
    ])
    rep = agents_mod.run_submission_agent(pid)
    assert rep["agent"] == "submission"
    assert rep["scan"] == {"total": 3, "submitted": 1, "ready": 1,
                           "needs_recipient": 0, "needs_pack": 1}
    assert "1 ready to submit" in rep["summary"]
    assert "1 already submitted" in rep["summary"]
    # The default run includes the submission agent, and running the
    # agents never sends anything: j1 is still unsubmitted.
    out = agents_mod.run_agents(pid, agents=["submission"])
    assert [r["agent"] for r in out["reports"]] == ["submission"]
    res = client.get(f"/api/profiles/{pid}/saved-jobs/j1/submission").json()
    assert res["submitted"] is None
