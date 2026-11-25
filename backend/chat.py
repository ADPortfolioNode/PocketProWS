"""Concierge recruiter — friendly, helpful, profile-scoped.

Terminology (Anthony, 2026-11-07): the CLIENT is the job seeker — the
client seeks work; the EMPLOYER is the company posting the job — the
employer hires. Job results always name the employer as the hiring side.

Retrieved-text at the core, with an LM layer on top (Anthony,
2026-11-22): when an LM rung is configured (backend/llm.py — Gemini
first), Q&A answers are composed by the LM from the retrieved
material only; when no rung answers, the answer falls back to the
quoted material and says why. The concierge also greets first in an
empty conversation (profiles.ensure_greeting). Two modes:
- "interview": one question at a time; each answer is saved into that
  profile's resource and confirmed briefly. The interview establishes WHO
  the client is first (name), before any job preferences.
- general chat: answers from the ACTIVE PROFILE's own documents and
  interview answers (Chroma, filtered by profile_id) plus saved jobs that
  match. Without a profile selected, it answers from saved jobs only and
  says so — it never mixes one profile's data into another's answers.

The concierge is the ADMIN of the structure (Anthony, 2026-11-23):
the workflow agents report to it, the client directs it, and
client-approved actions run through it — including emailing a
finished apply pack: the concierge prepares the send, shows the
exact message, and sends only on the client's approval in the
conversation ("send it"), recording the send on the pack.

Helpful and verbose, for transparency (Anthony, 2026-11-22): the
concierge teaches the workflow while it works it — a guide intent
("explain my workflow", "what do I do next") returns the full
walkthrough marked with the client's position; status answers are
narrated briefings (what the step is, what the numbers mean, the next
best step); Q&A answers close with a "How I answered" line naming what
was searched; and every interview question carries why it is asked.
"""
import re

from . import llm as llm_mod
from . import profiles as profiles_mod
from .vector_store import search_jobs_text, search_profile_text

# Status routing: short words match as whole words only, so "update my
# resume" does NOT route to status ("update" is not a status word at all).
STATUS_PHRASES = ("how are we doing", "how is it going", "follow-up",
                  "follow up", "followup", "where are we",
                  "what's happening", "whats happening")
STATUS_WORDS = ("status", "progress", "pipeline")


def _is_status_question(q: str) -> bool:
    lower = q.lower()
    if any(p in lower for p in STATUS_PHRASES):
        return True
    return any(re.search(rf"\b{re.escape(w)}\b", lower) for w in STATUS_WORDS)


# Guide routing (Anthony, 2026-11-22): the concierge teaches the
# workflow — "explain my workflow", "what do I do next", "how does
# this work" get the full walkthrough, marked with where this client
# stands in it.
GUIDE_PHRASES = ("explain my workflow", "explain the workflow", "explain your workflow",
                 "how does this work", "how does it work", "how this works",
                 "what do i do next", "what should i do next", "what's next for me",
                 "whats next", "walk me through", "guide me", "help me understand",
                 "explain the process", "explain my process")


def _is_guide_question(q: str) -> bool:
    lower = q.lower().strip()
    if lower in ("help", "help me", "?"):
        return True
    return any(p in lower for p in GUIDE_PHRASES)


STEP_GUIDE = [
    ("documents", "Documents — the resume goes in first. I read it and pull out the skills, certifications, education and contact details. Everything later — matching, the disqualifier filter, cover letters — is built from what the resume says, so this step is the foundation."),
    ("interview", "Interview — twelve short questions, one at a time, in the Concierge panel. They turn the resume into a person: target roles, current role, work history, where they're based, remote or on-site, full-time or contract, salary aim, and what cover letters should highlight, plus the tone they should take. Skills are never typed here — they're confirmed from the resume."),
    ("preferences", "Preferences — the interview answers become the search settings. Every search from here on runs on what this client actually wants, not generic keywords."),
    ("job_search", "Job search — six boards (Adzuna, Jooble, USAJOBS, Remotive, RemoteOK, Arbeitnow) searched with those preferences. Postings whose stated requirements would disqualify the client — a degree above theirs, a certification they don't hold, a required clearance — are omitted and reported with reasons. The rest are saved to the profile."),
    ("applications", "Applications — every saved job can get an apply pack: a fit check against the resume, a cover letter written for that employer, and draft answers to the standard questions. You review everything and submit it yourself — or tell me to email the pack: I'll show you the exact message first and send only when you approve it here — nothing is ever sent automatically. Statuses move saved → applied → interviewing → offer → hired as things progress."),
    ("follow_up", "Follow-up — an application that goes quiet gets a follow-up draft before it goes cold. I flag what's due and have the note written; you send it."),
]


