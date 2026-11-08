"""Workflow agents for PocketProWS.

Anthony (2026-11-08): "Set agents to operate the workflows and report to
concierge status for user resources etc."

What this module does: four small agents that OPERATE the per-profile
workflow (which was previously manual "mark done" steps) and report their
status, so the concierge can answer "what's the status?" from real data.

- SearchAgent: runs a profile's job search across the free sources using
  the profile's own target roles / location / remote preference, de-dupes
  against that profile's saved jobs, and saves new matches to the profile.
- ApplicationAgent: tracks each saved job's application status
  (saved -> applied -> interviewing -> offer -> hired, or rejected at any
  point), with dates and notes. It NEVER submits an application to an
  employer site itself — applying stays external / human. This agent only
  records what happened.
- FollowUpAgent: lists jobs needing follow-up (applied/interviewing with
  no status change for N days, default 7) and drafts a follow-up note per
  job for the recruiter to send.
- ResourceAgent: checks the profile's resources/documents — what exists,
  what was digested (skills / certs / education), and whether each
  document's RAG entry is present or missing/stale.

Per-profile isolation is mandatory: every agent only ever touches its own
profile's jobs / documents / RAG. One client per profile, as everywhere
else in this app.

Triggering: on demand via the API (POST /api/profiles/{id}/agents/run).
There is NO background cron / daemon in this change — that is a follow-up
option if Anthony wants the agents to run on a schedule.

Every agent run is recorded on the profile (agent_runs, latest first) and
summarised by profile_status(), which the concierge and the frontend
Agents view both read. Status answers need no LLM key.
"""
from datetime import datetime, timezone

from . import profiles as profiles_mod
from . import vector_store as vs
from .connectors.base import SearchResult

APPLICATION_STATUSES = ["saved", "applied", "interviewing", "offer",
                        "hired", "rejected"]

# Valid moves. hired / rejected are terminal — nothing moves out of them.
VALID_TRANSITIONS = {
    "saved": {"applied", "rejected"},
    "applied": {"interviewing", "rejected"},
    "interviewing": {"offer", "rejected"},
    "offer": {"hired", "rejected"},
    "hired": set(),
    "rejected": set(),
}

DEFAULT_FOLLOW_UP_DAYS = 7
MAX_AGENT_RUNS_KEPT = 20


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _job_status(job: dict) -> str:
    return job.get("application_status") or "saved"


def _ensure_job_status(job: dict) -> dict:
    """Give a saved job its application-tracking fields if it lacks them
    (jobs saved before agents existed have none)."""
    job.setdefault("application_status", "saved")
    job.setdefault("status_history", [])
    job.setdefault("last_status_at", None)
    job.setdefault("follow_up_draft", "")
    return job


def _record_run(profile_id: str, report: dict) -> dict:
    """Persist an agent run on the profile (latest first, capped)."""
    profiles = profiles_mod._load()
    p = profiles.get(profile_id)
    if not p:
        return report
    runs = p.setdefault("agent_runs", [])
    runs.insert(0, report)
    p["agent_runs"] = runs[:MAX_AGENT_RUNS_KEPT]
    profiles_mod._save(profiles)
    return report


def _free_connectors():
    """The six free sources, same set as main.FREE_CONNECTORS. Imported
    lazily here so agents.py never imports main (no import cycle)."""
    from .connectors.adzuna import AdzunaConnector
    from .connectors.arbeitnow import ArbeitnowConnector
    from .connectors.jooble import JoobleConnector
    from .connectors.remoteok import RemoteOKConnector
    from .connectors.remotive import RemotiveConnector
    from .connectors.usajobs import USAJobsConnector
    return [AdzunaConnector(), JoobleConnector(), USAJobsConnector(),
            RemotiveConnector(), RemoteOKConnector(), ArbeitnowConnector()]


