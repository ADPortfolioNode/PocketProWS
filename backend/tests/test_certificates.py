"""Certificates must be identified (Anthony, 2026-11-21): real
certificate PDFs (Coursera-style) show text as 2-byte CIDs under Type0
fonts — meaningless without the font's ToUnicode CMap — and position
every glyph with its own Td. The old extractor scraped image bytes as
garbage and found nothing, so every certificate failed the integrity
check with "digest missing". These tests build that exact encoding."""
import zlib

from fastapi.testclient import TestClient

from backend.main import app
from backend.profiles import digest_text, extract_text

client = TestClient(app)


def _pdf(objs) -> bytes:
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n"
            % (len(objs) + 1)) + str(xref).encode() + b"\n%%EOF"
    return out


def _stream(content: bytes) -> bytes:
    comp = zlib.compress(content)
    return (b"<< /Length " + str(len(comp)).encode()
            + b" /Filter /FlateDecode >>\nstream\n" + comp + b"\nendstream")


CERT_LINES = ["Feb 1, 2024",
              "Anthony Dickerson",
              "Python for Data Science, AI & Development",
              "an online non-credit course authorized by IBM and offered through Coursera",
              "has successfully completed"]


def coursera_style_pdf() -> bytes:
    """Text as per-glyph CIDs decoded only through a ToUnicode CMap
    (bfchar for letters/punctuation, one bfrange for the digits), each
    glyph advanced by its own 'x 0 Td' — the real Coursera layout."""
    chars = sorted({c for line in CERT_LINES for c in line if not c.isdigit()})
    cid_of = {c: 0x30 + i for i, c in enumerate(chars)}
    bfchar = "\n".join(f"<{cid_of[c]:04X}> <{ord(c):04X}>" for c in chars)
    cmap = ("/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
            "/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
            "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
            f"{len(chars)} beginbfchar\n{bfchar}\nendbfchar\n"
            "1 beginbfrange\n<0100> <0109> <0030>\nendbfrange\n"
            "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend")

    def cid(ch):
        return 0x100 + int(ch) if ch.isdigit() else cid_of[ch]

    ops = []
    for line in CERT_LINES:
        ops.append("1 0 0 -1 100 300 Tm")
        for ch in line:
            ops.append(f"<{cid(ch):04X}> Tj")
            ops.append("6 0 Td")
    content = ("BT /F1 11 Tf " + " ".join(ops) + " ET").encode()
    return _pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Font /Subtype /Type0 /BaseFont /TestFont "
        b"/Encoding /Identity-H /ToUnicode 5 0 R >>",
        _stream(cmap.encode()),
        _stream(content),
    ])


def test_coursera_style_certificate_is_identified():
    text = extract_text(coursera_style_pdf(), "cert.pdf")
    # The course title survives as one readable line (glyphs rejoined).
    assert "Python for Data Science, AI & Development" in text
    assert "has successfully completed" in text
    d = digest_text(text)
    assert "python" in d["skills"]
    # The credential is the course title, even though the line itself
    # never says the word "certificate".
    assert "Python for Data Science, AI & Development" in d["certifications"]


def test_uploaded_certificate_passes_integrity():
    p = client.post("/api/profiles", json={"name": "Anthony Dickerson"}).json()
    r = client.post(f"/api/profiles/{p['id']}/documents",
                    files={"file": ("PYTHON-AI-DEVELOPMENT-XGU3XQ4XCZ7V.pdf",
                                    coursera_style_pdf())})
    assert r.status_code == 200
    assert "python" in r.json()["extracted"]["skills"]
    assert r.json()["extracted"]["certifications"]
    st = client.get(f"/api/profiles/{p['id']}/status").json()
    assert st["integrity"]["passed"] is True, st["integrity"]["problems"]


def test_redigest_repairs_a_document_in_place():
    p = client.post("/api/profiles", json={"name": "Anthony Dickerson"}).json()
    doc = client.post(f"/api/profiles/{p['id']}/documents",
                      files={"file": ("cert.pdf", coursera_style_pdf())}).json()["document"]
    r = client.post(f"/api/profiles/{p['id']}/documents/{doc['id']}/redigest")
    assert r.status_code == 200
    assert "Python for Data Science" in r.json()["extracted"]["certifications"][0]
    got = client.get(f"/api/profiles/{p['id']}").json()
    assert "python" in got["client"]["skills"]


