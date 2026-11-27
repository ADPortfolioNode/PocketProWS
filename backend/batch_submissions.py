"""Batch submissions — one selection per job, one submission per page.

Anthony, 2026-11-26: "dont make separate calls for multiple
submissions — have one selection per job and one submission per page
of responses — so we dont hit the lm repeatedly."

The page-level flow is deliberately split into the two moments that
already existed per job:

1. PREPARE: the selected saved jobs are sent in ONE request. Their
   cover letters are written in ONE LM generation call and checked in
   ONE LM verification call (with at most one batch correction and
   one batch re-check when the checker flags letters). The
   deterministic lint still runs per letter locally. Each finished
   pack is stored on its own job record, exactly as the per-job
   apply-pack endpoint stores it.

2. SUBMIT: after the page review, the selected submissions are sent
   in ONE request. Email itself is still one message per employer —
   that is what an application email is — but the client authorizes
   the reviewed page once, and the response reports every job's
   outcome separately. Nothing sends without the page review's
   explicit confirmation, and a batch that fails pre-validation
   sends nothing at all.
"""
import json
import re
from datetime import datetime, timezone

from . import apply_pack
from . import llm
from . import profiles as profiles_mod
from . import submission as submission_mod

MAX_BATCH_JOBS = 20

_TONE_WORDS = {
    "warm", "friendly", "professional", "confident", "enthusiastic",
    "personable", "approachable", "upbeat", "energetic", "polished",
    "formal", "casual", "conversational", "direct", "concise",
    "humble", "bold", "serious", "sincere", "courteous", "respectful",
}
_TONE_CONNECTORS = {"and", "&"}


def _tone_like(text: str) -> bool:
    words = re.findall(r"[a-z&]+", (text or "").lower())
    return (0 < len(words) <= 6
            and any(w in _TONE_WORDS for w in words)
            and all(w in _TONE_WORDS or w in _TONE_CONNECTORS for w in words))


def _effective_tone(client: dict) -> str:
    fn = getattr(apply_pack, "_effective_tone", None)
    if callable(fn):
        return fn(client)
    tone = (client.get("cover_letter_tone") or "").strip()
    if tone:
        return tone
    highlights = (client.get("cover_letter_highlights") or "").strip()
    return highlights if _tone_like(highlights) else "professional"


def _content_highlights(client: dict) -> str:
    fn = getattr(apply_pack, "_content_highlights", None)
    if callable(fn):
        return fn(client)
    highlights = (client.get("cover_letter_highlights") or "").strip()
    tone = (client.get("cover_letter_tone") or "").strip()
    if highlights and highlights.rstrip(".").lower() == tone.rstrip(".").lower():
        return ""
    if not tone and _tone_like(highlights):
        return ""
    return highlights


def _applicant_block(client: dict) -> str:
    skills = [apply_pack._skill_display(s) for s in client.get("skills") or []]
    return (
        f"Applicant: {client.get('name', '')}\n"
        f"Current role: {client.get('current_role', '')}\n"
        f"Skills on resume: {', '.join(skills)}\n"
        f"Certifications: {', '.join(apply_pack._certs(client))}\n"
        f"Education: {', '.join(client.get('education') or [])}\n"
        f"Highlights to include: {_content_highlights(client)}\n"
        f"Tone on record (the letter's overall posture — it must be FELT, "
        f"never printed): {_effective_tone(client)}\n"
        f"Contact: {client.get('email', '')} "
        f"{apply_pack._phone_display(client.get('phone', ''))}")


def _job_block(item: dict) -> str:
    job, fit = item["job"], item["fit"]
    excerpt = (job.get("snippet") or job.get("description") or "")[:800]
    return (
        f"JOB_ID: {job.get('id', '')}\n"
        f"Job title: {job.get('title', '')}\n"
        f"Employer: {job.get('company', '')}\n"
        f"Location: {job.get('location', '')}\n"
        f"Posting excerpt: {excerpt}\n"
        f"Skills the posting names that the resume MATCHES: "
        f"{', '.join(fit['matched'])}\n"
        f"Skills the posting names that the resume does NOT have: "
        f"{', '.join(fit['missing'])}")


