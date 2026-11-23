"""LM letter check (Anthony, 2026-11-22): the apply pack's cover
letter is verified against the client's record for stupidity
(invented facts, wrong names/contacts, placeholders, contradictions)
and regression (the letter falling short of the record — matched
skills, certifications or requested highlights omitted, the role
understated). Issues get one correction pass and a re-check."""
from fastapi.testclient import TestClient

from backend import llm
from backend.main import app
from backend.tests.test_apply_pack import _profile_with_job

client = TestClient(app)

BAD_LETTER = ("Dear Acme hiring team,\n\nI am applying for the Python Developer "
              "position. I hold a Kubernetes certification and my phone is "
              "718-914-0413.\n\nSincerely,\nAnthony Dickerson")
FIXED_LETTER = ("Dear Acme hiring team,\n\nI am applying for the Python Developer "
                "position at Acme. My resume covers Python and FastAPI, and I "
                "hold the IBM AI Engineering Professional Certificate. I built "
                "three AI products end to end.\n\nSincerely,\nAnthony Dickerson\n"
                "deoism@gmail.com")


def _fake(letter_text, verdicts, revised=FIXED_LETTER):
    """Dispatch on the prompt's job: write / check / revise."""
    state = {"v": 0}

    def gen(prompt):
        if prompt.startswith("Write a professional cover letter"):
            if letter_text is None:
                return {"text": None, "provider": None,
                        "errors": {"gemini": "no key"}}
            return {"text": letter_text, "provider": "gemini", "errors": {}}
        if prompt.startswith("Check this cover letter"):
            v = verdicts[min(state["v"], len(verdicts) - 1)]
            state["v"] += 1
            return {"text": v, "provider": "gemini", "errors": {}}
        if prompt.startswith("Revise this cover letter"):
            return {"text": revised, "provider": "gemini", "errors": {}}
        return {"text": None, "provider": None, "errors": {}}
    return gen


def _pack(monkeypatch, fake):
    monkeypatch.setattr(llm, "generate", fake)
    p = _profile_with_job()
    r = client.post(f"/api/profiles/{p['id']}/saved-jobs/job1/apply-pack")
    assert r.status_code == 200, r.text
    return r.json()["apply_pack"]


def test_clean_letter_passes_first_check(monkeypatch):
    pack = _pack(monkeypatch, _fake(FIXED_LETTER, ["VERDICT: PASS"]))
    check = pack["letter_check"]
    assert check["checked"] is True and check["verdict"] == "pass"
    assert check["revised"] is False and check["issues"] == []
    assert pack["cover_letter"] == FIXED_LETTER


def test_stupidity_is_caught_corrected_and_rechecked(monkeypatch):
    verdicts = [
        "VERDICT: ISSUES\n"
        "- [stupidity] The letter claims a Kubernetes certification that is not on the record.\n"
        "- [stupidity] The phone number 718-914-0413 does not match the record.",
        "VERDICT: PASS",
    ]
    pack = _pack(monkeypatch, _fake(BAD_LETTER, verdicts))
    check = pack["letter_check"]
    assert pack["cover_letter"] == FIXED_LETTER  # the corrected version ships
    assert check["verdict"] == "pass" and check["revised"] is True
    assert any("Kubernetes" in i for i in check["first_issues"])


def test_regression_issues_that_survive_correction_are_reported(monkeypatch):
    verdicts = [
        "VERDICT: ISSUES\n"
        "- [regression] The letter omits the matched skill FastAPI.",
        "VERDICT: ISSUES\n"
        "- [regression] The letter omits the matched skill FastAPI.",
    ]
    pack = _pack(monkeypatch, _fake(BAD_LETTER, verdicts))
    check = pack["letter_check"]
    assert check["verdict"] == "issues" and check["revised"] is True
    assert any("FastAPI" in i for i in check["issues"])
    assert pack["cover_letter"] == FIXED_LETTER


def test_template_letter_is_checked_too(monkeypatch):
    # No rung writes the letter (template path) but a rung answers the
    # check: the verdict still lands in the pack.
    pack = _pack(monkeypatch, _fake(None, ["VERDICT: PASS"]))
    assert pack["provider"] == "template"
    assert pack["letter_check"]["checked"] is True
    assert pack["letter_check"]["verdict"] == "pass"


def test_no_lm_means_unchecked_and_honest(monkeypatch):
    monkeypatch.setattr(llm, "generate",
                        lambda prompt: {"text": None, "provider": None,
                                        "errors": {"gemini": "no key"}})
    p = _profile_with_job()
    r = client.post(f"/api/profiles/{p['id']}/saved-jobs/job1/apply-pack")
    pack = r.json()["apply_pack"]
    assert pack["provider"] == "template"
    assert pack["letter_check"]["checked"] is False
    assert "no key" in pack["letter_check"]["reason"]


def test_unreadable_verdict_is_reported_not_guessed(monkeypatch):
    pack = _pack(monkeypatch, _fake(FIXED_LETTER, ["The letter looks fine to me!"]))
    assert pack["letter_check"]["checked"] is False
    assert "could not be read" in pack["letter_check"]["reason"]
    assert pack["cover_letter"] == FIXED_LETTER