def test_prefix_upload_self_repairs_on_load():
    """A certificate uploaded under the OLD extractor has an empty
    stored digest. With the fix in place it must heal by itself on the
    next load — no button, no re-upload — and the integrity check the
    user actually sees must pass."""
    from backend import profiles as profiles_mod
    p = client.post("/api/profiles", json={"name": "Anthony Dickerson"}).json()
    up = client.post(f"/api/profiles/{p['id']}/documents",
                     files={"file": ("cert.pdf", coursera_style_pdf())}).json()
    doc_id = up["document"]["id"]
    # Simulate the pre-fix stored state: empty digest, garbage char count.
    store = profiles_mod._load()
    doc = next(d for d in store[p["id"]]["documents"] if d["id"] == doc_id)
    doc["digest"] = {"skills": [], "certifications": [], "education": [],
                     "email": "", "phone": "", "summary": ""}
    doc["text_chars"] = 55525
    profiles_mod._save(store)
    st = client.get(f"/api/profiles/{p['id']}/status").json()
    assert st["integrity"]["passed"] is True, st["integrity"]["problems"]
    got = client.get(f"/api/profiles/{p['id']}").json()
    healed = next(d for d in got["documents"] if d["id"] == doc_id)
    assert "Python for Data Science" in healed["digest"]["certifications"][0]
    assert healed["text_chars"] < 1000  # real text now, not 55K of garbage


def test_one_poison_document_cannot_break_profile_loading(monkeypatch):
    """The self-repair runs inside profile loading, so a document whose
    re-digest throws (a malformed cert from another issuer) must never
    take the profiles endpoints down with it — it is skipped, logged,
    and left with its stored digest."""
    from backend import profiles as profiles_mod
    p = client.post("/api/profiles", json={"name": "Anthony Dickerson"}).json()
    up = client.post(f"/api/profiles/{p['id']}/documents",
                     files={"file": ("cert.pdf", coursera_style_pdf())}).json()
    doc_id = up["document"]["id"]
    store = profiles_mod._load()
    doc = next(d for d in store[p["id"]]["documents"] if d["id"] == doc_id)
    doc["digest"] = {"skills": [], "certifications": [], "education": [],
                     "email": "", "phone": "", "summary": ""}
    profiles_mod._save(store)

    def boom(data, filename):
        raise ValueError("Odd-length string")

    monkeypatch.setattr(profiles_mod, "extract_text", boom)
    r = client.get("/api/profiles")
    assert r.status_code == 200
    r2 = client.post("/api/profiles", json={"name": "Second Client"})
    assert r2.status_code == 200
    got = client.get(f"/api/profiles/{p['id']}")
    assert got.status_code == 200
    still = next(d for d in got.json()["documents"] if d["id"] == doc_id)
    assert still["digest"]["skills"] == []  # untouched, honestly empty


def test_odd_length_hex_string_does_not_raise():
    # "Hello" with an odd digit count — legal PDF, must not raise.
    content = b"BT /F1 12 Tf <48656C6C6F7> Tj ET"
    pdf = _pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        _stream(content),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ])
    text = extract_text(pdf, "odd.pdf")
    assert "Hello" in text


def test_utf16be_hex_string_pdf_extracts():
    def hex16(s):
        return ("<FEFF" + s.encode("utf-16-be").hex().upper() + ">").encode()
    lines = ["Certificate of Completion",
             "Skills: Python, Machine Learning, React"]
    content = b"BT /F1 12 Tf 72 720 Td " + b" ".join(
        hex16(l) + b" Tj T*" for l in lines) + b" ET"
    pdf = _pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        _stream(content),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ])
    text = extract_text(pdf, "cert2.pdf")
    assert "Certificate of Completion" in text
    d = digest_text(text)
    assert "python" in d["skills"] and "machine learning" in d["skills"]


def test_tj_array_pdf_extracts_with_word_gaps():
    content = (b"BT /F1 12 Tf [(Certificate of Completion) -250 "
               b"(Skills: Python, React, SQL)] TJ ET")
    pdf = _pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        _stream(content),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ])
    text = extract_text(pdf, "cert3.pdf")
    assert "Certificate of Completion Skills: Python, React, SQL" in text
    assert "python" in digest_text(text)["skills"]