def _batch_generation_prompt(client: dict, items: list) -> str:
    jobs = "\n\n".join(_job_block(item) for item in items)
    return (
        "Write cover letters for multiple job applications in ONE response. "
        "Write one professional cover letter (220-320 words, plain text, no "
        "markdown) for EACH job below. Use ONLY the applicant facts given; "
        "do not invent experience, employers, or credentials, and do not "
        "mix one job's facts into another job's letter.\n\n"
        "Rules for every letter: the tone is the letter's overall posture — "
        "let it shape word choice, warmth and rhythm, and never print the "
        "tone words themselves as a sentence, fragment or sign-off. Use the "
        "applicant's current role exactly as given. Name certifications "
        "exactly as listed; if you state a count of certifications it must "
        "equal the number listed, and never print a date without its year. "
        "Present skill names properly capitalized (API, CI/CD, ChromaDB). "
        "Never add a second period after a name that already ends with one. "
        "Sign off with the applicant's name and contact line.\n\n"
        "Reply with ONLY a JSON array. Each element must be an object with "
        "exactly these fields: \"job_id\" and \"cover_letter\". Include every "
        "JOB_ID exactly once. No other text.\n\n"
        f"THE APPLICANT:\n{_applicant_block(client)}\n\n"
        f"THE JOBS:\n{jobs}")


def _batch_check_prompt(client: dict, items: list) -> str:
    blocks = []
    for item in items:
        blocks.append(
            f"{_job_block(item)}\n"
            f"THE LETTER FOR {item['job'].get('id', '')}:\n{item['letter']}")
    return (
        "Check these cover letters against the applicant's record. Check "
        "each letter only against its own job block. Two failure classes:\n"
        "STUPIDITY — anything wrong: a fact, skill, certification, employer "
        "or date not in the record; a wrong applicant, employer or job "
        "title; contact details that differ from the record (phone DIGITS "
        "must match; dashes or spacing alone are not a difference); "
        "claiming a skill listed as NOT on the resume; placeholders or "
        "bracketed text; contradictions; garbled or duplicated sentences; "
        "the tone/style setting printed as text; a certification count "
        "that does not match the record; a date without its year; a hedged "
        "plural like 'certification(s)'; a doubled period after a name "
        "that already ends with one.\n"
        "REGRESSION — the letter falling short of the record: a matched "
        "skill omitted; a certification on file omitted; requested "
        "highlights dropped; the current role or experience understated; "
        "generic filler where the record is specific.\n"
        "VIBE — each letter's overall posture must match the tone on "
        "record without naming it. If the tone is beyond plain "
        "'professional' and a letter's feel clearly contradicts it, report "
        "a [regression] issue: 'the letter's posture does not match the "
        "tone on record'. Printing the tone words is [stupidity].\n\n"
        "Reply with ONLY a JSON array. Each element must be an object with "
        "\"job_id\", \"verdict\" (\"pass\" or \"issues\"), and \"issues\" (an "
        "array of strings, each starting '[stupidity] ' or '[regression] '). "
        "Include every JOB_ID exactly once. No other text.\n\n"
        f"THE APPLICANT:\n{_applicant_block(client)}\n\n"
        "THE LETTERS:\n" + "\n\n".join(blocks))


