"""Edit profile contract (2026-11-22): the PATCH endpoint the Edit
profile form relies on — the client's own facts (contact, roles,
preferences) update and persist; a patch that tries to add a second
person to the profile is rejected."""
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_patch_updates_client_facts_and_persists():
    p = client.post("/api/profiles", json={"name": "Test Client"}).json()
    r = client.patch(f"/api/profiles/{p['id']}", json={
        "name": "Anthony Dickerson",
        "client": {"phone": "718-914-0313", "email": "deoism@gmail.com",
                   "target_roles": ["Python Developer", "AI Engineer"],
                   "cover_letter_tone": "direct"}})
    assert r.status_code == 200, r.text
    got = client.get(f"/api/profiles/{p['id']}").json()
    c = got["client"]
    assert c["name"] == "Anthony Dickerson"
    assert c["phone"] == "718-914-0313"
    assert c["target_roles"] == ["Python Developer", "AI Engineer"]
    assert c["cover_letter_tone"] == "direct"
    assert got["header"]["client_name"] == "Anthony Dickerson"


def test_patch_rejects_a_second_person():
    p = client.post("/api/profiles", json={"name": "Solo"}).json()
    r = client.patch(f"/api/profiles/{p['id']}",
                     json={"clients": [{"name": "Second"}]})
    assert r.status_code == 400
    r2 = client.patch(f"/api/profiles/{p['id']}",
                      json={"client": [{"name": "Second"}]})
    assert r2.status_code == 400


def test_patch_unknown_profile_is_404():
    assert client.patch("/api/profiles/nope",
                        json={"client": {"phone": "x"}}).status_code == 404
