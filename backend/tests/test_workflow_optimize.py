"""Workflow optimization regressions (downtime review, 2026-11-23):

- the follow-up agent wrote its drafts onto the throwaway copies
  follow_up_due() returns, so they never persisted on the saved jobs;
- the search agent only ever searched the FIRST target role and
  bypassed the disqualifier the manual search applies;
- profile_status() — a read — recorded a resource run and then
  loaded and re-saved the whole store to undo it.
"""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend import agents as agents_mod
from backend import profiles as profiles_mod
from backend.connectors.base import Job, SearchResult
from backend.main import app

client = TestClient(app)


def _profile(roles=("AI Engineer",), education=None):
    r = client.post("/api/profiles", json={"name": "Optimize Client"})
    assert r.status_code == 200
    pid = r.json()["id"]
    patch = {"target_roles": list(roles), "location": "Remote, USA",
             "remote_preference": "remote"}
    if education:
        patch["education"] = education
    client.patch(f"/api/profiles/{pid}", json={"client": patch})
    return pid


def _job(jid, title="AI Engineer", snippet="Build things."):
    return Job(id=jid, title=title, company="Acme", location="Remote",
               source="fakeboard", url=f"https://example.com/{jid}",
               snippet=snippet)


class _RoleConnector:
    """Returns a role-specific job plus one shared job, records queries."""
    name = "fakeboard"

    def __init__(self):
        self.queries = []

    def search(self, query, location="", limit=10):
        self.queries.append(query)
        return SearchResult(source=self.name, status="ok", jobs=[
            _job(f"job-{query}", title=query), _job("shared", "Shared Role")])


class _StaticConnector:
    name = "fakeboard"

    def __init__(self, jobs):
        self._jobs = jobs

    def search(self, query, location="", limit=10):
        return SearchResult(source=self.name, status="ok", jobs=self._jobs[:limit])


def test_search_agent_searches_every_target_role():
    pid = _profile(roles=("AI Engineer", "React Developer"))
    conn = _RoleConnector()
    rep = agents_mod.run_search_agent(pid, connectors=[conn])
    assert conn.queries == ["AI Engineer", "React Developer"]
    assert rep["queries"] == ["AI Engineer", "React Developer"]
    # Two role jobs + the shared one, deduped across roles.
    assert rep["new_jobs"] == 3
    saved = client.get(f"/api/profiles/{pid}/saved-jobs").json()["saved_jobs"]
    assert len(saved) == 3


def test_search_agent_omits_disqualified_postings():
    pid = _profile(education=["Associate of Science in Information Technology"])
    jobs = [_job("keep1"),
            _job("omit1", snippet="Requirements: bachelor's degree in "
                                  "computer science is required.")]
    rep = agents_mod.run_search_agent(pid, connectors=[_StaticConnector(jobs)])
    assert rep["new_jobs"] == 1
    assert rep["omitted_count"] == 1
    assert rep["omitted"][0]["id"] == "omit1"
    assert rep["omitted"][0]["reasons"]
    saved = client.get(f"/api/profiles/{pid}/saved-jobs").json()["saved_jobs"]
    assert [j["id"] for j in saved] == ["keep1"]


def test_follow_up_draft_persists_on_the_saved_job():
    pid = _profile()
    agents_mod.run_search_agent(pid, connectors=[_StaticConnector([_job("j1")])])
    res = agents_mod.set_application_status(pid, "j1", "applied")
    assert "error" not in res
    profiles = profiles_mod._load()
    job = profiles[pid]["saved_jobs"][0]
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    job["last_status_at"] = old
    job["applied_at"] = old
    profiles_mod._save(profiles)
    rep = agents_mod.run_follow_up_agent(pid, days=7)
    assert len(rep["due"]) == 1
    saved = profiles_mod.get_profile(pid)["saved_jobs"][0]
    assert saved["follow_up_draft"]
    assert "following up" in saved["follow_up_draft"]


def test_profile_status_is_a_pure_read():
    pid = _profile()
    before = profiles_mod._load()
    st1 = agents_mod.profile_status(pid)
    st2 = agents_mod.profile_status(pid)
    after = profiles_mod._load()
    assert before == after  # nothing recorded, nothing saved
    assert st1["resources"]["document_count"] == 0
    assert st1["last_runs"] == []
    assert st2["integrity"]["by_agent"]["resource"]["passed"] in (True, False)