def _batch_revise_prompt(client: dict, items: list) -> str:
    blocks = []
    for item in items:
        issues = item["letter_check"].get("issues") or []
        blocks.append(
            f"{_job_block(item)}\n"
            f"PROBLEMS TO FIX:\n" + "\n".join(f"- {i}" for i in issues) +
            f"\nTHE LETTER:\n{item['letter']}")
    return (
        "Revise these cover letters so every listed problem is fixed. Use "
        "ONLY the applicant facts given — do not invent experience, "
        "employers, or credentials, and do not add claims to replace the "
        "ones removed. Keep each letter 220-320 words, plain text, no "
        "markdown, signed with the applicant's name and contact line.\n\n"
        "Reply with ONLY a JSON array. Each element must be an object with "
        "exactly these fields: \"job_id\" and \"cover_letter\". Include every "
        "JOB_ID exactly once. No other text.\n\n"
        f"THE APPLICANT:\n{_applicant_block(client)}\n\n"
        "THE LETTERS TO REVISE:\n" + "\n\n".join(blocks))


def _extract_json_array(text: str):
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start < 0 or end < start:
        return None
    try:
        data = json.loads(cleaned[start:end + 1])
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, list) else None


def _parse_batch_letters(text: str) -> dict:
    data = _extract_json_array(text)
    out = {}
    if not data:
        return out
    for row in data:
        if not isinstance(row, dict):
            continue
        job_id = str(row.get("job_id") or "").strip()
        letter = str(row.get("cover_letter") or row.get("letter") or "").strip()
        if job_id and letter:
            out[job_id] = letter
    return out


def _parse_batch_verdicts(text: str) -> dict:
    data = _extract_json_array(text)
    out = {}
    if not data:
        return out
    for row in data:
        if not isinstance(row, dict):
            continue
        job_id = str(row.get("job_id") or "").strip()
        if not job_id:
            continue
        verdict = "pass" if str(row.get("verdict") or "").lower() == "pass" else "issues"
        raw_issues = row.get("issues") or []
        if isinstance(raw_issues, str):
            raw_issues = [raw_issues]
        issues = [str(i).strip() for i in raw_issues if str(i).strip()]
        if verdict == "issues" and not issues:
            issues = ["the LM flagged issues but did not itemize them"]
        out[job_id] = (verdict, issues)
    return out


def _check_batch(client: dict, items: list) -> list:
    """One LM verification call for the whole page. Flagged letters get
    one batch correction and one batch re-check — still per page, never
    per job."""
    if not items:
        return items
    gen = llm.generate(_batch_check_prompt(client, items))
    if not gen["text"]:
        reason = next(iter(gen["errors"].values()), "no LM rung answered")
        for item in items:
            item["letter_check"] = {"checked": False, "reason": reason,
                                    "batch": True}
        return items
    parsed = _parse_batch_verdicts(gen["text"])
    if not parsed:
        for item in items:
            item["letter_check"] = {
                "checked": False,
                "reason": "the LM's batch verdict could not be read",
                "batch": True}
        return items

    flagged = []
    for item in items:
        job_id = item["job"].get("id", "")
        if job_id not in parsed:
            item["letter_check"] = {
                "checked": False,
                "reason": "the LM batch verdict did not include this job",
                "batch": True}
            continue
        verdict, issues = parsed[job_id]
        item["letter_check"] = {"checked": True, "provider": gen["provider"],
                                "verdict": verdict, "issues": issues,
                                "revised": False, "batch": True}
        if verdict == "issues":
            flagged.append(item)

    if not flagged:
        return items

    rev = llm.generate(_batch_revise_prompt(client, flagged))
    revised = _parse_batch_letters(rev["text"]) if rev["text"] else {}
    revised_items = []
    for item in flagged:
        job_id = item["job"].get("id", "")
        if revised.get(job_id):
            item["letter"] = revised[job_id]
            item["letter_check"]["revised"] = True
            item["letter_check"]["first_issues"] = item["letter_check"]["issues"]
            revised_items.append(item)
        else:
            item["letter_check"]["note"] = (
                "the batch correction could not be completed")

    if revised_items:
        gen2 = llm.generate(_batch_check_prompt(client, revised_items))
        parsed2 = _parse_batch_verdicts(gen2["text"]) if gen2["text"] else {}
        for item in revised_items:
            job_id = item["job"].get("id", "")
            if job_id in parsed2:
                verdict2, issues2 = parsed2[job_id]
                item["letter_check"].update({
                    "verdict": verdict2, "issues": issues2,
                    "provider": gen2["provider"] or item["letter_check"]["provider"]})
            else:
                item["letter_check"]["note"] = (
                    "the letter above is the corrected version; "
                    "the batch re-check could not be completed")
    return items