def _guide_answer(profile_id: str = "") -> str:
    done, current = set(), ""
    who = ""
    if profile_id:
        profile = profiles_mod.get_profile(profile_id)
        if profile:
            who = profile["client"].get("name") or ""
            ws = profiles_mod.workflow_state(profile)
            current = ws["current_step"]
            done = {s["step"] for s in ws["steps"] if s["done"]}
    head = (f"Here's the workflow{' for ' + who if who else ''}, step by step — "
            f"and where things stand:")
    lines = [head]
    for i, (key, text) in enumerate(STEP_GUIDE, 1):
        if key in done:
            mark = "✓ done"
        elif key == current:
            mark = "→ you are here"
        else:
            mark = "upcoming"
        lines.append(f"{i}. [{mark}] {text}")
    if current:
        nxt = next((t for k, t in STEP_GUIDE if k == current), "")
        lines.append(f"Your next move is the step marked → — {nxt.split('—')[0].strip().lower()} is where the work is right now. "
                     "Ask me 'how are we doing' anytime for live numbers, or just ask about a role and I'll search what's saved.")
    else:
        lines.append("Create a client profile to start — the workflow above lights up step by step as you go.")
    return "\n".join(lines)


def _effective_query(q: str, history) -> str:
    """Follow-ups lean on the conversation: a short question ("and
    remote?", "what about Texas?") is searched together with the
    previous user message, so it matches what the user means instead
    of matching almost nothing."""
    words = q.split()
    if history and (len(words) <= 3 or q.lower().startswith(("and ", "what about"))):
        prev = [m for m in history if m.get("role") == "user"]
        if prev:
            return prev[-1]["text"] + " " + q
    return q


def answer(question: str, profile_id: str = "", mode: str = "") -> dict:
    """One concierge turn. With a profile, the turn is recorded in that
    profile's conversation (the interview flow keeps its own panel and
    is not recorded), and the response carries the updated history so
    the UI renders the transcript from one source of truth."""
    history = profiles_mod.get_chat(profile_id) if profile_id else None
    res = _answer_once((question or "").strip(), profile_id, mode, history or [])
    if profile_id and history is not None and mode != "interview" and (question or "").strip():
        profiles_mod.append_chat(profile_id, "user", (question or "").strip())
        updated = profiles_mod.append_chat(profile_id, "assistant", res["answer"])
        if updated is not None:
            res["history"] = updated
    return res


_APPROVE_WORDS = {"send it", "send", "approve", "approved", "yes",
                  "yes send it", "send now", "go ahead", "confirm"}
_CANCEL_WORDS = {"cancel", "don't send", "dont send", "no",
                 "never mind", "nevermind", "stop", "cancel it"}


def _review_text(pending: dict, profile: dict) -> str:
    job = next((j for j in profile.get("saved_jobs") or []
                if j.get("id") == pending.get("job_id")), {})
    docs = profile.get("documents") or []
    attach = next((d for d in docs if d["id"] == pending.get("document_id")),
                  None)
    attach_name = (attach or {}).get("filename") or "none"
    return (f"Ready to email the application for {job.get('title', '')} "
            f"at {job.get('company', '')}:\n"
            f"To: {pending.get('to')}\n"
            f"Subject: {pending.get('subject')}\n"
            f"Attachment: {attach_name}\n"
            "The body is the pack's cover letter, exactly as built. "
            "Reply 'send it' to approve this send — or 'cancel', and "
            "nothing is sent.")


