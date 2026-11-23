"""Apply pack — everything a client needs to apply to one saved job,
generated from their own profile (Anthony, 2026-11-22).

For one saved job, from the client's record (resume-sourced skills,
certifications, interview preferences, cover-letter highlights/tone):

- a FIT CHECK: which of the posting's skills the resume already has,
  and which it does not — computed by matching, never invented;
- a COVER LETTER: written by the LLM chain when a key is configured
  (backend/llm.py), otherwise a deterministic template built from the
  same facts. The pack says which provider wrote it. The LM then
  CHECKS the letter against the record (Anthony, 2026-11-22) for
  stupidity — invented facts, wrong names or contact details,
  placeholders, contradictions — and for regression — the letter
  falling short of the record (matched skills or certifications
  omitted, requested highlights dropped, the role understated).
  Issues trigger one correction pass and a re-check; the pack
  carries the verdict either way;
- DRAFT ANSWERS to the standard application questions, built only
  from facts on the profile (no invented credentials, no legal
  attestations — those stay the client's to answer).

Nothing is ever submitted: the pack is preparation. The client reads
it, opens the employer's posting, pastes, and submits themselves —
applying stays human by design (see backend/agents.py).
"""
from datetime import datetime, timezone

from . import llm
from . import profiles as profiles_mod
from .profiles import _SKILL_PATTERNS


def _job_skills(job: dict) -> list:
    text = " ".join([job.get("title", ""), job.get("snippet", ""),
                     job.get("company", "")]).lower()
    return sorted(s for s, pat in _SKILL_PATTERNS.items() if pat.search(text))


def fit_for(client: dict, job: dict) -> dict:
    wanted = _job_skills(job)
    have = {s.lower() for s in client.get("skills") or []}
    matched = [s for s in wanted if s in have]
    missing = [s for s in wanted if s not in have]
    coverage = round(len(matched) / len(wanted), 2) if wanted else None
    if not wanted:
        summary = ("The posting's text names no skills from our vocabulary, "
                   "so fit is judged on the title and description alone.")
    elif coverage >= 0.75:
        summary = (f"Strong match: the resume covers {len(matched)} of the "
                   f"{len(wanted)} skills this posting names.")
    elif coverage >= 0.4:
        summary = (f"Partial match: {len(matched)} of {len(wanted)} named "
                   f"skills are on the resume; {len(missing)} to address.")
    else:
        summary = (f"Stretch match: only {len(matched)} of {len(wanted)} "
                   f"named skills are on the resume.")
    return {"wanted": wanted, "matched": matched, "missing": missing,
            "coverage": coverage, "summary": summary}


def _clean_cert(cert: str) -> str:
    """Older digests may keep the 'Certifications: ' label on the entry;
    the letter and answers use the credential's name only."""
    import re
    return re.sub(r"(?i)^(certifications?|certs?)\s*:\s*", "", cert or "").strip()


def _certs(client: dict) -> list:
    return [c for c in (_clean_cert(c) for c in client.get("certifications") or []) if c]


def _join(words: list, last: str = "and") -> str:
    words = [w for w in words if w]
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + f" {last} " + words[-1]


def template_letter(client: dict, job: dict, fit: dict) -> str:
    name = client.get("name") or "Your Name"
    title = job.get("title") or "the role"
    company = job.get("company") or "your company"
    role = client.get("current_role") or ""
    skills = fit["matched"] or (client.get("skills") or [])[:5]
    certs = _certs(client)
    highlights = (client.get("cover_letter_highlights") or "").strip()
    contact = " · ".join(x for x in [client.get("email", ""), client.get("phone", ""),
                                     client.get("linkedin", "")] if x)
    lines = [f"Dear {company} hiring team,", ""]
    opener = f"I am applying for the {title} position at {company}."
    if role:
        opener += f" I currently work as a {role}."
    lines.append(opener)
    body = ""
    if skills:
        body = (f"My resume covers the skills this posting calls for, including "
                f"{_join(skills[:6])}.")
    if certs:
        body += (f" I also hold {certs[0]}" if body else f"I hold {certs[0]}")
        body += (f", along with {len(certs) - 1} further certification(s)."
                 if len(certs) > 1 else ".")
    if body:
        lines += ["", body]
    if highlights:
        lines += ["", highlights if highlights.endswith(".") else highlights + "."]
    lines += ["", f"I would welcome the chance to discuss how my experience fits "
                  f"the {title} role. Thank you for your consideration.",
              "", "Sincerely,", name]
    if contact:
        lines.append(contact)
    return "\n".join(lines)


