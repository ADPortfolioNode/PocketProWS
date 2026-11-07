from fastapi.testclient import TestClient

import backend.connectors.adzuna as adzuna_mod
from backend.main import app

client = TestClient(app)


def _fake_adzuna(*args, **kwargs):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": [{
                "id": 1, "title": "AI Engineer",
                "company": {"display_name": "Acme"},
                "location": {"display_name": "Remote"},
                "redirect_url": "https://example.com/j/1",
                "description": "Build RAG pipelines.",
                "salary_min": 120000,
            }]}
    return Resp()


def test_search_without_keys_reports_unavailable_not_500(monkeypatch):
    r = client.get("/api/jobs/search", params={"q": "AI Engineer", "source": "adzuna"})
    assert r.status_code == 200
    res = r.json()["results"][0]
    assert res["source"] == "adzuna"
    assert res["status"] == "unavailable"
    assert "ADZUNA_APP" in res["message"]


def test_search_adzuna_mocked(monkeypatch):
    monkeypatch.setattr(adzuna_mod, "ADZUNA_APP_ID", "x")
    monkeypatch.setattr(adzuna_mod, "ADZUNA_APP_KEY", "y")
    monkeypatch.setattr(adzuna_mod, "http_get", _fake_adzuna)
    r = client.get("/api/jobs/search", params={"q": "AI Engineer", "source": "adzuna"})
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["results"][0]["jobs"][0]["title"] == "AI Engineer"


def test_gated_boards_report_gated():
    r = client.get("/api/jobs/search", params={"q": "x", "source": "indeed"})
    assert r.json()["results"][0]["status"] == "unavailable"
    assert "retired" in r.json()["results"][0]["message"]
    r = client.get("/api/jobs/search", params={"q": "x", "source": "monster"})
    assert r.json()["results"][0]["status"] == "unavailable"
