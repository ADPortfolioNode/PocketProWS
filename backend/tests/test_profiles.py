"""Profiles: one person (one client) per profile, header from the active
profile, strict per-profile separation."""
from fastapi.testclient import TestClient

from backend.main import app
from backend.vector_store import search_profile_text

client = TestClient(app)

RESUME_A = b"""Anthony Dickerson
AI Engineer | Full-Stack AI Developer
Email: deoism@gmail.com
Skills: Python, FastAPI, React, RAG
Work: Freelance AI & Web Developer, Jan 2024 - present. Built PocketProSBA.
"""


def _mk(name="Anthony Dickerson"):
    r = client.post("/api/profiles", json={"name": name})
    assert r.status_code == 200
    return r.json()


def test_create_list_get_profile():
    p = _mk()
    assert p["client"]["name"] == "Anthony Dickerson"
    assert p["client"]["target_roles"] == []
    # one person per profile: the client is a single object, never a list
    assert isinstance(p["client"], dict)
    assert "clients" not in p and "persons" not in p
    r = client.get("/api/profiles")
    assert any(x["id"] == p["id"] for x in r.json()["profiles"])
    r = client.get(f"/api/profiles/{p['id']}")
    assert r.status_code == 200
    assert r.json()["workflow"]["current_step"] == "interview"
    assert r.json()["interview"]["complete"] is False
    assert r.json()["header"]["client_name"] == "Anthony Dickerson"


def test_update_profile_client_fields():
    p = _mk()
    r = client.patch(f"/api/profiles/{p['id']}",
                     json={"client": {"location": "Queens, NY", "remote_preference": "remote"}})
    assert r.status_code == 200
    assert r.json()["client"]["location"] == "Queens, NY"
    # header reflects the edit at once (fresh read, never stale)
    h = client.get("/api/profiles/active").json()
    assert h["header"]["location"] == "Queens, NY"


def test_second_person_in_one_profile_is_rejected():
    p = _mk()
    for bad in ({"clients": [{"name": "Someone Else"}]},
                {"persons": [{"name": "Someone Else"}]},
                {"second_client": {"name": "Someone Else"}},
                {"client": [{"name": "Someone Else"}]}):
        r = client.patch(f"/api/profiles/{p['id']}", json=bad)
        assert r.status_code == 400, bad
    got = client.get(f"/api/profiles/{p['id']}").json()
    assert isinstance(got["client"], dict)
    assert got["client"]["name"] == "Anthony Dickerson"


def test_delete_profile_removes_it():
    p = _mk("To Delete")
    r = client.delete(f"/api/profiles/{p['id']}")
    assert r.status_code == 200
    assert client.get(f"/api/profiles/{p['id']}").status_code == 404


def test_unknown_profile_404():
    assert client.get("/api/profiles/nope").status_code == 404
    assert client.delete("/api/profiles/nope").status_code == 404


def test_workflow_advances_with_data():
    p = _mk()
    w = client.get(f"/api/profiles/{p['id']}/workflow").json()
    assert w["current_step"] == "interview"
    client.patch(f"/api/profiles/{p['id']}",
                 json={"client": {"target_roles": ["AI Engineer"], "location": "Remote"}})
    w = client.get(f"/api/profiles/{p['id']}/workflow").json()
    assert any(s["step"] == "preferences" and s["done"] for s in w["steps"])
    w = client.post(f"/api/profiles/{p['id']}/workflow", json={"step": "applications"}).json()
    assert any(s["step"] == "applications" and s["done"] for s in w["steps"])


# ------------------------------------------------------- active profile / header
def test_first_profile_becomes_active_and_header_shows_it():
    p = _mk()
    r = client.get("/api/profiles/active")
    assert r.status_code == 200
    assert r.json()["active_profile_id"] == p["id"]
    assert r.json()["header"]["client_name"] == "Anthony Dickerson"
    assert r.json()["header"]["current_step"] == "interview"


def test_switching_active_profile_updates_header():
    a = _mk("Anthony Dickerson")
    b = _mk("Someone Else")
    client.patch(f"/api/profiles/{b['id']}",
                 json={"client": {"target_roles": ["Web Developer"], "location": "Remote"}})
    r = client.post("/api/profiles/active", json={"profile_id": b["id"]})
    assert r.status_code == 200
    h = r.json()["header"]
    assert h["profile_id"] == b["id"]
    assert h["client_name"] == "Someone Else"
    assert h["target_roles"] == ["Web Developer"]
    assert h["location"] == "Remote"
    # and switching back restores A's header
    r = client.post("/api/profiles/active", json={"profile_id": a["id"]})
    assert r.json()["header"]["client_name"] == "Anthony Dickerson"
    assert r.json()["header"]["target_roles"] == []


def test_active_unknown_profile_404():
    assert client.post("/api/profiles/active", json={"profile_id": "nope"}).status_code == 404


def test_deleting_active_profile_clears_active():
    p = _mk()
    assert client.get("/api/profiles/active").json()["active_profile_id"] == p["id"]
    client.delete(f"/api/profiles/{p['id']}")
    assert client.get("/api/profiles/active").json()["active_profile_id"] is None


def test_header_updates_after_interview_answer():
    p = _mk()
    client.post(f"/api/profiles/{p['id']}/interview/answer", json={"answer": "Anthony Dickerson"})
    client.post(f"/api/profiles/{p['id']}/interview/answer", json={"answer": "AI Engineer"})
    client.post(f"/api/profiles/{p['id']}/interview/answer",
                json={"answer": "AI Engineer, Web Developer"})
    h = client.get("/api/profiles/active").json()["header"]
    assert h["target_roles"] == ["AI Engineer", "Web Developer"]
    assert h["client_name"] == "Anthony Dickerson"
    assert h["current_step"] == "interview"  # interview still in progress


# ------------------------------------------------------- per-profile isolation
def test_profiles_are_strictly_separate():
    a = _mk("Anthony Dickerson")
    b = _mk("Someone Else")
    # A: document + interview answers through work history (Q5)
    client.post(f"/api/profiles/{a['id']}/documents",
                files={"file": ("resume.txt", RESUME_A)})
    for ans in ("Anthony Dickerson", "AI Engineer",
                "AI Engineer, Web Developer", "Python, FastAPI, React",
                "Freelance AI Developer at PocketPro, 2024-present"):
        client.post(f"/api/profiles/{a['id']}/interview/answer", json={"answer": ans})
    # B sees none of A's work history, documents, or RAG hits
    assert client.get(f"/api/profiles/{b['id']}/documents").json()["documents"] == []
    hits_b = search_profile_text(b["id"], "PocketProSBA")
    assert hits_b == []
    hits_a = search_profile_text(a["id"], "PocketProSBA")
    assert len(hits_a) >= 1
    assert all(h["profile_id"] == a["id"] for h in hits_a)
    # B's chat never retrieves A's notes
    r = client.post("/api/chat", json={"message": "PocketProSBA", "profile_id": b["id"]})
    assert "PocketProSBA" not in r.json().get("answer", "") or "don't have" in r.json()["answer"]
    # A is untouched by B's existence: work history, documents intact
    got_a = client.get(f"/api/profiles/{a['id']}").json()
    assert got_a["client"]["name"] == "Anthony Dickerson"
    assert len(got_a["documents"]) == 1
    assert any("PocketPro" in w for w in got_a["client"]["work_history"])
    got_b = client.get(f"/api/profiles/{b['id']}").json()
    assert got_b["client"]["work_history"] == []
    assert got_b["documents"] == []
