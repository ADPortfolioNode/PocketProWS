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

Nothing is ever submitted to an employer's site: the pack is
preparation. The client reads it and submits themselves — or directs
the app to email it (email_pack below): one message, to a recipient
they name, only after their explicit approval for that send.
Applying on web forms stays human by design (see backend/agents.py).
"""
import re
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


_CERT_LABELS = ("professional certificates", "professional certificate",
                "certifications", "certification", "certificates",
                "certificate", "certs", "cert")
_PARTIAL_DATE = re.compile(
    r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}$",
    re.IGNORECASE)


def _clean_cert(cert: str) -> str:
    """Older digests may keep a label on the entry ('Certifications: ',
    or the Coursera heading 'Professional Certificates'); the letter
    and answers use the credential's name only."""
    text = re.sub(r"(?i)^(certifications?|certs?)\s*:\s*", "", cert or "").strip()
    lowered = text.lower()
    for label in _CERT_LABELS:
        if lowered.startswith(label + " "):
            text = text[len(label):].strip(" :—-")
            break
    return text


def _cert_display(cert: str) -> str:
    """How a stored certification entry reads in a letter: cleaned of
    its digest labels, and a trailing date fragment WITHOUT a year
    ('— Jul 11') is dropped — a partial date in a letter is worse
    than no date (Anthony's live letter, 2026-11-24)."""
    text = _clean_cert(cert)
    parts = [p.strip() for p in text.split(" — ")]
    if len(parts) > 1 and _PARTIAL_DATE.match(parts[-1]):
        parts = parts[:-1]
    return " — ".join(p for p in parts if p)


def _certs(client: dict) -> list:
    """The record's certifications, display-cleaned and deduplicated
    (case-insensitively) — duplicates in the stored list used to
    inflate the count the letter quoted."""
    seen, out = set(), []
    for raw in client.get("certifications") or []:
        cert = _cert_display(raw)
        if cert and cert.lower() not in seen:
            seen.add(cert.lower())
            out.append(cert)
    return out


_SKILL_DISPLAY = {
    "api": "API", "apis": "APIs", "ci/cd": "CI/CD", "css": "CSS",
    "html": "HTML", "chromadb": "ChromaDB", "chroma": "Chroma",
    "sql": "SQL", "llm": "LLM", "llms": "LLMs", "rag": "RAG",
    "rest": "REST", "ai": "AI", "ml": "ML", "nlp": "NLP", "ui": "UI",
    "ux": "UX", "aws": "AWS", "gcp": "GCP", "git": "Git",
    "python": "Python", "javascript": "JavaScript",
    "typescript": "TypeScript", "react": "React", "flask": "Flask",
    "fastapi": "FastAPI", "docker": "Docker", "node": "Node.js",
    "nodejs": "Node.js", "php": "PHP", "java": "Java", "linux": "Linux",
}


def _skill_display(skill: str) -> str:
    """How a stored skill reads in a letter: the digest stores skills
    lowercase ('api', 'chromadb'); a letter presents them properly
    ('API', 'ChromaDB'). Multi-word phrases ('data entry') pass
    through unchanged — only single words are re-cased."""
    text = (skill or "").strip()
    if not text or " " in text:
        return text
    return _SKILL_DISPLAY.get(text.lower(), text[:1].upper() + text[1:])


def _article(word: str) -> str:
    return "an" if (word or "")[:1].lower() in "aeiou" else "a"


def _phone_display(phone: str) -> str:
    """The record's phone, formatted for a letter: bare digit strings
    get standard US grouping (7189140313 → 718-914-0313); anything
    already formatted passes through. Digits never change."""
    text = (phone or "").strip()
    digits = re.sub(r"\D", "", text)
    if text and all(ch.isdigit() or ch in " -." for ch in text):
        if len(digits) == 10:
            return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
        if len(digits) == 11 and digits.startswith("1"):
            return f"+1 {digits[1:4]}-{digits[4:7]}-{digits[7:]}"
    return text