# ------------------------------------------------------------ search agent
def run_search_agent(profile_id: str, connectors=None, limit: int = 5) -> dict:
    """Search for this profile's client, de-dupe, save new matches."""
    profile = profiles_mod.get_profile(profile_id)
    if not profile:
        return {"agent": "search", "ran_at": _now_iso(), "profile_id": profile_id,
                "error": "profile not found"}
    client = profile["client"]
    roles = list(client.get("target_roles") or [])
    if not roles:
        report = {"agent": "search", "ran_at": _now_iso(), "profile_id": profile_id,
                  "summary": "No target roles set for this client yet — finish the "
                             "interview first, then I can search for them.",
                  "counts": {}, "new_jobs": 0, "total_found": 0}
        return _record_run(profile_id, report)
    query = roles[0]
    location = client.get("location") or ""
    connectors = connectors if connectors is not None else _free_connectors()
    counts, total, new_jobs = {}, 0, []
    profiles = profiles_mod._load()
    p = profiles.get(profile_id)
    seen = {j["id"] for j in p["saved_jobs"]}
    for c in connectors:
        try:
            r = c.search(query, location, limit)
        except Exception as exc:  # noqa: BLE001 - one bad source must not kill the run
            r = SearchResult(source=c.name, status="error", jobs=[],
                             message=str(exc))
        counts[c.name] = {"status": r.status, "found": len(r.jobs),
                          "message": r.message}
        total += len(r.jobs)
        for job in r.jobs:
            job = job.as_dict() if hasattr(job, "as_dict") else dict(job)
            if job["id"] not in seen:
                _ensure_job_status(job)
                p["saved_jobs"].append(job)
                new_jobs.append(job)
                seen.add(job["id"])
    if new_jobs:
        vs.upsert_jobs(new_jobs)
    profiles_mod._save(profiles)
    ok = [n for n, c in counts.items() if c["status"] == "ok"]
    report = {"agent": "search", "ran_at": _now_iso(), "profile_id": profile_id,
              "query": query, "location": location,
              "summary": (f"Searched '{query}' across {len(connectors)} sources: "
                          f"{total} jobs found, {len(new_jobs)} new saved "
                          f"for {client.get('name') or profile_id}. "
                          f"Working sources: {', '.join(ok) or 'none'}."),
              "counts": counts, "new_jobs": len(new_jobs), "total_found": total,
              "new_job_titles": [j.get("title", "") for j in new_jobs]}
    return _record_run(profile_id, report)


# ------------------------------------------------------- application agent
def set_application_status(profile_id: str, job_id: str, status: str,
                           note: str = "") -> dict:
    """Move one saved job to a new application status. Returns the updated
    job, or {"error": ...} for a bad profile / job / transition."""
    if status not in APPLICATION_STATUSES:
        return {"error": f"unknown status '{status}'; use one of {APPLICATION_STATUSES}"}
    profiles = profiles_mod._load()
    p = profiles.get(profile_id)
    if not p:
        return {"error": "profile not found"}
    job = next((j for j in p["saved_jobs"] if j.get("id") == job_id), None)
    if not job:
        return {"error": "job not found in this profile's saved jobs"}
    _ensure_job_status(job)
    current = _job_status(job)
    if status != current and status not in VALID_TRANSITIONS.get(current, set()):
        return {"error": (f"cannot move a job from '{current}' to '{status}'; "
                          f"valid next steps from '{current}': "
                          f"{sorted(VALID_TRANSITIONS.get(current, set())) or 'none — terminal'}")}
    now = _now_iso()
    job["application_status"] = status
    job["last_status_at"] = now
    job["status_history"].append({"status": status, "at": now, "note": note or ""})
    if status == "applied" and not job.get("applied_at"):
        job["applied_at"] = now
    profiles_mod._save(profiles)
    return {"job": job,
            "pipeline": application_pipeline(p),
            "note": "Recorded only — no application was submitted to the employer by this app."}


def application_pipeline(profile: dict) -> dict:
    counts = {s: 0 for s in APPLICATION_STATUSES}
    for job in profile.get("saved_jobs") or []:
        counts[_job_status(job)] += 1
    return {"counts": counts, "total": len(profile.get("saved_jobs") or [])}


