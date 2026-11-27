"""Batch submissions (Anthony, 2026-11-26): one selection per job,
one submission per page — selected letters are written and checked
in one LM batch instead of one LM round-trip per job, and the
reviewed page is submitted in one request."""
import json
import smtplib

from fastapi.testclient import TestClient

from backend import llm
from backend import profiles as profiles_mod
from backend.main import app

client = TestClient(app)

SMTP_ENV = {"POCKETPROWS_SMTP_HOST": "smtp.example.com",
            "POCKETPROWS_SMTP_USER": "sender@example.com",
            "POCKETPROWS_SMTP_PASSWORD": "app-password",
            "POCKETPROWS_SMTP_FROM": "sender@example.com"}


class _FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        self.user = user

    def send_message(self, msg):
        _FakeSMTP.sent.append(msg)


def _configured(monkeypatch):
    for k, v in SMTP_ENV.items():
        monkeypatch.setenv(k, v)
    _FakeSMTP.sent = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)


def _job(jid, title, company, email):
    return {"id": jid, "title": title, "company": company,
            "location": "Remote", "source": "fakeboard",
            "url": f"https://example.com/{jid}",
            "snippet": f"Build Python and FastAPI services. Apply by email to {email}.",
            "application_status": "saved", "status_history": [],
            "last_status_at": None, "follow_up_draft": ""}


def _profile_with_two_jobs():
    p = client.post("/api/profiles", json={"name": "Anthony Dickerson"}).json()
    pid = p["id"]
    r = client.post(
        f"/api/profiles/{pid}/documents",
        files={"file": ("resume.txt",
                        b"Anthony Dickerson\nPython, FastAPI, React developer.\n"
                        b"Certifications: IBM AI Engineering Professional Certificate\n"
                        b"Email: deoism@gmail.com")})
    assert r.status_code == 200, r.text
    doc_id = r.json()["document"]["id"]
    store = profiles_mod._load()
    store[pid]["saved_jobs"].append(
        _job("job1", "Python Developer", "Acme", "jobs@acme.com"))
    store[pid]["saved_jobs"].append(
        _job("job2", "AI Engineer", "Beta", "hiring@beta.com"))
    store[pid]["client"]["cover_letter_highlights"] = (
        "Built three AI products end to end")
    store[pid]["client"]["current_role"] = "Freelance AI Consultant"
    profiles_mod._save(store)
    return pid, doc_id


def _letter(title, company):
    return (f"Dear {company} hiring team,\n\nI am applying for the {title} "
            f"position at {company}. My resume covers Python and FastAPI, "
            f"and I hold the IBM AI Engineering Professional Certificate. "
            f"I built three AI products end to end.\n\nSincerely,\n"
            f"Anthony Dickerson\ndeoism@gmail.com")


def _batch_fake(calls, verdicts=None, revised=None):
    state = {"checks": 0}

    def gen(prompt):
        calls.append(prompt)
        if prompt.startswith("Write cover letters for multiple"):
            return {"text": json.dumps([
                {"job_id": "job1",
                 "cover_letter": _letter("Python Developer", "Acme")},
                {"job_id": "job2",
                 "cover_letter": _letter("AI Engineer", "Beta")}]),
                "provider": "gemini", "errors": {}}
        if prompt.startswith("Check these cover letters"):
            state["checks"] += 1
            if verdicts and state["checks"] == 1:
                return {"text": json.dumps(verdicts),
                        "provider": "gemini", "errors": {}}
            return {"text": json.dumps([
                {"job_id": "job1", "verdict": "pass", "issues": []},
                {"job_id": "job2", "verdict": "pass", "issues": []}]),
                "provider": "gemini", "errors": {}}
        if prompt.startswith("Revise these cover letters"):
            return {"text": json.dumps([
                {"job_id": "job2", "cover_letter": revised}]),
                "provider": "gemini", "errors": {}}
        return {"text": None, "provider": None,
                "errors": {"test": f"unexpected prompt: {prompt[:40]}"}}
    return gen