def _end(text: str) -> str:
    """A sentence built around a name that may already end with a
    period ('Berenschot Groep B.V.') must not gain a second one."""
    return text if text.rstrip().endswith((".", "!", "?")) else text + "."


def _join(words: list, last: str = "and") -> str:
    words = [w for w in words if w]
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + f" {last} " + words[-1]


_TONE_WORDS = {
    "warm", "friendly", "professional", "confident", "enthusiastic",
    "personable", "approachable", "upbeat", "energetic", "polished",
    "formal", "casual", "conversational", "direct", "concise",
    "humble", "bold", "serious", "sincere", "courteous", "respectful",
}
_TONE_CONNECTORS = {"and", "&"}


def _tone_like(text: str) -> bool:
    """True when a short highlights value is really a tone/posture
    phrase ('warm and friendly') rather than letter content. The old
    interview stored the tone answer in highlights and left the tone
    field empty, so equality with the tone field is not enough."""
    words = re.findall(r"[a-z][a-z'-]*|&", (text or "").lower())
    if not words or len(words) > 6:
        return False
    return (all(w in _TONE_WORDS or w in _TONE_CONNECTORS for w in words)
            and any(w in _TONE_WORDS for w in words))


def _effective_tone(client: dict) -> str:
    tone = (client.get("cover_letter_tone") or "").strip()
    if tone:
        return tone
    highlights = (client.get("cover_letter_highlights") or "").strip()
    return highlights if _tone_like(highlights) else ""


def _content_highlights(client: dict) -> str:
    """Highlights that are letter content. Tone text sitting in the
    highlights field — equal to the tone, or tone-like with the tone
    field empty — is posture and is never printed."""
    highlights = (client.get("cover_letter_highlights") or "").strip()
    tone = (client.get("cover_letter_tone") or "").strip()
    if highlights and (highlights.rstrip(".").lower()
                       == tone.rstrip(".").lower()
                       or (not tone and _tone_like(highlights))):
        return ""
    return highlights


