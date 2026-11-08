"""Workflow agents: search, application tracking, follow-up, resources,
concierge status reporting, and per-profile isolation."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend import agents as agents_mod
from backend import profiles as profiles_mod
from backend import vector_store as vs
from backend.connectors.base import Job, SearchResult
from backend.main import app

client = TestClient(app)


def _profile(name="Test Client", roles=("AI Engineer",)):
    r = client.post("/api/profiles", json={"name": name})
    assert r.status_code == 200
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


# ------------------------------------------------------------ search agent
def test_search_agent_saves_and_dedupes():
    pid = _profile()
    jobs = [_job("j1"), _job("j2", "Python Developer", "Beta")]
    rep = agents_mod.run_search_agent(pid, connectors=[_FakeConnector(jobs)])
    assert rep["new_jobs"] == 2
    assert rep["total_found"] == 2
    rep2 = agents_mod.run_search_agent(pid, connectors=[_FakeConnector(jobs)])
    assert rep2["new_jobs"] == 0  # second run adds nothing — deduped
    saved = client.get(f"/api/profiles/{pid}/saved-jobs").json()["saved_jobs"]
    assert len(saved) == 2
    assert all(j["application_status"] == "saved" for j in saved)


def test_search_agent_needs_target_roles():
    pid = _profile(roles=())
    rep = agents_mod.run_search_agent(pid, connectors=[_FakeConnector([_job("j1")])])
    assert rep["new_jobs"] == 0
    assert "No target roles" in rep["summary"]
    assert client.get(f"/api/profiles/{pid}/saved-jobs").json()["saved_jobs"] == []


def test_search_agent_isolated_per_profile():
    a = _profile("Client A")
    b = _profile("Client B")
    agents_mod.run_search_agent(a, connectors=[_FakeConnector([_job("j1")])])
    assert len(client.get(f"/api/profiles/{a}/saved-jobs").json()["saved_jobs"]) == 1
    assert client.get(f"/api/profiles/{b}/saved-jobs").json()["saved_jobs"] == []


# ------------------------------------------------------- application agent
def test_application_status_full_chain():
    pid = _profile()
    agents_mod.run_search_agent(pid, connectors=[_FakeConnector([_job("j1")])])
    for nxt in ("applied", "interviewing", "offer", "hired"):
        r = client.patch(f"/api/profiles/{pid}/saved-jobs/j1/status",
                         json={"status": nxt, "note": f"moved to {nxt}"})
        assert r.status_code == 200, r.text
        assert r.json()["job"]["application_status"] == nxt
    job = r.json()["job"]
    assert len(job["status_history"]) == 4
    assert job["applied_at"]
    pipe = client.get(f"/api/profiles/{pid}/applications").json()["pipeline"]
    assert pipe["counts"]["hired"] == 1


def test_application_status_invalid_transition_rejected():
    pid = _profile()
    agents_mod.run_search_agent(pid, connectors=[_FakeConnector([_job("j1")])])
    # saved -> offer skips applied/interviewing: not allowed.
    r = client.patch(f"/api/profiles/{pid}/saved-jobs/j1/status",
                     json={"status": "offer"})
    assert r.status_code == 400
    assert "cannot move" in r.json()["detail"]
    # hired is terminal.
    client.patch(f"/api/profiles/{pid}/saved-jobs/j1/status", json={"status": "applied"})
    client.patch(f"/api/profiles/{pid}/saved-jobs/j1/status", json={"status": "interviewing"})
    client.patch(f"/api/profiles/{pid}/saved-jobs/j1/status", json={"status": "offer"})
    client.patch(f"/api/profiles/{pid}/saved-jobs/j1/status", json={"status": "hired"})
    r = client.patch(f"/api/profiles/{pid}/saved-jobs/j1/status",
                     json={"status": "applied"})
    assert r.status_code == 400
    # unknown job / unknown status
    assert client.patch(f"/api/profiles/{pid}/saved-jobs/nope/status",
                        json={"status": "applied"}).status_code == 400
    assert client.patch(f"/api/profiles/{pid}/saved-jobs/j1/status",
                        json={"status": "banana"}).status_code == 400


# ---------------------------------------------------------- follow-up agent
def _backdate_status(pid, job_id, days_ago):
    profiles = profiles_mod._load()
    job = next(j for j in profiles[pid]["saved_jobs"] if j["id"] == job_id)
    past = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    job["last_status_at"] = past
    job["applied_at"] = past
    profiles_mod._save(profiles)


def test_follow_up_agent_lists_stale_applications_and_drafts():
    pid = _profile()
    agents_mod.run_search_agent(pid, connectors=[_FakeConnector([_job("j1"), _job("j2")])])
    client.patch(f"/api/profiles/{pid}/saved-jobs/j1/status", json={"status": "applied"})
    client.patch(f"/api/profiles/{pid}/saved-jobs/j2/status", json={"status": "applied"})
    _backdate_status(pid, "j1", days_ago=10)  # stale
    _backdate_status(pid, "j2", days_ago=2)   # fresh
    rep = agents_mod.run_follow_up_agent(pid, days=7)
    assert len(rep["due"]) == 1
    assert rep["due"][0]["job_id"] == "j1"
    assert "Acme" in rep["due"][0]["draft"] and "AI Engineer" in rep["due"][0]["draft"]
    r = client.get(f"/api/profiles/{pid}/follow-ups", params={"days": 7})
    assert len(r.json()["due"]) == 1


def test_follow_up_agent_nothing_due():
    pid = _profile()
    rep = agents_mod.run_follow_up_agent(pid, days=7)
    assert rep["due"] == []
    assert "No follow-ups due" in rep["summary"]


# ----------------------------------------------------------- resource agent
def test_resource_agent_reports_healthy_then_stale():
    pid = _profile()
    r = client.post(f"/api/profiles/{pid}/documents",
                    files={"file": ("resume.txt", b"Python FastAPI RAG developer, IBM AI Engineering certificate.\n", "text/plain")})
    assert r.status_code == 200
    doc_id = r.json()["document"]["id"]
    rep = agents_mod.run_resource_agent(pid)
    assert rep["document_count"] == 1
    assert rep["healthy_count"] == 1
    assert rep["documents"][0]["status"] == "ok"
    assert rep["documents"][0]["rag_chunks"] >= 1
    assert "python" in rep["documents"][0]["skills"]
    # Simulate a stale RAG entry: chunks deleted, document still on file.
    vs.delete_profile_doc_chunks(pid, doc_id)
    rep2 = agents_mod.run_resource_agent(pid)
    assert rep2["documents"][0]["status"] == "needs attention"
    assert any("missing from RAG" in p for p in rep2["documents"][0]["problems"])


def test_resource_agent_no_documents():
    pid = _profile()
    rep = agents_mod.run_resource_agent(pid)
    assert rep["document_count"] == 0
    assert "No documents on file" in rep["summary"]


# ------------------------------------------------------------- status + chat
def test_status_endpoint_reports_real_numbers():
    pid = _profile()
    agents_mod.run_search_agent(pid, connectors=[_FakeConnector([_job("j1"), _job("j2")])])
    client.patch(f"/api/profiles/{pid}/saved-jobs/j1/status", json={"status": "applied"})
    st = client.get(f"/api/profiles/{pid}/status").json()
    assert st["client_name"] == "Test Client"
    assert st["pipeline"]["counts"]["saved"] == 1
    assert st["pipeline"]["counts"]["applied"] == 1
    assert st["pipeline"]["total"] == 2
    assert st["resources"]["document_count"] == 0
    assert any(r["agent"] == "search" for r in st["last_runs"])
    assert st["current_step"] == "interview"  # interview not done yet — first undone step


def test_agents_run_endpoint_records_runs():
    pid = _profile(roles=())
    r = client.post(f"/api/profiles/{pid}/agents/run",
                    json={"agents": ["follow_up", "resource"]})
    assert r.status_code == 200
    assert {x["agent"] for x in r.json()["reports"]} == {"follow_up", "resource"}
    st = client.get(f"/api/profiles/{pid}/status").json()
    assert any(x["agent"] == "follow_up" for x in st["last_runs"])


def test_concierge_answers_status_from_agent_data():
    pid = _profile()
    agents_mod.run_search_agent(pid, connectors=[_FakeConnector([_job("j1")])])
    client.patch(f"/api/profiles/{pid}/saved-jobs/j1/status",
                 json={"status": "applied"})
    r = client.post("/api/chat", json={"message": "What's the status?",
                                       "profile_id": pid})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "status"
    assert "Test Client" in body["answer"]
    assert "1 applied" in body["answer"]
    assert "No follow-ups due" in body["answer"]


def test_agents_never_touch_another_profile():
    a = _profile("Client A")
    b = _profile("Client B")
    agents_mod.run_search_agent(a, connectors=[_FakeConnector([_job("j1")])])
    client.patch(f"/api/profiles/{a}/saved-jobs/j1/status", json={"status": "applied"})
    agents_mod.run_follow_up_agent(a, days=7)
    agents_mod.run_resource_agent(a)
    st_b = client.get(f"/api/profiles/{b}/status").json()
    assert st_b["pipeline"]["total"] == 0
    assert st_b["last_runs"] == []
    assert st_b["resources"]["document_count"] == 0