def template_answers(client: dict, job: dict, fit: dict) -> list:
    name = client.get("name") or "the client"
    title = job.get("title") or "this role"
    company = job.get("company") or "the company"
    skills = fit["matched"] or (client.get("skills") or [])[:4]
    answers = []
    why = (f"I am applying for the {title} role at {company} because it matches "
           f"the work I do and want to keep doing")
    targets = client.get("target_roles") or []
    if targets:
        why += f" — my target roles include {_join(targets[:3])}"
    if skills:
        why += (f". The posting's core skills ({_join(skills[:4])}) are the "
                f"ones on my resume, so the fit is direct.")
    else:
        why += "."
    answers.append({"question": "Why are you interested in this role?", "answer": why})
    strengths = []
    if skills:
        strengths.append(f"hands-on experience with {_join(skills[:5])}")
    if client.get("education"):
        strengths.append(f"educated at {_join((client['education'])[:2])}")
    if strengths:
        subject = f"{name.split()[0]} brings" if name and name != "the client" else "I bring"
        fit_answer = f"{subject} {_join(strengths)}."
        if _certs(client):
            fit_answer += f" Certifications include {_join(_certs(client)[:2])}."
    elif _certs(client):
        fit_answer = f"Certifications include {_join(_certs(client)[:2])}, alongside the experience on my resume."
    else:
        fit_answer = ("My resume (attached) lays out my experience for this role; "
                      "the skills it lists are the ones I would bring to the position.")
    answers.append({"question": "What makes you a strong fit for this position?",
                    "answer": fit_answer})
    arrangement_bits = [b for b in [client.get("remote_preference", ""),
                                    client.get("employment_type", ""),
                                    ("based in " + client["location"]) if client.get("location") else ""] if b]
    if arrangement_bits:
        answers.append({"question": "What is your preferred work arrangement?",
                        "answer": "I am looking for " + _join(arrangement_bits) + "."})
    if (client.get("salary_text") or "").strip():
        answers.append({"question": "What are your salary expectations?",
                        "answer": client["salary_text"].strip()})
    return answers


def _lm_prompt(client: dict, job: dict, fit: dict) -> str:
    return (
        "Write a professional cover letter (250-350 words, plain text, no "
        "markdown) for this job application. Use ONLY the facts given; do "
        "not invent experience, employers, or credentials.\n\n"
        f"Applicant: {client.get('name', '')}\n"
        f"Current role: {client.get('current_role', '')}\n"
        f"Skills on resume: {', '.join(client.get('skills') or [])}\n"
        f"Certifications: {', '.join(_certs(client))}\n"
        f"Education: {', '.join(client.get('education') or [])}\n"
        f"Highlights the applicant wants mentioned: {client.get('cover_letter_highlights', '')}\n"
        f"Preferred tone: {client.get('cover_letter_tone', '') or 'professional'}\n"
        f"Contact: {client.get('email', '')} {client.get('phone', '')}\n\n"
        f"Job title: {job.get('title', '')}\n"
        f"Employer: {job.get('company', '')}\n"
        f"Location: {job.get('location', '')}\n"
        f"Posting excerpt: {(job.get('snippet') or '')[:800]}\n"
        f"Skills the posting names that the resume matches: {', '.join(fit['matched'])}\n"
        "Sign off with the applicant's name and contact line."
    )


def _facts_block(client: dict, job: dict, fit: dict) -> str:
    """The ground truth a letter is checked against — the same facts
    the letter was built from, nothing else."""
    return (
        f"Applicant: {client.get('name', '')}\n"
        f"Current role: {client.get('current_role', '')}\n"
        f"Skills on resume: {', '.join(client.get('skills') or [])}\n"
        f"Certifications: {', '.join(_certs(client))}\n"
        f"Education: {', '.join(client.get('education') or [])}\n"
        f"Highlights the applicant asked to include: {client.get('cover_letter_highlights', '')}\n"
        f"Contact on record — email: {client.get('email', '')} · phone: {client.get('phone', '')}\n"
        f"Job: {job.get('title', '')} at {job.get('company', '')} ({job.get('location', '')})\n"
        f"Skills the posting names that the resume MATCHES: {', '.join(fit['matched'])}\n"
        f"Skills the posting names that the resume does NOT have: {', '.join(fit['missing'])}")


def _verify_prompt(client: dict, job: dict, fit: dict, letter: str) -> str:
    return (
        "Check this cover letter against the applicant's record. Two "
        "failure classes:\n"
        "STUPIDITY — anything in the letter that is wrong: a fact, skill, "
        "certification, employer or date not in the record; a wrong name "
        "(applicant, employer, job title); contact details that differ "
        "from the record; claiming a skill listed as NOT on the resume; "
        "leftover placeholders or bracketed text; contradictions; "
        "garbled, duplicated or nonsensical sentences.\n"
        "REGRESSION — the letter falling short of the record: a matched "
        "skill the posting names is omitted; a certification on file is "
        "omitted; the applicant's requested highlights are dropped; the "
        "current role or experience is understated; generic filler where "
        "the record is specific.\n\n"
        "Reply with EXACTLY this shape: the first line is 'VERDICT: PASS' "
        "or 'VERDICT: ISSUES'. If ISSUES, follow with one line per issue, "
        "each starting '- [stupidity] ' or '- [regression] ', naming the "
        "problem precisely. No other text.\n\n"
        f"THE RECORD:\n{_facts_block(client, job, fit)}\n\n"
        f"THE LETTER:\n{letter}")