def template_letter(client: dict, job: dict, fit: dict) -> str:
    name = client.get("name") or "Your Name"
    title = job.get("title") or "the role"
    company = job.get("company") or "your company"
    role = (client.get("current_role") or "").strip()
    skills = [_skill_display(s) for s in
              (fit["matched"] or (client.get("skills") or [])[:5])]
    certs = _certs(client)
    highlights = _content_highlights(client)
    contact = " · ".join(x for x in [client.get("email", ""),
                                     _phone_display(client.get("phone", "")),
                                     client.get("linkedin", "")] if x)
    lines = [f"Dear {company} hiring team,", ""]
    opener = _end(f"I am applying for the {title} position at {company}")
    if role:
        opener += f" I currently work as {_article(role)} {role}."
    lines.append(opener)
    body = ""
    if skills:
        body = (f"My resume covers the skills this posting calls for, including "
                f"{_join(skills[:6])}.")
    if certs:
        if len(certs) == 1:
            cert_sentence = f"I hold the {certs[0]}."
        elif len(certs) == 2:
            cert_sentence = (f"My certifications are the {certs[0]} and "
                             f"the {certs[1]}.")
        else:
            cert_sentence = (f"My certifications include the {certs[0]} and "
                             f"the {certs[1]} — {len(certs)} in total on file.")
        body = f"{body} {cert_sentence}" if body else cert_sentence
    if body:
        lines += ["", body]
    if highlights:
        words = highlights.rstrip(".").split()
        if len(words) <= 6:
            # A short content fragment ('team leadership') is woven
            # into a sentence — never a bare fragment paragraph the
            # way Anthony's live letter printed one (2026-11-24).
            fragment = highlights.rstrip(".")
            fragment = fragment[:1].lower() + fragment[1:]
            lines += ["", f"I bring {_article(fragment)} {fragment} "
                          f"approach to my work."]
        else:
            lines += ["", highlights if highlights.endswith(".")
                      else highlights + "."]
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
    skills = [_skill_display(s) for s in
              (fit["matched"] or (client.get("skills") or [])[:4])]
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
        f"Highlights the applicant wants mentioned: {_content_highlights(client)}\n"
        f"Preferred tone: {_effective_tone(client) or 'professional'}\n"
        f"Contact: {client.get('email', '')} {client.get('phone', '')}\n\n"
        f"Job title: {job.get('title', '')}\n"
        f"Employer: {job.get('company', '')}\n"
        f"Location: {job.get('location', '')}\n"
        f"Posting excerpt: {(job.get('snippet') or '')[:800]}\n"
        f"Skills the posting names that the resume matches: {', '.join(fit['matched'])}\n"
        "Rules: the tone is the letter's overall posture — let it "
        "shape the word choice, warmth and rhythm of the whole letter, "
        "and never print the tone words themselves as a sentence, "
        "fragment or sign-off in the letter. Use the applicant's "
        "current role exactly as given. "
        "Name certifications exactly as listed; if you state a count "
        "of certifications it must equal the number listed, and never "
        "print a date without its year. Present skill names properly "
        "capitalized (API, CI/CD, ChromaDB). Never add a second "
        "period after a name that already ends with one.\n"
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
        f"Highlights the applicant asked to include: {_content_highlights(client)}\n"
        f"Tone on record (the letter's overall posture — it must be FELT, never printed): {_effective_tone(client) or 'professional'}\n"
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
        "from the record (the phone's DIGITS must match; dashes or "
        "spacing alone are not a difference); claiming a skill listed "
        "as NOT on the resume; leftover placeholders or bracketed "
        "text; contradictions; garbled, duplicated or nonsensical "
        "sentences; the tone/style setting printed as text in the "
        "letter (e.g. a standalone fragment like 'Warm and friendly.'); "
        "a certification count that does not match the number of "
        "certifications in the record; a date printed without its "
        "year; a hedged plural like 'certification(s)'; a doubled "
        "period after a name that already ends with one.\n"
        "REGRESSION — the letter falling short of the record: a matched "
        "skill the posting names is omitted; a certification on file is "
        "omitted; the applicant's requested highlights are dropped; the "
        "current role or experience is understated; generic filler where "
        "the record is specific.\n"
        "VIBE — the letter's overall posture must match the tone on "
        "record: word choice, warmth and rhythm throughout should feel "
        "like that tone without ever naming it. If the tone is set "
        "beyond plain 'professional' and the letter's feel clearly "
        "contradicts it (cold and clipped where warm was asked, stiff "
        "where friendly was asked), report it as a [regression] issue: "
        "'the letter's posture does not match the tone on record'. "
        "Printing the tone words as text instead of embodying them is "
        "[stupidity], above.\n\n"
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


def lint_letter(client: dict, job: dict, fit: dict, letter: str) -> list:
    """Deterministic letter checks that run even when no LM rung
    answers — the failure mode behind Anthony's 2026-11-24 letter:
    the LM was rate-limited, so the template shipped and NOTHING
    checked it. Each rule is one defect class from that real letter;
    the fixed template passes all of them."""
    issues = []
    text = letter or ""
    tone = _effective_tone(client).lower().rstrip(".")
    if tone and len(tone.split()) >= 2:
        if tone in text.lower():
            issues.append("the tone setting is printed in the letter")
    elif tone:
        for line in text.splitlines():
            if line.strip().lower().rstrip(".") == tone:
                issues.append("the tone setting is printed as a "
                              "standalone line in the letter")
                break
    if "(s)" in text:
        issues.append("the letter contains a hedged plural '(s)'")
    if ".." in text.replace("...", ""):
        issues.append("the letter contains a doubled period")
    role = (client.get("current_role") or "").strip()
    if role and f" as a {role}" in text and _article(role) == "an":
        issues.append(f"the letter says 'a {role}' — wrong article "
                      f"for the role on record")
    phone_digits = re.sub(r"\D", "", client.get("phone", "") or "")
    if phone_digits:
        letter_phones = [d for d in re.findall(r"[\d][\d\s().-]{8,}\d", text)
                         if len(re.sub(r"\D", "", d)) >= 10]
        if letter_phones and not any(
                re.sub(r"\D", "", d).endswith(phone_digits[-10:])
                for d in letter_phones):
            issues.append("the phone number in the letter does not "
                          "match the record")
    certs = _certs(client)
    count_claim = re.search(r"(\d+)\s+in total on file", text)
    further_claim = re.search(r"along with\s+(\d+)\s+further", text)
    if count_claim and int(count_claim.group(1)) != len(certs):
        issues.append("the letter's certification count does not "
                      "match the record")
    if further_claim and int(further_claim.group(1)) != len(certs) - 1:
        issues.append("the letter's certification count does not "
                      "match the record")
    return issues