# ---------------------------------------------------------- follow-up agent
def follow_up_due(profile: dict, days: int = DEFAULT_FOLLOW_UP_DAYS,
                  now=None) -> list:
    """Jobs in applied / interviewing whose status has not changed for
    `days` days. Jobs with no recorded status date are not listed as due —
    they need a date first, not a chase."""
    now = now or datetime.now(timezone.utc)
    due = []
    for job in profile.get("saved_jobs") or []:
        if _job_status(job) not in ("applied", "interviewing"):
            continue
        last = _parse_iso(job.get("last_status_at") or job.get("applied_at") or "")
        if last is None:
            continue
        if (now - last).days >= days:
            due.append(job)
    return due


def _draft_follow_up(profile: dict, job: dict) -> str:
    client = (profile["client"].get("name") or "our client")
    return (f"Hi, following up on {client}'s application for "
            f"{job.get('title', 'the role')} at {job.get('company', 'the employer')} "
            f"(applied {job.get('applied_at', '')[:10] or 'recently'}). "
            f"Is there any update on next steps? Happy to share anything else "
            f"you need. — PocketProWS, for {client}")


def run_follow_up_agent(profile_id: str, days: int = DEFAULT_FOLLOW_UP_DAYS) -> dict:
    profiles = profiles_mod._load()
    p = profiles.get(profile_id)
    if not p:
        return {"agent": "follow_up", "ran_at": _now_iso(), "profile_id": profile_id,
                "error": "profile not found"}
    due = follow_up_due(p, days=days)
    for job in due:
        _ensure_job_status(job)
        job["follow_up_draft"] = _draft_follow_up(p, job)
    profiles_mod._save(profiles)
    report = {"agent": "follow_up", "ran_at": _now_iso(), "profile_id": profile_id,
              "follow_up_days": days,
              "summary": (f"{len(due)} job(s) need a follow-up "
                          f"(no status change in {days}+ days)."
                          if due else
                          f"No follow-ups due — nothing has sat in applied / "
                          f"interviewing for {days}+ days."),
              "due": [{"job_id": j["id"], "title": j.get("title", ""),
                       "company": j.get("company", ""),
                       "status": _job_status(j),
                       "last_status_at": j.get("last_status_at"),
                       "draft": j.get("follow_up_draft", "")} for j in due]}
    return _record_run(profile_id, report)


# ----------------------------------------------------------- resource agent
def run_resource_agent(profile_id: str) -> dict:
    """Check this profile's documents: exists, digested, RAG entry present."""
    profile = profiles_mod.get_profile(profile_id)
    if not profile:
        return {"agent": "resource", "ran_at": _now_iso(), "profile_id": profile_id,
                "error": "profile not found"}
    docs = profile.get("documents") or []
    checked = []
    for doc in docs:
        chunks = vs.count_profile_chunks(profile_id, doc["id"])
        digest = doc.get("digest") or {}
        problems = []
        if not doc.get("text_chars"):
            problems.append("no text extracted")
        if not digest.get("skills") and not digest.get("email"):
            problems.append("nothing digested (no skills or contact found)")
        if chunks == 0 and doc.get("text_chars"):
            problems.append("missing from RAG store (stale — re-upload to re-index)")
        checked.append({"doc_id": doc["id"], "title": doc.get("title", doc.get("filename", "")),
                        "text_chars": doc.get("text_chars", 0),
                        "skills": digest.get("skills") or [],
                        "certifications": digest.get("certifications") or [],
                        "education": digest.get("education") or [],
                        "rag_chunks": chunks,
                        "status": "ok" if not problems else "needs attention",
                        "problems": problems})
    interview_notes = vs.count_profile_chunks(profile_id, None, kind="interview")
    ok = sum(1 for d in checked if d["status"] == "ok")
    report = {"agent": "resource", "ran_at": _now_iso(), "profile_id": profile_id,
              "summary": (f"{len(docs)} document(s) on file, {ok} healthy; "
                          f"{interview_notes} interview note(s) in RAG."
                          if docs else
                          "No documents on file for this profile yet — add a resume or work history to build their resource."),
              "documents": checked,
              "document_count": len(docs),
              "healthy_count": ok,
              "interview_notes_in_rag": interview_notes}
    return _record_run(profile_id, report)


