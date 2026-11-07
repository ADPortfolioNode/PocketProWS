from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert set(r.json()["sources"]) == {"adzuna", "jooble", "usajobs", "remotive",
                                         "remoteok", "arbeitnow", "indeed", "dice", "monster"}
    assert set(r.json()["free_sources"]) == {"adzuna", "jooble", "usajobs", "remotive",
                                              "remoteok", "arbeitnow"}


def test_sources_lists_all_nine():
    r = client.get("/api/sources")
    assert r.status_code == 200
    names = [s["name"] for s in r.json()["sources"]]
    assert len(names) == 9
    free = {s["name"] for s in r.json()["sources"] if s["status"] == "ok"}
    assert free == {"adzuna", "jooble", "usajobs", "remotive", "remoteok", "arbeitnow"}
    gated = {s["name"] for s in r.json()["sources"] if s["status"] == "gated"}
    assert gated == {"indeed", "dice", "monster"}
    no_key = {s["name"] for s in r.json()["sources"] if s["name"] in ("remotive", "remoteok", "arbeitnow")}
    assert all(s["key_configured"] for s in r.json()["sources"] if s["name"] in no_key)