def test_batch_prepare_uses_one_generation_and_one_check_call(monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "generate", _batch_fake(calls))
    pid, _doc_id = _profile_with_two_jobs()

    r = client.post(f"/api/profiles/{pid}/saved-jobs/apply-packs/batch",
                    json={"job_ids": ["job1", "job2", "job1"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["batch"] == {"requested": 2, "prepared": 2, "skipped": 0}
    assert [row["application_email"] for row in out["results"]] == [
        "jobs@acme.com", "hiring@beta.com"]
    # The whole page cost two LM calls: one write, one check.
    assert len(calls) == 2
    assert calls[0].startswith("Write cover letters for multiple")
    assert calls[1].startswith("Check these cover letters")
    for jid in ("job1", "job2"):
        pack = out["packs"][jid]
        assert pack["provider"] == "gemini"
        assert pack["letter_check"]["checked"] is True
        assert pack["letter_check"]["verdict"] == "pass"
        assert pack["letter_check"]["batch"] is True
        got = client.get(f"/api/profiles/{pid}/saved-jobs/{jid}/apply-pack")
        assert got.json()["apply_pack"]["cover_letter"] == pack["cover_letter"]


def test_batch_check_correction_is_also_batched(monkeypatch):
    calls = []
    revised = _letter("AI Engineer", "Beta").replace(
        "My resume covers Python and FastAPI",
        "My resume covers Python, FastAPI and React")
    verdicts = [
        {"job_id": "job1", "verdict": "pass", "issues": []},
        {"job_id": "job2", "verdict": "issues",
         "issues": ["[regression] The letter omits the matched skill React."]},
    ]
    monkeypatch.setattr(llm, "generate",
                        _batch_fake(calls, verdicts=verdicts, revised=revised))
    pid, _doc_id = _profile_with_two_jobs()

    r = client.post(f"/api/profiles/{pid}/saved-jobs/apply-packs/batch",
                    json={"job_ids": ["job1", "job2"]})
    assert r.status_code == 200, r.text
    pack = r.json()["packs"]["job2"]
    assert pack["cover_letter"] == revised
    assert pack["letter_check"]["revised"] is True
    assert pack["letter_check"]["verdict"] == "pass"
    assert any("React" in i for i in pack["letter_check"]["first_issues"])
    # Write + check + one batch revise + one batch re-check, for the page.
    assert len(calls) == 4


def test_batch_submit_sends_the_reviewed_page_once(monkeypatch):
    _configured(monkeypatch)
    calls = []
    monkeypatch.setattr(llm, "generate", _batch_fake(calls))
    pid, doc_id = _profile_with_two_jobs()
    r = client.post(f"/api/profiles/{pid}/saved-jobs/apply-packs/batch",
                    json={"job_ids": ["job1", "job2"]})
    assert r.status_code == 200, r.text
    packs = r.json()["packs"]

    submissions = [
        {"job_id": "job1", "to": "jobs@acme.com",
         "body": packs["job1"]["cover_letter"]},
        {"job_id": "job2", "to": "hiring@beta.com",
         "body": packs["job2"]["cover_letter"]},
    ]
    # No page approval, no sends. A bad recipient also sends nothing —
    # the batch validates the whole page before the first email.
    r = client.post(f"/api/profiles/{pid}/saved-jobs/submissions/batch",
                    json={"submissions": submissions, "document_id": doc_id})
    assert r.status_code == 400
    bad = [dict(submissions[0]), dict(submissions[1], to="not-an-email")]
    r = client.post(f"/api/profiles/{pid}/saved-jobs/submissions/batch",
                    json={"submissions": bad, "document_id": doc_id,
                          "confirm": True})
    assert r.status_code == 400
    assert _FakeSMTP.sent == []

    r = client.post(f"/api/profiles/{pid}/saved-jobs/submissions/batch",
                    json={"submissions": submissions, "document_id": doc_id,
                          "confirm": True})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["submitted"] == 2 and out["failed"] == 0
    assert [row["status"] for row in out["results"]] == ["sent", "sent"]
    assert [msg["To"] for msg in _FakeSMTP.sent] == [
        "jobs@acme.com", "hiring@beta.com"]
    jobs = client.get(f"/api/profiles/{pid}/saved-jobs").json()["saved_jobs"]
    assert [j["application_status"] for j in jobs] == ["applied", "applied"]

    # Preparing the same page again skips submitted jobs and does not
    # spend another LM call on them.
    before = len(calls)
    r = client.post(f"/api/profiles/{pid}/saved-jobs/apply-packs/batch",
                    json={"job_ids": ["job1", "job2"]})
    assert r.status_code == 200, r.text
    assert r.json()["batch"] == {"requested": 2, "prepared": 0, "skipped": 2}
    assert len(calls) == before