def build_pack(client: dict, job: dict) -> dict:
    fit = fit_for(client, job)
    gen = llm.generate(_lm_prompt(client, job, fit))
    if gen["text"]:
        letter, provider = gen["text"], gen["provider"]
    else:
        letter, provider = template_letter(client, job, fit), "template"
    letter, letter_check = check_letter(client, job, fit, letter)
    letter_check["lint_issues"] = lint_letter(client, job, fit, letter)
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


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def email_pack(profile_id: str, job_id: str, to: str, subject: str = "",
               body: str = "", document_id: str = None) -> dict:
    """Send a built pack by email — the shared send path behind both
    the API endpoint (the pack panel's review screen) and the
    concierge (the admin of the structure, acting on the client's
    approval in chat). Callers gate the send on that approval BEFORE
    calling; this function validates, sends, records the send on the
    pack, and moves a still-'saved' job to 'applied'. Errors return
    {"error": ..., "http": <status>} with the real reason."""
    from . import mailer as mailer_mod
    p = profiles_mod.get_profile(profile_id)
    if not p:
        return {"error": "profile not found", "http": 404}
    job = next((j for j in p.get("saved_jobs") or []
                if j.get("id") == job_id), None)
    if not job:
        return {"error": "job not found in this profile's saved jobs",
                "http": 404}
    pack = job.get("apply_pack")
    if not pack:
        return {"error": "build the apply pack first — the email sends "
                         "the pack's cover letter", "http": 400}
    to = (to or "").strip()
    if not _EMAIL_RE.match(to):
        return {"error": f"'{to}' does not look like an email address",
                "http": 400}
    client_name = p["client"].get("name") or "the client"
    subject = (subject or "").strip() or (
        f"Application for {job.get('title', 'the role')} — {client_name}")
    body = (body or "").strip() or pack.get("cover_letter", "")
    if not body:
        return {"error": "the email body is empty", "http": 400}
    attachment = None
    if document_id:
        info = profiles_mod.document_file(profile_id, document_id)
        if "error" in info:
            return {"error": info["error"], "http": 400}
        attachment = {"filename": info["filename"],
                      "data": info["path"].read_bytes()}
    st = mailer_mod.status()
    if not st["configured"]:
        return {"error": "email is not configured — missing "
                         + ", ".join(st["missing"]) + " in .env",
                "http": 400}
    try:
        record = mailer_mod.send(to, subject, body, attachment)
    except RuntimeError as exc:
        return {"error": f"email failed: {exc}", "http": 502}
    profiles = profiles_mod._load()
    stored_p = profiles.get(profile_id)
    stored = next((j for j in (stored_p or {}).get("saved_jobs") or []
                   if j.get("id") == job_id), None)
    if stored is not None and stored.get("apply_pack") is not None:
        stored["apply_pack"]["emailed"] = record
        profiles_mod._save(profiles)
    job_status = (stored or {}).get("application_status") or "saved"
    if job_status == "saved":
        from . import agents as agents_mod
        res = agents_mod.set_application_status(
            profile_id, job_id, "applied",
            note=f"Application emailed to {to} from PocketProWS "
                 f"after the client's approval.")
        if "job" in res:
            job_status = "applied"
    return {"emailed": record, "job_status": job_status}