def _parse_verdict(text: str):
    """(verdict, issues) from the LM's reply, or None when the reply
    does not follow the verdict shape."""
    if not text:
        return None
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines or not lines[0].upper().startswith("VERDICT:"):
        return None
    verdict = "pass" if "PASS" in lines[0].upper() else "issues"
    issues = [ln[2:].strip() for ln in lines[1:] if ln.startswith("- ")]
    if verdict == "issues" and not issues:
        issues = ["the LM flagged issues but did not itemize them"]
    return verdict, issues


def _revise_prompt(client: dict, job: dict, fit: dict, letter: str, issues: list) -> str:
    return (
        "Revise this cover letter so every problem below is fixed. Use "
        "ONLY the facts in the record — do not invent experience, "
        "employers, or credentials, and do not add claims to replace the "
        "ones removed. Keep it 250-350 words, plain text, no markdown, "
        "signed with the applicant's name and the contact line from the "
        "record.\n\n"
        f"PROBLEMS TO FIX:\n" + "\n".join(f"- {i}" for i in issues) +
        f"\n\nTHE RECORD:\n{_facts_block(client, job, fit)}\n\n"
        f"THE LETTER:\n{letter}")


def check_letter(client: dict, job: dict, fit: dict, letter: str):
    """The LM verifies the letter for stupidity and regression
    (Anthony, 2026-11-22). Returns (letter, check): on flagged issues
    the letter gets ONE correction pass and is re-checked; the check
    reports the final verdict either way. When no LM rung answers,
    the letter ships unchecked and the check says so."""
    gen = llm.generate(_verify_prompt(client, job, fit, letter))
    if not gen["text"]:
        reason = next(iter(gen["errors"].values()), "no LM rung answered")
        return letter, {"checked": False, "reason": reason}
    parsed = _parse_verdict(gen["text"])
    if parsed is None:
        return letter, {"checked": False,
                        "reason": "the LM's verdict could not be read"}
    verdict, issues = parsed
    check = {"checked": True, "provider": gen["provider"],
             "verdict": verdict, "issues": issues, "revised": False}
    if verdict == "pass":
        return letter, check
    rev = llm.generate(_revise_prompt(client, job, fit, letter, issues))
    if not rev["text"]:
        return letter, check
    letter2 = rev["text"]
    gen2 = llm.generate(_verify_prompt(client, job, fit, letter2))
    parsed2 = _parse_verdict(gen2["text"]) if gen2["text"] else None
    check["revised"] = True
    if parsed2 is None:
        check["note"] = ("the letter above is the corrected version; "
                         "the re-check could not be completed")
        return letter2, check
    verdict2, issues2 = parsed2
    check.update({"verdict": verdict2, "issues": issues2,
                  "provider": gen2["provider"] or check["provider"],
                  "first_issues": issues})
    return letter2, check


def build_pack(client: dict, job: dict) -> dict:
    fit = fit_for(client, job)
    gen = llm.generate(_lm_prompt(client, job, fit))
    if gen["text"]:
        letter, provider = gen["text"], gen["provider"]
    else:
        letter, provider = template_letter(client, job, fit), "template"
    letter, letter_check = check_letter(client, job, fit, letter)
    return {"job_id": job.get("id", ""), "title": job.get("title", ""),
            "company": job.get("company", ""), "url": job.get("url", ""),
            "fit": fit, "cover_letter": letter,
            "answers": template_answers(client, job, fit),
            "provider": provider,
            "letter_check": letter_check,
            "llm_errors": gen["errors"] if not gen["text"] else {},
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "note": "Preparation only — review everything, then open the "
                    "posting and submit it yourself, or email the pack "
                    "from here when email is configured. Nothing is "
                    "sent automatically — every email needs your "
                    "approval on its review screen first."}


def generate_pack(profile_id: str, job_id: str) -> dict:
    """Build (or rebuild) the pack for one saved job and store it on the
    job record, so it survives reloads and shows in the status view."""
    profiles = profiles_mod._load()
    p = profiles.get(profile_id)
    if not p:
        return {"error": "profile not found"}
    job = next((j for j in p["saved_jobs"] if j.get("id") == job_id), None)
    if not job:
        return {"error": "saved job not found"}
    pack = build_pack(p["client"], job)
    job["apply_pack"] = pack
    profiles_mod._save(profiles)
    return {"profile_id": profile_id, "apply_pack": pack}


def get_pack(profile_id: str, job_id: str) -> dict:
    p = profiles_mod.get_profile(profile_id)
    if not p:
        return {"error": "profile not found"}
    job = next((j for j in p["saved_jobs"] if j.get("id") == job_id), None)
    if not job:
        return {"error": "saved job not found"}
    return {"profile_id": profile_id, "apply_pack": job.get("apply_pack")}
