"""Concierge recruiter — friendly, helpful, profile-scoped.

Terminology (Anthony, 2026-11-07): the CLIENT is the job seeker — the
client seeks work; the EMPLOYER is the company posting the job — the
employer hires. Job results always name the employer as the hiring side.

Keyless retrieved-text fallback (PocketPro pattern). Two modes:
- "interview": one question at a time; each answer is saved into that
  profile's resource and confirmed briefly. The interview establishes WHO
  the client is first (name), before any job preferences.
- general chat: answers from the ACTIVE PROFILE's own documents and
  interview answers (Chroma, filtered by profile_id) plus saved jobs that
  match. Without a profile selected, it answers from saved jobs only and
  says so — it never mixes one profile's data into another's answers.
"""
from . import profiles as profiles_mod
from .vector_store import search_jobs_text, search_profile_text

STATUS_WORDS = ("status", "how are we doing", "how is it going", "progress",
                "update", "follow-up", "follow up", "followup", "pipeline",
                "where are we", "what's happening", "whats happening")


def answer(question: str, profile_id: str = "", mode: str = "") -> dict:
    q = (question or "").strip()
    # Status questions go to the workflow agents' live status — real
    # numbers for the active profile, no LLM key needed.
    if profile_id and q and any(w in q.lower() for w in STATUS_WORDS):
        from . import agents as agents_mod
        st = agents_mod.profile_status(profile_id)
        if "error" not in st:
            return {"answer": agents_mod.status_summary_text(st),
                    "jobs": [], "mode": "status", "status": st}
    if mode == "interview" and profile_id:
        profile = profiles_mod.get_profile(profile_id)
        if not profile:
            return {"answer": "I don't have that profile on file — create it first, then we'll start the interview.",
                    "jobs": [], "mode": "interview", "interview": {"error": "profile not found"}}
        if not q:
            st = profiles_mod.interview_status(profile)
            return {"answer": st["next_question"] or "Interview complete!",
                    "jobs": [], "mode": "interview", "interview": st}
        res = profiles_mod.answer_interview(profile_id, q)
        if res.get("complete"):
            text = f"All done — thank you! {res['saved']} Here's what I have for you: {res['summary']}"
        else:
            text = f"{res['saved']} Next question: {res['next_question']}"
        return {"answer": text, "jobs": [], "mode": "interview",
                "interview": {"complete": res["complete"], "step": res.get("step"),
                              "total": res.get("total"),
                              "next_question": res.get("next_question"),
                              "summary": res.get("summary")}}
    if not q:
        return {"answer": "Ask me about a role, a skill, or a location — for example, 'remote Python jobs'.",
                "jobs": [], "mode": "fallback"}
    found = search_jobs_text(q, n=5)
    client_bits = []
    who = ""
    if profile_id:
        profile = profiles_mod.get_profile(profile_id)
        if profile:
            who = profile["client"].get("name") or profile_id
            client_bits = search_profile_text(profile_id, q, n=5)
    if not found and not client_bits:
        hint = (f" for {who}" if who else "")
        return {
            "answer": ("I don't have any saved jobs or client notes matching that yet"
                       f"{hint}. Run a job search first (Adzuna, Jooble, USAJOBS, "
                       "Remotive, RemoteOK or Arbeitnow), or add a document / answer "
                       "an interview question, and I'll match against it. "
                       "No LLM key is configured, so I'm answering from saved material only."),
            "jobs": [], "mode": "fallback",
        }
    lines = []
    if client_bits:
        lines.append(f"From client {who}'s own notes and documents:")
        lines += [f"- {b['text'][:220]}" for b in client_bits]
    if found:
        lines.append("Closest saved jobs (employer = the company hiring):")
        lines += [f"- {j.get('title','')} — employer {j.get('company','')} ({j.get('location','')}) — {j.get('url','')}"
                  for j in found]
    who_line = f" for client {who}" if who else ""
    return {"answer": f"Here's what I found{who_line} for '{q}':\n" + "\n".join(lines),
            "jobs": found, "mode": "fallback",
            "client_notes": client_bits}