def _email_turn(q: str, profile_id: str):
    """The concierge administering an email send, or None when the
    message is not about email. A prepared send waits on the profile
    (pending_email) and holds the floor until the client approves it
    ('send it') or cancels — the same approval rule as the pack
    panel's review screen, in the conversation."""
    from . import apply_pack as pack_mod
    from . import mailer as mailer_mod
    profile = profiles_mod.get_profile(profile_id)
    if not profile:
        return None
    lower = q.lower().strip()
    pending = profiles_mod.get_pending_email(profile_id)
    if pending:
        if lower in _CANCEL_WORDS or lower.startswith("cancel"):
            profiles_mod.set_pending_email(profile_id, None)
            return {"answer": "Cancelled — nothing was sent. The pack "
                              "stays on the job whenever you're ready.",
                    "jobs": [], "mode": "email"}
        if pending.get("stage") == "approve":
            if lower in _APPROVE_WORDS:
                res = pack_mod.email_pack(
                    profile_id, pending["job_id"], pending.get("to") or "",
                    pending.get("subject", ""), "",
                    pending.get("document_id"))
                profiles_mod.set_pending_email(profile_id, None)
                if "error" in res:
                    return {"answer": f"Not sent: {res['error']}",
                            "jobs": [], "mode": "email"}
                rec = res["emailed"]
                return {"answer": f"Sent — the application was emailed "
                                  f"to {rec['to']} from {rec['from']}, "
                                  f"and the job is now marked Applied. "
                                  f"The send is recorded on the pack.",
                        "jobs": [], "mode": "email"}
            return {"answer": "A send is waiting for your word:\n"
                              + _review_text(pending, profile),
                    "jobs": [], "mode": "email"}
        if pending.get("stage") == "address":
            addr = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", q)
            if not addr:
                return {"answer": "What email address should I send it "
                                  "to? Reply with the address — or "
                                  "'cancel'.",
                        "jobs": [], "mode": "email"}
            pending = {**pending, "to": addr.group(0), "stage": "approve"}
            profiles_mod.set_pending_email(profile_id, pending)
            return {"answer": _review_text(pending, profile),
                    "jobs": [], "mode": "email"}
        if pending.get("stage") == "job":
            cands = pending.get("candidates") or []
            pick = None
            if lower.isdigit() and 1 <= int(lower) <= len(cands):
                pick = cands[int(lower) - 1]
            else:
                pick = next((c for c in cands
                             if c["title"].lower() in lower
                             or lower in c["title"].lower()), None)
            if not pick:
                listing = "\n".join(
                    f"{i}. {c['title']} at {c['company']}"
                    for i, c in enumerate(cands, 1))
                return {"answer": f"Which one? Reply with the number:\n{listing}",
                        "jobs": [], "mode": "email"}
            client_name = profile["client"].get("name") or "the client"
            pending = {"job_id": pick["id"], "to": pending.get("to"),
                       "stage": "approve" if pending.get("to") else "address",
                       "subject": f"Application for {pick['title']} — {client_name}",
                       "document_id": pending.get("document_id")}
            profiles_mod.set_pending_email(profile_id, pending)
            if pending["stage"] == "address":
                return {"answer": f"{pick['title']} at {pick['company']} "
                                  f"— what email address should I send "
                                  f"it to?",
                        "jobs": [], "mode": "email"}
            fresh = profiles_mod.get_profile(profile_id) or profile
            return {"answer": _review_text(pending, fresh),
                    "jobs": [], "mode": "email"}
    addr = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", q)
    wants_email = (("email" in lower
                    and ("application" in lower or "pack" in lower
                         or addr is not None))
                   or ("send" in lower
                       and ("application" in lower or "pack" in lower)))
    if not wants_email:
        return None
    st = mailer_mod.status()
    if not st["configured"]:
        return {"answer": "I can't email yet — email isn't configured. "
                          "Add " + ", ".join(st["missing"])
                          + " to the app's .env and restart, and I'll "
                            "send packs from here, on your approval.",
                "jobs": [], "mode": "email"}
    cands = [j for j in profile.get("saved_jobs") or [] if j.get("apply_pack")]
    if not cands:
        return {"answer": "There's no apply pack ready to email yet. "
                          "Build one first — Agents panel, open a saved "
                          "job, Apply pack — then tell me to email it.",
                "jobs": [], "mode": "email"}
    docs = profile.get("documents") or []
    doc_id = docs[0]["id"] if docs else None
    named = next((c for c in cands if c.get("title", "").lower() in lower),
                 None)
    if len(cands) > 1 and named is None:
        listing = "\n".join(f"{i}. {c.get('title', '')} at {c.get('company', '')}"
                            for i, c in enumerate(cands, 1))
        profiles_mod.set_pending_email(profile_id, {
            "stage": "job", "to": addr.group(0) if addr else None,
            "candidates": [{"id": c["id"], "title": c.get("title", ""),
                            "company": c.get("company", "")} for c in cands],
            "document_id": doc_id})
        return {"answer": f"More than one pack is ready. Which "
                          f"application should I email?\n{listing}",
                "jobs": [], "mode": "email"}
    job = named or cands[0]
    client_name = profile["client"].get("name") or "the client"
    pending = {"stage": "approve" if addr else "address",
               "job_id": job["id"],
               "to": addr.group(0) if addr else None,
               "subject": f"Application for {job.get('title', 'the role')} — {client_name}",
               "document_id": doc_id}
    profiles_mod.set_pending_email(profile_id, pending)
    if not addr:
        return {"answer": f"The pack for {job.get('title', '')} at "
                          f"{job.get('company', '')} is ready. What "
                          f"email address should I send it to?",
                "jobs": [], "mode": "email"}
    return {"answer": _review_text(pending, profile),
            "jobs": [], "mode": "email"}


