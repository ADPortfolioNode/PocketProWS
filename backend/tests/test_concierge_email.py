"""The concierge as admin: emailing a pack from the conversation.

The flow under test mirrors the pack panel's review screen: the
concierge prepares the send and shows the exact message; only the
client's 'send it' in chat sends — anything else holds or cancels.
"""
import smtplib

from fastapi.testclient import TestClient

from backend import chat as chat_mod
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
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        _FakeSMTP.sent.append(msg)


def _configured(monkeypatch):
    for k, v in SMTP_ENV.items():
        monkeypatch.setenv(k, v)
    _FakeSMTP.sent = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)


def _profile_with_pack(jobs=("job-c1",), with_doc=True):
    r = client.post("/api/profiles", json={"name": "Chat Client"})
    pid = r.json()["id"]
    profiles = profiles_mod._load()
    for jid in jobs:
        profiles[pid]["saved_jobs"].append(
            {"id": jid, "title": f"Role {jid}", "company": "Acme",
             "location": "Remote", "source": "fakeboard",
             "url": f"https://example.com/{jid}", "snippet": "Build things.",
             "application_status": "saved", "status_history": [],
             "last_status_at": None, "follow_up_draft": ""})
    profiles_mod._save(profiles)
    for jid in jobs:
        r = client.post(f"/api/profiles/{pid}/saved-jobs/{jid}/apply-pack")
        assert r.status_code == 200, r.text
    if with_doc:
        r = client.post(f"/api/profiles/{pid}/documents",
                        files={"file": ("resume.txt",
                                        b"Chat Client\npython, react")})
        assert r.status_code == 200, r.text
    return pid


def _say(pid, text):
    return chat_mod.answer(text, profile_id=pid)["answer"]


def test_concierge_prepares_reviews_then_sends_on_approval(monkeypatch):
    _configured(monkeypatch)
    pid = _profile_with_pack()
    ans = _say(pid, "email the application to hiring@acme.com")
    assert "Ready to email" in ans
    assert "hiring@acme.com" in ans and "resume.txt" in ans
    assert _FakeSMTP.sent == []  # preparing is not sending
    # An unrelated message does not send — the send holds the floor.
    ans = _say(pid, "how are we doing")
    assert "waiting for your word" in ans
    assert _FakeSMTP.sent == []
    ans = _say(pid, "send it")
    assert ans.startswith("Sent")
    assert len(_FakeSMTP.sent) == 1
    assert _FakeSMTP.sent[0]["To"] == "hiring@acme.com"
    pack = client.get(f"/api/profiles/{pid}/saved-jobs/job-c1/apply-pack").json()
    assert pack["apply_pack"]["emailed"]["to"] == "hiring@acme.com"
    jobs = client.get(f"/api/profiles/{pid}/saved-jobs").json()["saved_jobs"]
    assert jobs[0]["application_status"] == "applied"
    assert profiles_mod.get_pending_email(pid) is None


def test_concierge_cancel_sends_nothing(monkeypatch):
    _configured(monkeypatch)
    pid = _profile_with_pack()
    _say(pid, "email the application to hiring@acme.com")
    ans = _say(pid, "cancel")
    assert "nothing was sent" in ans
    assert _FakeSMTP.sent == []
    assert profiles_mod.get_pending_email(pid) is None


def test_concierge_asks_for_address_when_missing(monkeypatch):
    _configured(monkeypatch)
    pid = _profile_with_pack()
    ans = _say(pid, "email the application")
    assert "What email address" in ans
    ans = _say(pid, "hiring@acme.com")
    assert "Ready to email" in ans
    ans = _say(pid, "send it")
    assert ans.startswith("Sent")
    assert len(_FakeSMTP.sent) == 1


def test_concierge_unconfigured_is_honest(monkeypatch):
    for k in SMTP_ENV:
        monkeypatch.delenv(k, raising=False)
    pid = _profile_with_pack()
    ans = _say(pid, "email the application to hiring@acme.com")
    assert "isn't configured" in ans
    assert "POCKETPROWS_SMTP_HOST" in ans
    assert profiles_mod.get_pending_email(pid) is None


def test_concierge_no_pack_ready(monkeypatch):
    _configured(monkeypatch)
    r = client.post("/api/profiles", json={"name": "No Pack Chat"})
    pid = r.json()["id"]
    ans = _say(pid, "email the application to hiring@acme.com")
    assert "no apply pack ready" in ans


def test_concierge_disambiguates_two_packs(monkeypatch):
    _configured(monkeypatch)
    pid = _profile_with_pack(jobs=("job-c1", "job-c2"))
    ans = _say(pid, "email the application to hiring@acme.com")
    assert "More than one pack is ready" in ans
    assert "Role job-c2" in ans
    ans = _say(pid, "2")
    assert "Ready to email" in ans and "Role job-c2" in ans
    ans = _say(pid, "send it")
    assert ans.startswith("Sent")
    assert len(_FakeSMTP.sent) == 1
    assert "Role job-c2" in _FakeSMTP.sent[0]["Subject"]