def build_packs_batch(client: dict, jobs: list) -> dict:
    """Build every selected job's pack with one LM generation call and
    one LM check call for the page. Jobs the LM batch response misses
    fall back to the deterministic template — no extra LM call."""
    items = []
    for job in jobs:
        items.append({"job": job, "fit": apply_pack.fit_for(client, job),
                      "letter": "", "provider": "template", "llm_errors": {}})
    if not items:
        return {}

    gen = llm.generate(_batch_generation_prompt(client, items))
    parsed = _parse_batch_letters(gen["text"]) if gen["text"] else {}
    for item in items:
        job_id = item["job"].get("id", "")
        letter = parsed.get(job_id, "").strip()
        if letter:
            item["letter"] = letter
            item["provider"] = gen["provider"] or "lm"
            item["llm_errors"] = {}
        else:
            item["letter"] = apply_pack.template_letter(
                client, item["job"], item["fit"])
            item["provider"] = "template"
            item["llm_errors"] = gen["errors"] if not gen["text"] else {
                "batch": "the LM batch response did not include this job"}

    _check_batch(client, items)

    packs = {}
    for item in items:
        job, fit = item["job"], item["fit"]
        letter_check = item["letter_check"]
        letter_check["lint_issues"] = apply_pack.lint_letter(
            client, job, fit, item["letter"])
        packs[job.get("id", "")] = {
            "job_id": job.get("id", ""), "title": job.get("title", ""),
            "company": job.get("company", ""), "url": job.get("url", ""),
            "fit": fit, "cover_letter": item["letter"],
            "answers": apply_pack.template_answers(client, job, fit),
            "provider": item["provider"],
            "letter_check": letter_check,
            "llm_errors": item["llm_errors"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "batch": True,
            "note": "Preparation only — review everything, then open the "
                    "posting and submit it yourself, or email the pack "
                    "from here when email is configured. Nothing is "
                    "sent automatically — every email needs your "
                    "approval on its review screen first."}
    return packs


def _dedupe_ids(job_ids) -> list:
    if not isinstance(job_ids, list):
        return []
    seen, out = set(), []
    for raw in job_ids:
        job_id = str(raw or "").strip()
        if job_id and job_id not in seen:
            seen.add(job_id)
            out.append(job_id)
    return out


def prepare_batch(profile_id: str, job_ids) -> dict:
    """Prepare the selected page: one request in, one pack stored per
    selected job, one result row per selected job."""
    ids = _dedupe_ids(job_ids)
    if not ids:
        return {"error": "select at least one job for the page submission",
                "http": 400}
    if len(ids) > MAX_BATCH_JOBS:
        return {"error": f"a page submission can prepare at most "
                         f"{MAX_BATCH_JOBS} jobs at once", "http": 400}
    profiles = profiles_mod._load()
    profile = profiles.get(profile_id)
    if not profile:
        return {"error": "profile not found", "http": 404}
    jobs_by_id = {j.get("id"): j for j in profile.get("saved_jobs") or []}
    missing = [job_id for job_id in ids if job_id not in jobs_by_id]
    if missing:
        return {"error": f"saved job not found: {missing[0]}", "http": 400}

    selected = [jobs_by_id[job_id] for job_id in ids]
    results_by_id = {}
    to_prepare = []
    for job in selected:
        emailed = (job.get("apply_pack") or {}).get("emailed")
        if emailed:
            results_by_id[job.get("id")] = {
                "job_id": job.get("id"), "status": "skipped",
                "reason": "already submitted",
                "application_email": emailed.get("to", "")}
        else:
            to_prepare.append(job)

    packs = build_packs_batch(profile["client"], to_prepare)
    for job in to_prepare:
        job["apply_pack"] = packs[job.get("id", "")]
    profiles_mod._save(profiles)

    for job in to_prepare:
        readiness = submission_mod.readiness(profile, job)
        results_by_id[job.get("id")] = {
            "job_id": job.get("id"), "status": "prepared",
            "application_email": readiness["application_email"],
            "ready": readiness["ready"], "checks": readiness["checks"]}

    return {"profile_id": profile_id, "packs": packs,
            "results": [results_by_id[job_id] for job_id in ids],
            "batch": {"requested": len(ids), "prepared": len(to_prepare),
                      "skipped": len(ids) - len(to_prepare)}}


def submit_batch(profile_id: str, submissions, document_id=None) -> dict:
    """Submit the reviewed page. Every submission is validated before
    the first email sends; after that, each employer's email is sent
    and recorded independently, and the response reports each outcome."""
    if not isinstance(submissions, list) or not submissions:
        return {"error": "the page submission has no jobs to submit",
                "http": 400}
    if len(submissions) > MAX_BATCH_JOBS:
        return {"error": f"a page submission can submit at most "
                         f"{MAX_BATCH_JOBS} jobs at once", "http": 400}
    profile = profiles_mod.get_profile(profile_id)
    if not profile:
        return {"error": "profile not found", "http": 404}

    from . import mailer as mailer_mod
    mail = mailer_mod.status()
    if not mail["configured"]:
        return {"error": "email is not configured — missing "
                         + ", ".join(mail["missing"]) + " in .env",
                "http": 400}
    if document_id:
        info = profiles_mod.document_file(profile_id, document_id)
        if "error" in info:
            return {"error": info["error"], "http": 400}

    jobs_by_id = {j.get("id"): j for j in profile.get("saved_jobs") or []}
    client_name = profile["client"].get("name") or "the client"
    prepared, seen = [], set()
    for raw in submissions:
        if not isinstance(raw, dict):
            return {"error": "each page submission must name a job",
                    "http": 400}
        job_id = str(raw.get("job_id") or "").strip()
        if not job_id or job_id in seen:
            return {"error": "each selected job can be submitted once "
                             "per page", "http": 400}
        seen.add(job_id)
        job = jobs_by_id.get(job_id)
        if not job:
            return {"error": f"saved job not found: {job_id}", "http": 400}
        pack = job.get("apply_pack")
        if not pack:
            return {"error": f"build the apply pack first for "
                             f"{job.get('title', job_id)}", "http": 400}
        if pack.get("emailed"):
            return {"error": f"{job.get('title', job_id)} was already "
                             f"submitted", "http": 400}
        to = str(raw.get("to") or "").strip()
        if not apply_pack._EMAIL_RE.match(to):
            return {"error": f"'{to}' does not look like an email address",
                    "http": 400}
        subject = str(raw.get("subject") or "").strip() or (
            f"Application for {job.get('title', 'the role')} — {client_name}")
        body = str(raw.get("body") or "").strip() or pack.get("cover_letter", "")
        if not body:
            return {"error": f"the email body is empty for "
                             f"{job.get('title', job_id)}", "http": 400}
        prepared.append({"job_id": job_id, "to": to,
                         "subject": subject, "body": body})

    results = []
    sent = 0
    for item in prepared:
        res = apply_pack.email_pack(
            profile_id, item["job_id"], item["to"], item["subject"],
            item["body"], document_id)
        if "error" in res:
            results.append({"job_id": item["job_id"], "status": "failed",
                            "error": res["error"]})
        else:
            sent += 1
            results.append({"job_id": item["job_id"], "status": "sent",
                            "emailed": res["emailed"],
                            "job_status": res["job_status"],
                            "follow_up_due_at": res.get("follow_up_due_at", "")})
    return {"profile_id": profile_id, "results": results,
            "submitted": sent, "failed": len(results) - sent}