def _answer_once(q: str, profile_id: str = "", mode: str = "", history=None) -> dict:
    # The concierge is the admin: an email it prepared (or a new email
    # request) is handled before anything else in the turn.
    if profile_id and q and mode != "interview":
        email_res = _email_turn(q, profile_id)
        if email_res is not None:
            return email_res
    # Status questions go to the workflow agents' live status — real
    # numbers for the active profile, no LLM key needed.
    if profile_id and q and _is_status_question(q):
        from . import agents as agents_mod
        st = agents_mod.profile_status(profile_id)
        if "error" not in st:
            return {"answer": agents_mod.status_summary_text(st),
                    "jobs": [], "mode": "status", "status": st}
    if q and _is_guide_question(q) and mode != "interview":
        return {"answer": _guide_answer(profile_id), "jobs": [], "mode": "guide"}
    if mode == "interview" and profile_id:
        profile = profiles_mod.get_profile(profile_id)
        if not profile:
            return {"answer": "I don't have that profile on file — create it first, then we'll start the interview.",
                    "jobs": [], "mode": "interview", "interview": {"error": "profile not found"}}
        if not q:
            st = profiles_mod.interview_status(profile)
            text = st["next_question"] or "Interview complete!"
            if st.get("why"):
                text += f"\n(Why I ask: {st['why']})"
            return {"answer": text,
                    "jobs": [], "mode": "interview", "interview": st}
        res = profiles_mod.answer_interview(profile_id, q)
        if res.get("error"):
            return {"answer": res["error"] + " — please answer the question.",
                    "jobs": [], "mode": "interview",
                    "interview": {"error": res["error"],
                                  "next_question": res.get("next_question"),
                                  "step": res.get("step"), "total": res.get("total")}}
        if res.get("complete"):
            text = (f"All done — thank you! {res['saved']} Here's what I have for you: {res['summary']} "
                    "From here the workflow moves to Preferences and Job search — ask me "
                    "'explain my workflow' and I'll show you the whole map.")
        else:
            text = f"{res['saved']} Next question: {res['next_question']}"
            fresh = profiles_mod.get_profile(profile_id) or profile
            why = profiles_mod.interview_status(fresh).get("why", "")
            if why:
                text += f"\n(Why I ask: {why})"
        fresh = profiles_mod.get_profile(profile_id) or profile
        return {"answer": text, "jobs": [], "mode": "interview",
                "interview": {"complete": res["complete"], "step": res.get("step"),
                              "total": res.get("total"),
                              "next_question": res.get("next_question"),
                              "why": profiles_mod.interview_status(fresh).get("why", ""),
                              "summary": res.get("summary")}}
    if not q:
        return {"answer": ("Ask me about a role, a skill, or a location — for example, 'remote Python jobs'. "
                           "Or ask 'how are we doing' for a full status briefing, or 'explain my workflow' "
                           "and I'll walk you through how all of this works, step by step."),
                "jobs": [], "mode": "fallback"}
    effective = _effective_query(q, history or [])
    found = search_jobs_text(effective, n=5)
    client_bits = []
    who = ""
    if profile_id:
        profile = profiles_mod.get_profile(profile_id)
        if profile:
            who = profile["client"].get("name") or profile_id
            client_bits = search_profile_text(profile_id, effective, n=5)
    if not found and not client_bits:
        hint = (f" for {who}" if who else "")
        if llm_mod.status()["providers"]:
            lm_note = ("An LM is configured, but it composes only from saved material "
                       "too — with nothing saved on this topic, there is nothing "
                       "to compose from.")
        else:
            lm_note = ("No LLM key is configured, so I'm answering from saved "
                       "material only — nothing is invented.")
        return {
            "answer": ("I don't have any saved jobs or client notes matching that yet"
                       f"{hint}. Here's how this works: I can only answer from material "
                       "that's been saved to this profile — the resume and documents under "
                       "Documents, the interview answers, and jobs a search has saved. "
                       "Run a job search first (Adzuna, Jooble, USAJOBS, Remotive, RemoteOK "
                       "or Arbeitnow), or add a document / answer an interview question, and "
                       f"I'll match against it. {lm_note}"),
            "jobs": [], "mode": "fallback",
        }
    searched = []
    if profile_id:
        searched.append(f"{len(client_bits)} passage(s) from {who}'s documents and interview notes")
    searched.append(f"{len(found)} saved job(s)")
    searched_str = " and ".join(searched)
    # The LM layer (Anthony, 2026-11-22): when a rung is configured it
    # composes the answer from the retrieved material — grounded in
    # it, nothing beyond it. When no rung answers, the answer falls
    # back to the quoted material, and says why.
    gen = llm_mod.generate(_qa_prompt(q, who, client_bits, found))
    if gen["text"]:
        how = (f"How I answered: {gen['provider']} composed this from {searched_str} "
               f"for '{effective}' — grounded only in that saved material, nothing "
               "beyond it. Ask 'explain my workflow' anytime for the full picture.")
        return {"answer": gen["text"] + "\n\n" + how,
                "jobs": found, "mode": "llm", "provider": gen["provider"],
                "client_notes": client_bits}
    lines = []
    if client_bits:
        lines.append(f"From client {who}'s own notes and documents:")
        lines += [f"- {b['text'][:220]}" for b in client_bits]
    if found:
        lines.append("Closest saved jobs (employer = the company hiring):")
        lines += [f"- {j.get('title','')} — employer {j.get('company','')} ({j.get('location','')}) — {j.get('url','')}"
                  for j in found]
    who_line = f" for client {who}" if who else ""
    configured = llm_mod.status()["providers"]
    if configured:
        first_err = next(iter(gen["errors"].values()), "unavailable")
        how = (f"How I answered: I searched {searched_str} for '{effective}'. "
               f"The LM ({', '.join(configured)}) didn't answer just now — "
               f"{first_err} — so this is the saved material itself, quoted — "
               "nothing added. Ask 'explain my workflow' anytime for the full picture.")
    else:
        how = (f"How I answered: I searched {searched_str} for '{effective}'. "
               "No LLM key is configured, so this is the saved material itself, quoted — "
               "nothing added. Ask 'explain my workflow' anytime for the full picture.")
    lines.append("")
    lines.append(how)
    return {"answer": f"Here's what I found{who_line} for '{q}':\n" + "\n".join(lines),
            "jobs": found, "mode": "fallback",
            "client_notes": client_bits}


def _qa_prompt(q: str, who: str, client_bits, found) -> str:
    """Facts-only composition prompt: the LM writes the answer from
    the retrieved passages and saved jobs, and from nothing else."""
    notes = "\n".join(f"- {b['text'][:600]}" for b in client_bits) or "(none)"
    jobs = "\n".join(
        f"- {j.get('title','')} — employer {j.get('company','')} ({j.get('location','')}) — {j.get('url','')}"
        for j in found) or "(none)"
    return (
        "You are the PocketProWS concierge recruiter. Answer the user's "
        "question using ONLY the saved material below — the client's own "
        "documents and notes, and their saved jobs. Do not invent employers, "
        "salaries, dates or facts that are not in the material. If the "
        "material only partly answers, say what it covers and what it does "
        "not. Be helpful, warm and clear. The client is the job seeker; the "
        "employer is the company hiring.\n\n"
        f"Question: {q}\n\nClient ({who or 'no profile selected'}):\n{notes}\n\n"
        f"Saved jobs:\n{jobs}")