# ------------------------------------------------------------- run + status
def run_agents(profile_id: str, agents=None, follow_up_days: int = DEFAULT_FOLLOW_UP_DAYS,
               connectors=None, limit: int = 5) -> dict:
    """Run the requested agents (default: search, follow_up, resource).
    The application agent is event-driven (status changes), so it is not
    run here — its pipeline is included in the status instead."""
    wanted = agents or ["search", "follow_up", "resource"]
    reports = []
    if "search" in wanted:
        reports.append(run_search_agent(profile_id, connectors=connectors, limit=limit))
    if "follow_up" in wanted:
        reports.append(run_follow_up_agent(profile_id, days=follow_up_days))
    if "resource" in wanted:
        reports.append(run_resource_agent(profile_id))
    return {"profile_id": profile_id, "reports": reports}


def profile_status(profile_id: str, follow_up_days: int = DEFAULT_FOLLOW_UP_DAYS) -> dict:
    """One status snapshot for the concierge and the frontend Agents view:
    workflow step, pipeline counts, follow-ups due, resource health, and
    each agent's last run. Computed live from the profile's own data."""
    profile = profiles_mod.get_profile(profile_id)
    if not profile:
        return {"error": "profile not found"}
    due = follow_up_due(profile, days=follow_up_days)
    resource = run_resource_agent(profile_id)
    # run_resource_agent records a run; keep the status read side-effect
    # light by dropping that duplicate run back off the stored list.
    profiles = profiles_mod._load()
    p = profiles.get(profile_id)
    if p and p.get("agent_runs"):
        p["agent_runs"] = [r for r in p["agent_runs"]
                           if not (r.get("agent") == "resource"
                                   and r.get("ran_at") == resource["ran_at"])][:MAX_AGENT_RUNS_KEPT]
        profiles_mod._save(profiles)
    workflow = profiles_mod.workflow_state(profile)
    return {"profile_id": profile_id,
            "client_name": profile["client"].get("name") or "",
            "current_step": workflow["current_step"],
            "workflow": workflow,
            "interview_complete": profile["interview_step"] >= len(profiles_mod.INTERVIEW_QUESTIONS),
            "pipeline": application_pipeline(profile),
            "saved_jobs": [_ensure_job_status(dict(j)) for j in profile.get("saved_jobs") or []],
            "follow_ups_due": [{"job_id": j["id"], "title": j.get("title", ""),
                                "company": j.get("company", ""),
                                "status": _job_status(j),
                                "last_status_at": j.get("last_status_at"),
                                "draft": j.get("follow_up_draft", "")} for j in due],
            "follow_up_days": follow_up_days,
            "resources": {"document_count": resource["document_count"],
                          "healthy_count": resource["healthy_count"],
                          "interview_notes_in_rag": resource["interview_notes_in_rag"],
                          "documents": resource["documents"]},
            "last_runs": (profile.get("agent_runs") or [])[:6]}


def status_summary_text(status: dict) -> str:
    """Plain-language status the concierge can speak, from real numbers."""
    if "error" in status:
        return "I don't have that profile on file — create it first."
    name = status["client_name"] or "this client"
    pipe = status["pipeline"]["counts"]
    lines = [f"Status for {name}: workflow is on "
             f"{status['current_step'].replace('_', ' ')}."]
    lines.append(f"Applications: {status['pipeline']['total']} saved job(s) — "
                 f"{pipe['saved']} saved, {pipe['applied']} applied, "
                 f"{pipe['interviewing']} interviewing, {pipe['offer']} offer(s), "
                 f"{pipe['hired']} hired, {pipe['rejected']} rejected.")
    due = status["follow_ups_due"]
    if due:
        lines.append(f"Follow-ups due ({len(due)}): " +
                     "; ".join(f"{d['title']} at {d['company']} ({d['status']})" for d in due) +
                     ". I have a draft note ready for each.")
    else:
        lines.append("No follow-ups due right now.")
    res = status["resources"]
    lines.append(f"Resources: {res['document_count']} document(s), "
                 f"{res['healthy_count']} healthy in RAG, "
                 f"{res['interview_notes_in_rag']} interview note(s) in RAG.")
    for run in status["last_runs"][:3]:
        lines.append(f"Last {run['agent']} run ({run.get('ran_at', '')[:16]}): {run.get('summary', '')}")
    return "\n".join(lines)
