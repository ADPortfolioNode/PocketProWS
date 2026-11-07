"""New free sources: Remotive, RemoteOK, Arbeitnow — mocked HTTP."""
from fastapi.testclient import TestClient

import backend.connectors.arbeitnow as an_mod
import backend.connectors.remoteok as rok_mod
import backend.connectors.remotive as rem_mod
from backend.main import app

client = TestClient(app)


class Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_remotive_mocked(monkeypatch):
    def fake(*a, **k):
        return Resp({"jobs": [{"id": 1, "title": "AI Engineer", "company_name": "Acme",
                               "candidate_required_location": "USA", "url": "https://example.com/j/1",
                               "salary": "$100k", "description": "<p>Build RAG.</p>", "tags": ["python"]}]})
    monkeypatch.setattr(rem_mod, "http_get", fake)
    r = client.get("/api/jobs/search", params={"q": "AI Engineer", "source": "remotive"})
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["results"][0]["jobs"][0]["company"] == "Acme"


def test_remoteok_mocked_skips_legal_notice(monkeypatch):
    def fake(*a, **k):
        return Resp([{"legal": "terms"}, {"id": "9", "position": "Python Developer",
                                          "company": "Beta", "tags": ["python"],
                                          "description": "<p>Remote Python.</p>",
                                          "apply_url": "https://example.com/apply",
                                          "salary_min": 80000, "salary_max": 120000}])
    monkeypatch.setattr(rok_mod, "http_get", fake)
    r = client.get("/api/jobs/search", params={"q": "Python", "source": "remoteok"})
    assert r.json()["total"] == 1
    assert r.json()["results"][0]["jobs"][0]["title"] == "Python Developer"


def test_arbeitnow_mocked(monkeypatch):
    def fake(*a, **k):
        return Resp({"data": [{"slug": "ai-engineer-1", "title": "AI Engineer",
                               "company_name": "Gamma", "location": "Remote",
                               "url": "https://example.com/j/2", "remote": True,
                               "description": "<p>AI role.</p>", "tags": ["AI"]}]})
    monkeypatch.setattr(an_mod, "http_get", fake)
    r = client.get("/api/jobs/search", params={"q": "AI Engineer", "source": "arbeitnow"})
    assert r.json()["total"] == 1


def test_search_scoped_to_profile_saves_jobs():
    # Use remotive mocked so a real search returns a job for the profile.
    def fake(*a, **k):
        return Resp({"jobs": [{"id": 5, "title": "AI Engineer", "company_name": "Acme",
                               "candidate_required_location": "USA", "url": "https://example.com/j/5",
                               "salary": "", "description": "AI Engineer RAG", "tags": ["ai"]}]})
    import backend.connectors.remotive as _rm
    _orig = _rm.http_get
    _rm.http_get = fake
    try:
        p = client.post("/api/profiles", json={"name": "Anthony"}).json()
        r = client.get("/api/jobs/search", params={"q": "AI Engineer", "source": "remotive",
                                                   "profile_id": p["id"]})
        assert r.status_code == 200
        saved = client.get(f"/api/profiles/{p['id']}/saved-jobs").json()
        assert len(saved["saved_jobs"]) == 1
        assert saved["saved_jobs"][0]["title"] == "AI Engineer"
    finally:
        _rm.http_get = _orig


def test_gated_boards_still_gated():
    for name in ("indeed", "dice", "monster"):
        r = client.get("/api/jobs/search", params={"q": "x", "source": name})
        assert r.json()["results"][0]["status"] == "unavailable"
