"""Clicking a document views it (Anthony, 2026-11-22): the view
endpoint returns the text the app extracted from the stored file —
read-only, nothing re-digested or re-indexed — and the file endpoint
serves the original bytes inline so a PDF opens in the browser."""
from fastapi.testclient import TestClient

from backend.main import app
from backend import profiles as profiles_mod

client = TestClient(app)

RESUME = (b"Anthony Dickerson\nQueens, NY - anthony@example.com - 718-555-0100\n"
          b"Skills: Python, React, FastAPI\n"
          b"Experience: built recruiter tools and RAG assistants.\n")


def _profile_with_doc():
    p = client.post("/api/profiles", json={"name": "View Test Client"}).json()
    pid = p["id"]
    up = client.post(f"/api/profiles/{pid}/documents",
                     files={"file": ("resume.txt", RESUME, "text/plain")})
    assert up.status_code == 200, up.text
    return pid, up.json()["document"]["id"]


def test_view_returns_extracted_text_and_digest():
    pid, doc_id = _profile_with_doc()
    r = client.get(f"/api/profiles/{pid}/documents/{doc_id}/view")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "Python" in body["text"] and "Anthony Dickerson" in body["text"]
    assert body["truncated"] is False
    assert body["text_chars"] == len(body["text"])
    assert "python" in body["document"]["digest"]["skills"]


def test_view_is_read_only():
    pid, doc_id = _profile_with_doc()
    before = profiles_mod.get_profile(pid)["documents"][0]["text_chars"]
    client.get(f"/api/profiles/{pid}/documents/{doc_id}/view")
    after = profiles_mod.get_profile(pid)["documents"][0]["text_chars"]
    assert before == after


def test_file_serves_original_bytes_inline():
    pid, doc_id = _profile_with_doc()
    r = client.get(f"/api/profiles/{pid}/documents/{doc_id}/file")
    assert r.status_code == 200, r.text
    assert r.content == RESUME
    assert r.headers["content-type"].startswith("text/plain")
    assert "inline" in r.headers.get("content-disposition", "")


def test_view_unknown_document_is_404():
    pid, _ = _profile_with_doc()
    r = client.get(f"/api/profiles/{pid}/documents/nope123/view")
    assert r.status_code == 404
    r = client.get(f"/api/profiles/{pid}/documents/nope123/file")
    assert r.status_code == 404
    r = client.get("/api/profiles/nope123/documents/x/view")
    assert r.status_code == 404


def test_view_missing_stored_file_is_honest_error():
    pid, doc_id = _profile_with_doc()
    for f in profiles_mod._docs_dir(pid).glob(f"{doc_id}-*"):
        f.unlink()
    r = client.get(f"/api/profiles/{pid}/documents/{doc_id}/view")
    assert r.status_code == 400
    assert "missing" in r.json()["detail"]
