"""Workflow-integrity checks: each agent verifies the workflow it operates
on, plus the audit fixes (sanitized uploads, empty answers/names, drafts
on read, same-status no-op, status-word routing). All test data is made up
and local-only — nothing here is sent anywhere."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend import agents as agents_mod
from backend import profiles as profiles_mod
from backend import vector_store as vs
from backend.connectors.base import Job, SearchResult
from backend.main import app

client = TestClient(app)


def _profile(name="Integrity Client", roles=("AI Engineer",)):
    r = client.post("/api/profiles", json={"name": name})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    if roles:
        client.patch(f"/api/profiles/{pid}",
                     json={"client": {"target_roles": list(roles),
                                      "location": "Remote, USA",
                                      "remote_preference": "remote"}})
    return pid


class _FakeConnector:
    name = "fakeboard"

    def __init__(self, jobs):
        self._jobs = jobs

    def search(self, query, location="", limit=10):
        return SearchResult(source=self.name, status="ok",
                            jobs=self._jobs[:limit])


def _job(jid, title="AI Engineer", company="Acme"):
    return Job(id=jid, title=title, company=company, location="Remote",
               source="fakeboard", url=f"https://example.com/{jid}",
               snippet="Build things.")


def _corrupt(pid, mutate):
    """Hand-edit the stored profile (simulating corrupted data), then save."""
    profiles = profiles_mod._load()
    mutate(profiles[pid])
    profiles_mod._save(profiles)


def _backdate_status(pid, job_id, days_ago):
    def _mut(p):
        job = next(j for j in p["saved_jobs"] if j["id"] == job_id)
        past = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        job["last_status_at"] = past
        job["applied_at"] = past
    _corrupt(pid, _mut)


# ------------------------------------------------- clean profile passes all
def test_integrity_clean_profile_passes_every_agent():
    pid = _profile()
    agents_mod.run_search_agent(pid, connectors=[_FakeConnector([_job("j1")])])
    client.patch(f"/api/profiles/{pid}/saved-jobs/j1/status", json={"status": "applied"})
    client.post(f"/api/profiles/{pid}/documents",
                files={"file": ("resume.txt", b"Python FastAPI RAG developer, IBM AI Engineering certificate.\n", "text/plain")})
    integ = agents_mod.check_workflow_integrity(pid)
    assert integ["passed"] is True, integ["problems"]
    assert integ["problems"] == []
    assert all(r["passed"] for r in integ["by_agent"].values())
    st = client.get(f"/api/profiles/{pid}/status").json()
    assert st["integrity"]["passed"] is True


def test_integrity_reported_in_concierge_status_answer():
    pid = _profile()
    agents_mod.run_search_agent(pid, connectors=[_FakeConnector([_job("j1")])])
    r = client.post("/api/chat", json={"message": "What's the status?",
                                       "profile_id": pid})
    assert r.status_code == 200
    assert r.json()["mode"] == "status"
    assert "Workflow integrity check: passed." in r.json()["answer"]


# ------------------------------------------------------------ search agent
def test_search_integrity_catches_duplicate_and_malformed_saved_job():
    pid = _profile()
    agents_mod.run_search_agent(pid, connectors=[_FakeConnector([_job("j1")])])

    def _mut(p):
        job = dict(p["saved_jobs"][0])
        p["saved_jobs"].append(dict(job))  # exact duplicate id
        bad = dict(job, id="j2")
        del bad["title"]
        bad["application_status"] = ""
        p["saved_jobs"].append(bad)
    _corrupt(pid, _mut)
    integ = agents_mod.check_search_integrity(profiles_mod.get_profile(pid))
    assert integ["passed"] is False
    assert any("duplicate" in p for p in integ["problems"])
    assert any("missing field" in p and "j2" in p for p in integ["problems"])
    # The search agent's own run records the failure.
    rep = agents_mod.run_search_agent(pid, connectors=[_FakeConnector([])])
    assert rep["integrity"]["passed"] is False


# -------------------------------------------------------- application agent
def test_application_integrity_catches_illegal_history_jump():
    pid = _profile()
    agents_mod.run_search_agent(pid, connectors=[_FakeConnector([_job("j1")])])

    def _mut(p):
        job = p["saved_jobs"][0]
        job["application_status"] = "offer"
        job["status_history"] = [{"status": "offer", "at": "2026-11-08T00:00:00+00:00", "note": ""}]
    _corrupt(pid, _mut)
    integ = agents_mod.check_application_integrity(profiles_mod.get_profile(pid))
    assert integ["passed"] is False
    assert any("illegal history move 'saved' -> 'offer'" in p for p in integ["problems"])
    rep = agents_mod.run_application_agent(pid)
    assert rep["integrity"]["passed"] is False
    assert "Integrity FAILED" in rep["summary"]


def test_application_integrity_catches_move_out_of_terminal_state():
    pid = _profile()
    agents_mod.run_search_agent(pid, connectors=[_FakeConnector([_job("j1")])])
    for nxt in ("applied", "interviewing", "offer", "hired"):
        client.patch(f"/api/profiles/{pid}/saved-jobs/j1/status", json={"status": nxt})

    def _mut(p):
        job = p["saved_jobs"][0]
        job["status_history"].append({"status": "applied", "at": "2026-11-08T01:00:00+00:00", "note": ""})
        job["application_status"] = "applied"
    _corrupt(pid, _mut)
    integ = agents_mod.check_application_integrity(profiles_mod.get_profile(pid))
    assert integ["passed"] is False
    assert any("terminal state 'hired'" in p for p in integ["problems"])


def test_application_integrity_catches_status_history_mismatch():
    pid = _profile()
    agents_mod.run_search_agent(pid, connectors=[_FakeConnector([_job("j1")])])
    client.patch(f"/api/profiles/{pid}/saved-jobs/j1/status", json={"status": "applied"})

    def _mut(p):
        p["saved_jobs"][0]["application_status"] = "interviewing"  # history still ends at applied
    _corrupt(pid, _mut)
    integ = agents_mod.check_application_integrity(profiles_mod.get_profile(pid))
    assert integ["passed"] is False
    assert any("does not match last history entry" in p for p in integ["problems"])


# ---------------------------------------------------------- follow-up agent
def test_follow_up_integrity_catches_job_with_no_status_date():
    pid = _profile()
    agents_mod.run_search_agent(pid, connectors=[_FakeConnector([_job("j1")])])
    client.patch(f"/api/profiles/{pid}/saved-jobs/j1/status", json={"status": "applied"})

    def _mut(p):
        job = p["saved_jobs"][0]
        job["last_status_at"] = None
        job["applied_at"] = None
    _corrupt(pid, _mut)
    integ = agents_mod.check_follow_up_integrity(profiles_mod.get_profile(pid))
    assert integ["passed"] is False
    assert any("no recorded status date" in p for p in integ["problems"])
    # And it is (correctly) not listed as due — it needs a date first.
    assert agents_mod.follow_up_due(profiles_mod.get_profile(pid)) == []


# ----------------------------------------------------------- resource agent
def test_resource_integrity_catches_rag_entry_for_deleted_document():
    pid = _profile()
    client.post(f"/api/profiles/{pid}/documents",
                files={"file": ("resume.txt", b"Python FastAPI RAG developer, IBM AI Engineering certificate.\n", "text/plain")})
    # Simulate a deleted document whose RAG chunks were never removed.
    vs.upsert_profile_chunks(pid, "ghost-doc-1234", "Python developer resume text")
    integ = agents_mod.check_resource_integrity(profiles_mod.get_profile(pid))
    assert integ["passed"] is False
    assert any("deleted/missing document ghost-doc-1234" in p for p in integ["problems"])
    rep = agents_mod.run_resource_agent(pid)
    assert rep["integrity"]["passed"] is False


def test_resource_integrity_passes_after_document_deleted_properly():
    pid = _profile()
    r = client.post(f"/api/profiles/{pid}/documents",
                    files={"file": ("resume.txt", b"Python FastAPI RAG developer, IBM AI Engineering certificate.\n", "text/plain")})
    doc_id = r.json()["document"]["id"]
    assert client.delete(f"/api/profiles/{pid}/documents/{doc_id}").status_code == 200
    integ = agents_mod.check_resource_integrity(profiles_mod.get_profile(pid))
    assert integ["passed"] is True, integ["problems"]


def test_failed_integrity_reaches_concierge_status_answer():
    pid = _profile()
    agents_mod.run_search_agent(pid, connectors=[_FakeConnector([_job("j1")])])

    def _mut(p):
        job = p["saved_jobs"][0]
        job["application_status"] = "offer"
        job["status_history"] = [{"status": "offer", "at": "2026-11-08T00:00:00+00:00", "note": ""}]
    _corrupt(pid, _mut)
    r = client.post("/api/chat", json={"message": "What's the status?",
                                       "profile_id": pid})
    assert r.json()["mode"] == "status"
    assert "Workflow integrity check FAILED" in r.json()["answer"]
    assert "illegal history move" in r.json()["answer"]


# ------------------------------------------------------------- audit fixes
def test_upload_traversal_filename_is_sanitized_not_500():
    pid = _profile()
    r = client.post(f"/api/profiles/{pid}/documents",
                    files={"file": ("../../traversal-evil.txt", b"hello world", "text/plain")})
    assert r.status_code == 200, r.text
    assert r.json()["document"]["filename"] == "traversal-evil.txt"
    assert ".." not in r.json()["document"]["filename"]


def test_upload_unsupported_type_rejected():
    pid = _profile()
    r = client.post(f"/api/profiles/{pid}/documents",
                    files={"file": ("evil.exe", b"MZ\x90\x00binary", "application/octet-stream")})
    assert r.status_code == 400, r.text
    assert "unsupported file type" in r.json()["detail"]
    r = client.post(f"/api/profiles/{pid}/documents",
                    files={"file": ("photo.png", b"\x89PNGbinary", "image/png")})
    assert r.status_code == 400


def test_empty_interview_answer_rejected_without_advancing():
    pid = _profile()
    r = client.post(f"/api/profiles/{pid}/interview/answer", json={"answer": "   "})
    assert r.status_code == 400, r.text
    st = client.get(f"/api/profiles/{pid}/interview").json()
    assert st["step"] == 0
    # A real answer still works afterwards.
    r = client.post(f"/api/profiles/{pid}/interview/answer", json={"answer": "Test Person"})
    assert r.status_code == 200
    assert client.get(f"/api/profiles/{pid}/interview").json()["step"] == 1


def test_follow_up_draft_present_on_read_without_running_agent():
    pid = _profile()
    agents_mod.run_search_agent(pid, connectors=[_FakeConnector([_job("j1")])])
    client.patch(f"/api/profiles/{pid}/saved-jobs/j1/status", json={"status": "applied"})
    _backdate_status(pid, "j1", days_ago=10)
    r = client.get(f"/api/profiles/{pid}/follow-ups", params={"days": 7})
    assert r.status_code == 200
    assert len(r.json()["due"]) == 1
    assert r.json()["due"][0]["draft"] != ""
    assert "Acme" in r.json()["due"][0]["draft"]


def test_same_status_reset_does_not_duplicate_history():
    pid = _profile()
    agents_mod.run_search_agent(pid, connectors=[_FakeConnector([_job("j1")])])
    client.patch(f"/api/profiles/{pid}/saved-jobs/j1/status", json={"status": "applied"})
    client.patch(f"/api/profiles/{pid}/saved-jobs/j1/status", json={"status": "applied"})
    job = client.get(f"/api/profiles/{pid}/saved-jobs").json()["saved_jobs"][0]
    assert len(job["status_history"]) == 1
    assert job["application_status"] == "applied"


def test_concierge_update_my_resume_is_not_a_status_question():
    pid = _profile()
    r = client.post("/api/chat", json={"message": "update my resume",
                                       "profile_id": pid})
    assert r.status_code == 200
    assert r.json()["mode"] != "status"
