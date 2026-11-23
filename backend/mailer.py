"""Outbound email for PocketProWS — the final step of application prep.

Anthony (2026-11-23): "give pocketprows ability to email — the final
step of application prep — when ready — and approved — send!"

The boundary is explicit: this module never sends on its own. The one
send path runs only from the API endpoint behind the UI's review step,
with the caller's explicit approval for that specific message. The
employer-site rule is unchanged — the app still never fills or submits
web application forms; email is a channel the client directs, to a
recipient he types, with the exact text he reviewed.

Configuration is environment-only (the local .env, like the LLM keys —
never in code, never in chat):

  POCKETPROWS_SMTP_HOST      e.g. smtp.gmail.com
  POCKETPROWS_SMTP_PORT      default 587 (STARTTLS)
  POCKETPROWS_SMTP_USER      the mailbox login
  POCKETPROWS_SMTP_PASSWORD  an app password for the mailbox,
                             never the account password itself
  POCKETPROWS_SMTP_FROM      optional From address (default: the user)
"""
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

REQUIRED = ("POCKETPROWS_SMTP_HOST", "POCKETPROWS_SMTP_USER",
            "POCKETPROWS_SMTP_PASSWORD")

_CONTENT_TYPES = {
    ".pdf": ("application", "pdf"),
    ".docx": ("application",
              "vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".txt": ("text", "plain"),
    ".md": ("text", "markdown"),
}


def _config() -> dict:
    env = {k: os.environ.get(k, "").strip()
           for k in REQUIRED + ("POCKETPROWS_SMTP_FROM",)}
    try:
        port = int(os.environ.get("POCKETPROWS_SMTP_PORT", "587") or "587")
    except ValueError:
        port = 587
    return {"host": env["POCKETPROWS_SMTP_HOST"],
            "user": env["POCKETPROWS_SMTP_USER"],
            "password": env["POCKETPROWS_SMTP_PASSWORD"],
            "from": env["POCKETPROWS_SMTP_FROM"] or env["POCKETPROWS_SMTP_USER"],
            "port": port,
            "missing": [k for k in REQUIRED if not env[k]]}


def status() -> dict:
    """What the UI needs: is email configured, and as whom."""
    cfg = _config()
    return {"configured": not cfg["missing"],
            "from": cfg["from"] if not cfg["missing"] else "",
            "missing": cfg["missing"]}


def send(to: str, subject: str, body: str, attachment: dict = None) -> dict:
    """Send one message. attachment: {"filename", "data" (bytes)}.
    Returns the send record; raises RuntimeError with the real reason
    when the send fails — callers surface it, never swallow it."""
    cfg = _config()
    if cfg["missing"]:
        raise RuntimeError("email is not configured — missing "
                           + ", ".join(cfg["missing"]) + " in .env")
    msg = EmailMessage()
    msg["From"] = cfg["from"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if attachment:
        maintype, subtype = _CONTENT_TYPES.get(
            Path(attachment["filename"]).suffix.lower(),
            ("application", "octet-stream"))
        msg.add_attachment(attachment["data"], maintype=maintype,
                           subtype=subtype, filename=attachment["filename"])
    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as smtp:
            smtp.starttls()
            smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the caller
        raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc
    return {"to": to, "subject": subject, "from": cfg["from"],
            "attachment": (attachment or {}).get("filename", ""),
            "at": datetime.now(timezone.utc).isoformat()}
