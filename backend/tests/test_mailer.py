"""Emailing a finished apply pack — the final step of application prep.

The gates under test: nothing sends without the caller's explicit
approval for that message; nothing sends unconfigured (and says why);
a bad recipient is refused; a real send (fake SMTP) carries the
reviewed letter and the chosen resume, is recorded on the pack, and
moves a 'saved' job to 'applied'.
"""
import smtplib

from fastapi.testclient import TestClient

from backend import mailer as mailer_mod
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


def _unconfigured(monkeypatch):
    for k in SMTP_ENV:
        monkeypatch.delenv(k, raising=False)


def _profile_with_pack():
    r = client.post("/api/profiles", json={"name": "Mail Client"})
    pid = r.json()["id"]
    client.patch(f"/api/profiles/{pid}", json={
        "client": {"target_roles": ["AI Engineer"], "location": "Remote, USA"}})
    # Save a job directly on the profile, then build its pack.
    from backend import profiles as profiles_mod
    profiles = profiles_mod._load()
    profiles[pid]["saved_jobs"].append(
        {"id": "job-mail-1", "title": "AI Engineer", "company": "Acme",
         "location": "Remote", "source": "fakeboard",
         "url": "https://example.com/job-mail-1", "snippet": "Build things.",
         "application_status": "saved", "status_history": [],
         "last_status_at": None, "follow_up_draft": ""})
    profiles_mod._save(profiles)
    r = client.post(f"/api/profiles/{pid}/saved-jobs/job-mail-1/apply-pack")
    assert r.status_code == 200, r.text
    # A document to attach.
    r = client.post(f"/api/profiles/{pid}/documents",
                    files={"file": ("resume.txt", b"Anthony Dickerson\nAI Engineer\npython, react")})
    assert r.status_code == 200, r.text
    doc_id = r.json()["document"]["id"]
    return pid, doc_id


def test_mail_status_unconfigured(monkeypatch):
    _unconfigured(monkeypatch)
    st = client.get("/api/mail/status").json()
    assert st["configured"] is False
    assert "POCKETPROWS_SMTP_HOST" in st["missing"]


def test_send_requires_explicit_approval(monkeypatch):
    _configured(monkeypatch)
    pid, _doc = _profile_with_pack()
    r = client.post(f"/api/profiles/{pid}/saved-jobs/job-mail-1/email-application",
                    json={"to": "hiring@acme.com"})
    assert r.status_code == 400
    assert "approval" in r.json()["detail"]
    assert _FakeSMTP.sent == []


def test_send_unconfigured_names_what_is_missing(monkeypatch):
    _unconfigured(monkeypatch)
    pid, _doc = _profile_with_pack()
    r = client.post(f"/api/profiles/{pid}/saved-jobs/job-mail-1/email-application",
                    json={"to": "hiring@acme.com", "confirm": True})
    assert r.status_code == 400
    assert "POCKETPROWS_SMTP_HOST" in r.json()["detail"]


def test_send_rejects_bad_recipient(monkeypatch):
    _configured(monkeypatch)
    pid, _doc = _profile_with_pack()
    r = client.post(f"/api/profiles/{pid}/saved-jobs/job-mail-1/email-application",
                    json={"to": "not-an-email", "confirm": True})
    assert r.status_code == 400
    assert _FakeSMTP.sent == []


def test_approved_send_carries_letter_and_resume_and_records(monkeypatch):
    _configured(monkeypatch)
    pid, doc_id = _profile_with_pack()
    r = client.post(f"/api/profiles/{pid}/saved-jobs/job-mail-1/email-application",
                    json={"to": "hiring@acme.com", "confirm": True,
                          "document_id": doc_id})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["emailed"]["to"] == "hiring@acme.com"
    assert out["emailed"]["attachment"] == "resume.txt"
    assert out["job_status"] == "applied"
    assert len(_FakeSMTP.sent) == 1
    msg = _FakeSMTP.sent[0]
    assert msg["To"] == "hiring@acme.com"
    assert "AI Engineer" in msg["Subject"]
    body = msg.get_body(("plain",)).get_content()
    assert "Mail Client" in body or "AI Engineer" in body
    attachments = list(msg.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "resume.txt"
    # Recorded on the pack, and the pipeline moved.
    pack = client.get(f"/api/profiles/{pid}/saved-jobs/job-mail-1/apply-pack").json()
    assert pack["apply_pack"]["emailed"]["to"] == "hiring@acme.com"
    jobs = client.get(f"/api/profiles/{pid}/saved-jobs").json()["saved_jobs"]
    assert jobs[0]["application_status"] == "applied"
    assert "emailed" in jobs[0]["status_history"][-1]["note"].lower()


def test_send_without_pack_is_refused(monkeypatch):
    _configured(monkeypatch)
    r = client.post("/api/profiles", json={"name": "No Pack"})
    pid = r.json()["id"]
    from backend import profiles as profiles_mod
    profiles = profiles_mod._load()
    profiles[pid]["saved_jobs"].append(
        {"id": "job-nopack", "title": "X", "company": "Y", "source": "z",
         "url": "", "snippet": "", "application_status": "saved",
         "status_history": [], "last_status_at": None, "follow_up_draft": ""})
    profiles_mod._save(profiles)
    r = client.post(f"/api/profiles/{pid}/saved-jobs/job-nopack/email-application",
                    json={"to": "hiring@acme.com", "confirm": True})
    assert r.status_code == 400
    assert "apply pack" in r.json()["detail"]
    assert _FakeSMTP.sent == []
