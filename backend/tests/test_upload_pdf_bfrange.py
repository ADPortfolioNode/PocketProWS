"""Upload crash regression (Anthony, 2026-11-23): a real resume PDF
whose ToUnicode CMap uses the ARRAY form of bfrange
(<lo> <hi> [<d1> <d2> ...]) crashed _parse_tounicode with
'too many values to unpack' — the pattern captures three groups, the
loop unpacked two — so the upload died as an unhandled 500 and the
app could only say 'unknown error'. The array branch had never run
against a fixture before. These tests build that exact encoding,
plus the fault isolation around CMap parsing and the endpoint's
duty to return the real reason."""
import zlib

from fastapi.testclient import TestClient

from backend import profiles
from backend.main import app
from backend.tests.test_certificates import _pdf, _stream

client = TestClient(app)

LINE = "Upload works 2026"


def array_bfrange_pdf() -> bytes:
    """Every glyph decoded through ONE array-form bfrange entry."""
    chars = sorted(set(LINE))
    cid_of = {c: i + 1 for i, c in enumerate(chars)}
    dsts = " ".join(f"<{ord(c):04X}>" for c in chars)
    cmap = ("/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
            "/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
            "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
            f"1 beginbfrange\n<{min(cid_of.values()):04X}> <{max(cid_of.values()):04X}> [{dsts}]\nendbfrange\n"
            "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend")
    ops = ["1 0 0 -1 100 300 Tm"]
    for ch in LINE:
        ops.append(f"<{cid_of[ch]:04X}> Tj")
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


def test_array_bfrange_pdf_extracts_instead_of_crashing():
    text = profiles.extract_text(array_bfrange_pdf(), "resume.pdf")
    assert "Upload works 2026" in text


def test_array_bfrange_pdf_uploads_through_the_endpoint():
    p = client.post("/api/profiles", json={"name": "Upload Tester"}).json()
    r = client.post(f"/api/profiles/{p['id']}/documents",
                    files={"file": ("resume.pdf", array_bfrange_pdf())})
    assert r.status_code == 200, r.text
    assert r.json()["text_chars"] > 0


def test_one_bad_cmap_cannot_fail_extraction(monkeypatch):
    def boom(cmap):
        raise ValueError("malformed cmap")
    monkeypatch.setattr(profiles, "_parse_tounicode", boom)
    # Must degrade to whatever the fallback yields — never raise.
    text = profiles.extract_text(array_bfrange_pdf(), "resume.pdf")
    assert isinstance(text, str)


def test_upload_endpoint_reports_the_real_reason(monkeypatch):
    def boom(profile_id, filename, data):
        raise RuntimeError("kaboom in the extractor")
    monkeypatch.setattr(profiles, "add_document", boom)
    p = client.post("/api/profiles", json={"name": "Reason Tester"}).json()
    r = client.post(f"/api/profiles/{p['id']}/documents",
                    files={"file": ("resume.pdf", b"%PDF-1.4 fake")})
    assert r.status_code == 500
    assert "kaboom in the extractor" in r.json()["detail"]
