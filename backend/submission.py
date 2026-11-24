"""Submission readiness — is everything collected for this job's
application to go out? (Anthony, 2026-11-24: "i do want the system
to automatically submit jobs after I authorize — each job lead
should have a submit button — as soon as it is all collected the
submit button appears — when ready — and I authorize — WS then
emails submission — provide an agent for this task.")

The submission channel is email (apply_pack.email_pack — the pack's
cover letter + the resume, from the client's own mailbox), sent only
on the client's per-job authorization: the Submit button's
"Authorize and submit", or the concierge's in-chat approval. This
module answers the readiness question for the button, the submit
panel and the submission agent: pack built? client contact on file?
a document to attach? an application email for the job — found in
the posting when the posting carries one, otherwise the client
supplies it at submit time. Employer web forms are never touched:
the boards expose no apply API, and attestation stays human.
"""
import re

from . import profiles as profiles_mod

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def find_application_email(job: dict) -> str:
    """The posting's own application email, when the saved job carries
    one (some boards put 'apply by email' in the snippet). Sentence
    punctuation glued to the address ("…to jobs@acme.com.") is not
    part of it."""
    for field in ("snippet", "url", "title", "company"):
        m = _EMAIL.search(str(job.get(field) or ""))
        if m:
            return m.group(0).rstrip(".,;:")
    return ""


def readiness(profile: dict, job: dict) -> dict:
    """The checklist for one saved job. `ready` means the Submit
    button shows: the pack is built and the job is not submitted yet.
    A missing application email does not hide the button — the
    posting often doesn't carry one — it is collected in the submit
    panel instead, and the check says so."""
    pack = job.get("apply_pack")
    client = profile.get("client") or {}
    docs = profile.get("documents") or []
    found = find_application_email(job)
    emailed = (pack or {}).get("emailed")
    checks = [
        {"key": "pack",
         "label": "Apply pack built — cover letter and answers from the profile",
         "ok": bool(pack),
         "detail": "" if pack else "build the apply pack first"},
        {"key": "contact",
         "label": "Client contact on the letter",
         "ok": bool(client.get("email")),
         "detail": "" if client.get("email")
         else "no email on the profile — add it in Edit profile"},
        {"key": "document",
         "label": "A document to attach (the resume)",
         "ok": bool(docs),
         "detail": "" if docs else "no documents on the profile yet"},
        {"key": "recipient",
         "label": "Application email for this job",
         "ok": bool(found),
         "detail": found if found else
         "not in the posting — enter the employer's application email to submit"},
    ]
    return {"job_id": job.get("id"), "submitted": emailed,
            "application_email": found,
            "ready": bool(pack) and not emailed,
            "checks": checks}


def for_job(profile_id: str, job_id: str) -> dict:
    p = profiles_mod.get_profile(profile_id)
    if not p:
        return {"error": "profile not found", "http": 404}
    job = next((j for j in p.get("saved_jobs") or []
                if j.get("id") == job_id), None)
    if not job:
        return {"error": "job not found in this profile's saved jobs",
                "http": 404}
    return readiness(p, job)


def agent_scan(profile: dict) -> dict:
    """The submission agent's view of the whole pipeline."""
    jobs = profile.get("saved_jobs") or []
    rows = [readiness(profile, j) for j in jobs]
    return {
        "total": len(rows),
        "submitted": sum(1 for r in rows if r["submitted"]),
        "ready": sum(1 for r in rows
                     if r["ready"] and r["application_email"]),
        "needs_recipient": sum(1 for r in rows
                               if r["ready"] and not r["application_email"]),
        "needs_pack": sum(1 for j in jobs if not j.get("apply_pack")),
        "rows": rows,
    }
