#!/usr/bin/env python3
"""Seed Anthony Dickerson's own job hunt into PocketProWS.

Creates (or finds) Anthony as the client profile and records every job
from his Nov 2026 hunt — submitted, in-progress/blocked, parked, and
closed — as saved jobs with the app's own application statuses.

Run from the PocketProWS repo root (or anywhere) with the project's venv:
    .venv/bin/python scripts/seed_anthony_applications.py

Idempotent: re-running adds nothing twice and leaves existing statuses
alone unless the recorded state changed. Uses the app's own modules
(backend.profiles / backend.agents) so the data goes through the same
validation and history the UI uses.

Data source: Anthony's verified job-hunt record, Nov 10-13, 2026.
Statuses use the app's vocabulary only:
  applied  = application submitted (applied_at = real submission date)
  saved    = not yet applied — the note says why (blocked / parked / closed)
There is no "parked" or "closed" status in the app; a closed posting is
recorded as saved with a "do not apply" note, never as "rejected"
(rejected means the employer turned him down, which is not what happened).
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend import agents as agents_mod
from backend import profiles as profiles_mod

CLIENT_NAME = "Anthony Dickerson"

CLIENT = {
    "name": "Anthony Dickerson",
    "current_role": "AI Engineer",
    "target_roles": ["AI Engineer", "AI Developer", "Web Developer"],
    "skills": ["Python", "FastAPI", "Flask", "RAG", "LLM APIs",
               "Gemini", "Groq", "Ollama", "OpenAI", "Claude",
               "ChromaDB", "React", "Docker", "Git", "GitHub",
               "ML pipelines"],
    "location": "Queens, NY",
    "remote_preference": "Remote",
    "employment_type": "Full-time or contract",
    "salary_min": "85000",
    "salary_max": "110000",
    "salary_text": "$85,000-$110,000",
    "email": "deoism@gmail.com",
    "phone": "718-914-0313",
    "linkedin": "linkedin.com/in/anthony-d-aidev",
    "github": "github.com/ADPortfolioNode",
}

# id, title, company, location, source, url, snippet, salary,
# status, applied date (YYYY-MM-DD or ""), note
JOBS = [
    # ---- submitted (applied) ----
    ("manual-myriad360-junior-ai-automation",
     "Junior AI and Automation Engineer", "Myriad360", "Remote (US)",
     "Indeed", "", "Junior AI/Automation Engineer; associate-friendly.",
     "$90,000", "applied", "2026-11-10",
     "Submitted Nov 10, 2026 via Indeed; salary expectation $90,000 entered."),
    ("manual-mitchell-martin-ai-engineer",
     "AI Engineer", "Mitchell/Martin Inc.", "Hybrid (4 days onsite)",
     "Recruiter (Sunitha Goje)", "",
     "Portal listed as 'Sr. BA / AI Developer', Job Ref 26-27919.",
     "", "applied", "2026-11-10",
     "Submitted Nov 10, 2026 via recruiter Sunitha Goje (sgoje@itmmi.com); "
     "cover letter 07 + resume emailed. Applied despite 4-days-onsite hybrid."),
    ("manual-luxoft-senior-genai",
     "Senior GenAI Engineer (VR-125338)", "Luxoft", "Remote (US)",
     "Luxoft careers", "", "Senior GenAI Engineer, VR-125338.",
     "$7,500/mo ($90K/yr)", "applied", "2026-11-10",
     "Submitted Nov 10, 2026; resume only; $7,500/mo entered."),
    ("manual-awesome-motive-ai-engineer",
     "AI Engineer", "Awesome Motive", "Remote (US)",
     "Workable", "", "AI Engineer; best tech match.",
     "$90,000", "applied", "2026-11-10",
     "Submitted Nov 10, 2026 via Workable; cover letter 09; salary $90,000 entered."),
    ("manual-mission-us-applied-ai",
     "Applied AI Engineer", "Mission US", "Remote (US)",
     "Rippling ATS", "", "Applied AI Engineer.",
     "", "applied", "2026-11-12",
     "Submitted Nov 12, 2026 by Anthony himself on his own browser/device; "
     "text-message consent filed as Yes. Six identical Rippling confirmations "
     "arrived (likely one submission + duplicate-send glitch)."),
    ("manual-patreon-swe-backend",
     "Software Engineer, Backend", "Patreon", "New York, NY (hybrid 3 days/week)",
     "Ashby", "https://jobs.ashbyhq.com/patreon/2c79ab4b-6479-451d-bbac-e2e2fb0dc911",
     "Backend SWE; FastAPI, SQL, data pipelines.",
     "$189,000-$255,500 + equity", "applied", "2026-11-13",
     "Submitted Nov 13, 2026 09:04 EST via Ashby; cover letter 19; resume PDF. "
     "No street address, no ZIP, no salary field on the form."),
    # ---- in progress / blocked (saved) ----
    ("manual-evlo-llm-genai",
     "AI LLM/GenAI Engineer", "Evlo", "Remote (NY)",
     "evlo.ai", "https://evlo.ai/jobs/apply/bf-g0021-s06",
     "LLM/GenAI Engineer; degree 'or equivalent practical experience'.",
     "Not posted (est. $130-180K)", "saved", "",
     "BLOCKED Nov 13, 2026: resume uploaded; form requires a Zip Code and the "
     "resume has none. Cover letter 17 drafted, not attached (single-file "
     "upload). Awaiting Anthony's decision on sharing a ZIP."),
    ("manual-accenture-senior-web-dev",
     "Senior Web Developer (R00368488)", "Accenture", "New York, NY",
     "Accenture Workday", "",
     "Senior Web Developer; React/TypeScript/Next.js; closes Dec 15, 2026.",
     "$66,300-$205,800", "saved", "",
     "BLOCKED Nov 13, 2026: signed in via Google, resume uploaded; form "
     "requires Address Line 1 AND Postal Code — resume has neither. Cover "
     "letter 21 drafted, not attached. Needs Anthony to supply street address + ZIP."),
    ("manual-barclays-web-portal-dev",
     "Web Portal Developer (JR-0000133464)", "Barclays", "New York, NY (hybrid 2 days)",
     "Barclays Workday", "https://search.jobs.barclays/job/new-york/web-portal-developer/13015/101105784880",
     "Web Portal Developer; Markets Post Trade, Technology.",
     "$137,717-$145,000", "saved", "",
     "BLOCKED Nov 13, 2026: posting live, but Workday requires creating a "
     "candidate account (email + new password) first. Cover letter 20 drafted, "
     "not uploaded. Needs Anthony to create the Workday account."),
    # ---- parked (saved) ----
    ("manual-csi-ai-engineer",
     "AI Engineer (R-100743)", "CSI", "",
     "Workday", "", "AI Engineer; posting closes Nov 17, 2026.",
     "", "saved", "",
     "PARKED: Workday sign-in wall. Cover letter 16 drafted. Restart when "
     "Anthony has a CSI account; posting closes Nov 17, 2026."),
    ("manual-nimara-senior-ai",
     "Senior AI Engineer", "Nimara", "Remote (US)",
     "Dice", "", "Senior AI Engineer, contract.",
     "$45-50/hr C2C / $50-55/hr W2", "saved", "",
     "PARKED: Dice sign-in wall. Cover letter 10 drafted."),
    ("manual-catapult-api-dev",
     "API Developer (Python/Applied AI)", "Catapult", "Remote (US), 6-mo",
     "Dice", "", "API Developer, Python/Applied AI, 6-month contract.",
     "Up to $68/hr", "saved", "",
     "PARKED: Dice sign-in wall. Cover letter 11 drafted."),
    ("manual-optum-2394708",
     "Job 2394708", "Optum", "",
     "Taleo", "", "Optum application, held unsubmitted.",
     "", "saved", "",
     "HELD unsubmitted: Taleo sign-in + Anthony's answers pending; no address entered."),
    # ---- closed / expired / skipped (saved, do not apply) ----
    ("manual-brightplan-applied-ai",
     "Applied AI Engineer (Python/AI)", "BrightPlan (via RemoteHunter)", "Remote (US)",
     "Workable / LinkedIn", "", "Applied AI Engineer; FastAPI; best tech match.",
     "$125,000-$155,000", "saved", "",
     "CLOSED Nov 13, 2026: Workable posting 'no longer available'; LinkedIn "
     "route blocked by account restriction (ID check). Cover letter 13 unused. "
     "Do not re-apply."),
    ("manual-airbnb-ml-assistance",
     "ML Engineer, Assistance Engineering", "Airbnb", "Remote (US)",
     "Airbnb careers", "https://careers.airbnb.com/positions/7826337/",
     "ML Engineer, Assistance Engineering.",
     "$162,000-$186,000", "saved", "",
     "CLOSED Nov 13, 2026: careers posting returns 404. Cover letter 18 "
     "unused. Do not re-apply."),
    ("manual-cai-r8777",
     "Job R8777", "CAI", "",
     "", "", "Role filled before application.",
     "", "saved", "",
     "CLOSED: role filled. No application."),
    ("manual-lanthos",
     "AI Engineer", "Lanthos", "",
     "", "", "Hard Vertex AI / GCP requirements.",
     "", "saved", "",
     "SKIPPED: hard Vertex AI / GCP requirements; does not match Anthony's tech."),
    ("manual-aiapply-llm",
     "LLM Applications Engineer", "AIApply", "Remote (US)",
     "", "", "LLM Applications Engineer.",
     "$165,000-$225,000", "saved", "",
     "SKIPPED: hard LangGraph / TypeScript / cloud requirements. Cover letter "
     "08 unused."),
    ("manual-torentify-genai",
     "GenAI App Engineer", "Torentify", "Remote (US)",
     "", "", "GenAI App Engineer.",
     "$135,000-$150,000", "saved", "",
     "EXPIRED: no live route. Cover letter 12 unused."),
    ("manual-remotehunter-brightplan-earlier",
     "Applied AI Engineer", "BrightPlan (via RemoteHunter)", "Remote (US)",
     "", "", "Applied AI Engineer; earlier listing.",
     "", "saved", "",
     "EXPIRED: earlier listing; no live route. Cover letter 13 unused."),
]


def find_or_create_profile():
    profiles = profiles_mod._load()
    for pid, p in profiles.items():
        if (p.get("client") or {}).get("name", "").strip().lower() == CLIENT_NAME.lower():
            return p
    profile = profiles_mod.create_profile(CLIENT_NAME)
    return profile


def main():
    profile = find_or_create_profile()
    pid = profile["id"]
    # Fill the client record from the resume (only blanks get overwritten).
    client = profile.setdefault("client", {})
    for key, value in CLIENT.items():
        if not client.get(key):
            client[key] = value

    profiles = profiles_mod._load()
    profile = profiles[pid]
    saved = profile.setdefault("saved_jobs", [])
    existing = {j.get("id") for j in saved}

    added, updated = 0, 0
    for (jid, title, company, location, source, url, snippet,
         salary, status, applied_date, note) in JOBS:
        # Reload every iteration: set_application_status loads and saves
        # its own copy, so a stale in-memory list would silently drop jobs.
        profiles = profiles_mod._load()
        profile = profiles[pid]
        saved = profile.setdefault("saved_jobs", [])
        if jid in {j.get("id") for j in saved}:
            continue
        job = {"id": jid, "title": title, "company": company,
               "location": location, "source": source, "url": url,
               "snippet": snippet, "salary": salary}
        agents_mod._ensure_job_status(job)
        saved.append(job)
        profiles_mod._save(profiles)
        added += 1
        if status == "applied":
            res = agents_mod.set_application_status(pid, jid, "applied", note)
            if "error" in res:
                print(f"  !! {jid}: {res['error']}")
                continue
            # Backdate to the real submission date (the transition above
            # records today as the recording date).
            profiles = profiles_mod._load()
            job = next(j for j in profiles[pid]["saved_jobs"] if j["id"] == jid)
            job["applied_at"] = applied_date
            job["last_status_at"] = applied_date
            if job.get("status_history"):
                job["status_history"][-1]["at"] = applied_date
            profiles_mod._save(profiles)
            updated += 1
        else:
            # Saved jobs carry the state in their history note.
            profiles = profiles_mod._load()
            job = next(j for j in profiles[pid]["saved_jobs"] if j["id"] == jid)
            job["status_history"] = [{
                "status": "saved",
                "at": "2026-11-13",
                "note": note,
            }]
            job["last_status_at"] = "2026-11-13"
            profiles_mod._save(profiles)

    profiles = profiles_mod._load()
    profile = profiles[pid]
    pipe = agents_mod.application_pipeline(profile)
    print(f"profile: {CLIENT_NAME} ({pid})")
    print(f"added {added} jobs, {updated} marked applied")
    print(f"pipeline: {pipe['counts']} (total {pipe['total']})")
    for j in profile["saved_jobs"]:
        print(f"  [{j.get('application_status')}] {j.get('company')} — {j.get('title')}")


if __name__ == "__main__":
    main()
