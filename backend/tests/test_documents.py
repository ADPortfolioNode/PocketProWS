"""Documents: Add / Edit / Delete + digest into the client's resource."""
from fastapi.testclient import TestClient

from backend.main import app
from backend.vector_store import search_profile_text

client = TestClient(app)

RESUME = b"""Anthony Dickerson
AI Engineer | Full-Stack AI Developer
Email: deoism@gmail.com | Phone: 718-914-0313
Skills: Python, FastAPI, React, RAG, LangChain, ChromaDB, Docker
Certifications: IBM AI Engineering Professional Certificate
Education: A.A.S. Information Technology, TCI College, 2012
Work: Freelance AI & Web Developer, Jan 2024 - present. Built PocketProSBA.
"""


def _mk():
    return client.post("/api/profiles", json={"name": "Anthony Dickerson"}).json()


def _upload(pid, content=RESUME, filename="resume.txt"):
    return client.post(f"/api/profiles/{pid}/documents",
                       files={"file": (filename, content)})


def test_add_document_digests_facts():
    p = _mk()
    r = _upload(p["id"])
    assert r.status_code == 200
    doc = r.json()["document"]
    assert doc["filename"] == "resume.txt"
    ext = r.json()["extracted"]
    assert "python" in ext["skills"]
    assert "rag" in ext["skills"]
    assert ext["email"] == "deoism@gmail.com"
    assert any("IBM" in c for c in ext["certifications"])
    assert any("Information Technology" in e for e in ext["education"])
    # digested facts landed in the profile's client record
    got = client.get(f"/api/profiles/{p['id']}").json()
    assert "Python" in got["client"]["skills"] or "python" in got["client"]["skills"]
    assert got["client"]["email"] == "deoism@gmail.com"
    assert any(s["step"] == "documents" and s["done"] for s in got["workflow"]["steps"])


def test_document_is_in_client_rag_and_scoped():
    p = _mk()
    other = client.post("/api/profiles", json={"name": "Someone Else"}).json()
    _upload(p["id"])
    hits = search_profile_text(p["id"], "PocketProSBA")
    assert len(hits) >= 1
    assert all(h["profile_id"] == p["id"] for h in hits)
    # profile B's retrieval never sees profile A's document
    assert search_profile_text(other["id"], "PocketProSBA") == []


def test_edit_document_title():
    p = _mk()
    doc = _upload(p["id"]).json()["document"]
    r = client.patch(f"/api/profiles/{p['id']}/documents/{doc['id']}",
                     json={"title": "Anthony — Resume 2026"})
    assert r.status_code == 200
    assert r.json()["document"]["title"] == "Anthony — Resume 2026"


def test_replace_document_redigests():
    p = _mk()
    doc = _upload(p["id"]).json()["document"]
    r = client.post(f"/api/profiles/{p['id']}/documents/{doc['id']}/replace",
                    files={"file": ("resume2.txt", b"Skills: AWS, Terraform\nCertifications: AWS Certified Solutions Architect")})
    assert r.status_code == 200
    assert "aws" in r.json()["document"]["digest"]["skills"]
    got = client.get(f"/api/profiles/{p['id']}").json()
    assert "aws" in got["client"]["skills"]


def test_delete_document_removes_from_rag():
    p = _mk()
    doc = _upload(p["id"]).json()["document"]
    assert len(search_profile_text(p["id"], "PocketProSBA")) >= 1
    r = client.delete(f"/api/profiles/{p['id']}/documents/{doc['id']}")
    assert r.status_code == 200
    assert search_profile_text(p["id"], "PocketProSBA") == []
    assert client.get(f"/api/profiles/{p['id']}/documents").json()["documents"] == []


def test_documents_permissions_note_on_first_load():
    p = _mk()
    r = client.get(f"/api/profiles/{p['id']}/documents")
    assert "Add / Edit / Delete" in r.json()["permissions"]


OFFICE_RESUME = b"""Maria Lopez
Office Administrator
Email: maria.lopez@example.com
Skills: Microsoft Excel, QuickBooks, data entry, customer service, bookkeeping, payroll, scheduling
Experience: Front desk receptionist and accounts payable clerk for 6 years.
"""


def test_nontech_office_skills_extracted():
    p = client.post("/api/profiles", json={"name": "Maria Lopez"}).json()
    r = _upload(p["id"], OFFICE_RESUME, "maria.txt")
    assert r.status_code == 200
    skills = r.json()["extracted"]["skills"]
    for s in ("excel", "quickbooks", "data entry", "customer service",
              "bookkeeping", "payroll", "scheduling", "accounts payable",
              "receptionist"):
        assert s in skills, s
    got = client.get(f"/api/profiles/{p['id']}").json()
    assert "quickbooks" in got["client"]["skills"]


def test_trades_and_healthcare_skills_extracted():
    p = client.post("/api/profiles", json={"name": "James Carter"}).json()
    text = (b"James Carter\nWarehouse associate and certified nursing aide.\n"
            b"Skills: forklift, warehouse, shipping, patient care, cpr, vital signs\n")
    r = _upload(p["id"], text, "james.txt")
    assert r.status_code == 200
    skills = r.json()["extracted"]["skills"]
    for s in ("forklift", "warehouse", "shipping", "patient care", "cpr",
              "vital signs"):
        assert s in skills, s


def test_skill_matching_respects_word_boundaries():
    # "excellent" must not extract "excel"; "digital" must not extract
    # "git"; "storage" must not extract "rag".
    p = client.post("/api/profiles", json={"name": "Prose Person"}).json()
    text = (b"A digital native with excellent communication skills and a "
            b"history of storage room organization.\n")
    r = _upload(p["id"], text, "prose.txt")
    assert r.status_code == 200
    skills = r.json()["extracted"]["skills"]
    assert "excel" not in skills
    assert "git" not in skills
    assert "rag" not in skills


def test_replace_document_nontech_redigests():
    p = client.post("/api/profiles", json={"name": "Maria Lopez"}).json()
    doc = _upload(p["id"], OFFICE_RESUME, "maria.txt").json()["document"]
    r = client.post(f"/api/profiles/{p['id']}/documents/{doc['id']}/replace",
                    files={"file": ("maria2.txt",
                                    b"Skills: QuickBooks, invoicing, office management")})
    assert r.status_code == 200
    skills = r.json()["document"]["digest"]["skills"]
    assert "quickbooks" in skills
    assert "invoicing" in skills
    assert "office management" in skills
