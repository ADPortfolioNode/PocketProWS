"""PocketProWS — Recruiter workstation. FastAPI is the ONLY server.

Routing answer (Anthony asked "node server routing?"): NO Node server.
FastAPI serves the API AND the built React static files (frontend/dist).
Node/Vite is a build-time tool only — `npm run build` produces static
HTML/JS, and FastAPI serves it. No Node runtime is needed in production,
which is exactly what the Asura DirectAdmin Python-app host supports.

Job sources — 6 FREE public APIs (verified live 2026-11-07):
adzuna, jooble, usajobs (free keys), remotive, remoteok, arbeitnow
(no key). Indeed / Dice / Monster stay GATED — no public search API.

Terminology (Anthony, 2026-11-07): the CLIENT is the job seeker — the
client seeks work; the EMPLOYER is the company posting the job — the
employer hires. A "person" is never an employer in this app.

Profile model (Anthony, 2026-11-07): the PROFILE is the unit of
separation. One profile holds exactly ONE client (one person per profile,
never two). Each profile gets its own personal resources: work history,
documents, interview answers, job search preferences, saved jobs, workflow
state, RAG store. Profiles are kept strictly separate — profile A's data
never appears in profile B. The HEADER is dynamically populated from the
ACTIVE profile (GET /api/profiles/active) and updates the moment the
active profile is switched, created, or edited — never hard-coded, never
stale. Everything is scoped by profile_id (the single scoping key).
"""
import os
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import profiles as profiles_mod
from .chat import answer as concierge_answer
from .connectors.adzuna import AdzunaConnector
from .connectors.arbeitnow import ArbeitnowConnector
from .connectors.gated import GatedConnector
from .connectors.jooble import JoobleConnector
from .connectors.remoteok import RemoteOKConnector
from .connectors.remotive import RemotiveConnector
from .connectors.usajobs import USAJobsConnector
from .vector_store import upsert_jobs

app = FastAPI(title="PocketProWS", version="0.3.0")

FREE_CONNECTORS = [
    AdzunaConnector(), JoobleConnector(), USAJobsConnector(),
    RemotiveConnector(), RemoteOKConnector(), ArbeitnowConnector(),
]
CONNECTORS = FREE_CONNECTORS + [
    GatedConnector("indeed"), GatedConnector("dice"), GatedConnector("monster"),
]
_NO_KEY = {"remotive", "remoteok", "arbeitnow"}


@app.get("/api/health")
def health():
    return {"status": "ok", "app": "PocketProWS", "version": "0.3.0",
            "sources": [c.name for c in CONNECTORS],
            "free_sources": [c.name for c in FREE_CONNECTORS]}


@app.get("/api/sources")
def sources():
    return {"sources": [
        {"name": c.name,
         "status": "ok" if c in FREE_CONNECTORS else "gated",
         "free": c in FREE_CONNECTORS,
         "key_configured": _key_configured(c.name)}
        for c in CONNECTORS]}


def _key_configured(name):
    from . import config
    if name in _NO_KEY:
        return True  # no key needed
    return {"adzuna": bool(config.ADZUNA_APP_ID and config.ADZUNA_APP_KEY),
            "jooble": bool(config.JOOBLE_API_KEY),
            "usajobs": bool(config.USAJOBS_API_KEY and config.USAJOBS_USER_AGENT)}.get(name, False)


@app.get("/api/jobs/search")
def jobs_search(q: str = "", location: str = "", limit: int = 10, source: str = "",
                profile_id: str = ""):
    results, all_jobs = [], []
    for c in CONNECTORS:
        if source and c.name != source:
            continue
        r = c.search(q, location, limit)
        results.append({"source": r.source, "status": r.status,
                        "message": r.message, "count": len(r.jobs), "jobs": r.jobs})
        all_jobs.extend(r.jobs)
    if all_jobs:
        upsert_jobs(all_jobs)
    if profile_id and all_jobs:
        # Scope the search to the active profile: remember what it found.
        profiles = profiles_mod._load()
        p = profiles.get(profile_id)
        if p:
            seen = {j["id"] for j in p["saved_jobs"]}
            p["saved_jobs"].extend(j for j in all_jobs if j["id"] not in seen)
            profiles_mod._save(profiles)
    return {"query": q, "location": location, "total": len(all_jobs),
            "results": results, "profile_id": profile_id}


# ------------------------------------------------------------ profiles
@app.post("/api/profiles")
def create_profile(payload: dict):
    return profiles_mod.create_profile(payload.get("name", ""))


@app.get("/api/profiles")
def list_profiles():
    return {"profiles": profiles_mod.list_profiles()}


# NOTE: /active routes must be declared BEFORE /{profile_id} or FastAPI
# would match the literal "active" as a profile id.
@app.get("/api/profiles/active")
def active_profile():
    """Header data: the active profile, read fresh from the store every
    call, so the header updates the moment the profile is switched, created
    or edited. Returns active_profile_id null when no profile is active."""
    p = profiles_mod.get_active_profile()
    if not p:
        return {"active_profile_id": None, "header": None, "profile": None}
    return {"active_profile_id": p["id"], "header": profiles_mod.header_for(p),
            "profile": _profile_view(p)}


@app.post("/api/profiles/active")
def set_active_profile(payload: dict):
    pid = payload.get("profile_id", "")
    if not profiles_mod.set_active_profile(pid):
        raise HTTPException(404, "profile not found")
    return active_profile()


@app.delete("/api/profiles/active")
def clear_active_profile():
    profiles_mod.clear_active_profile()
    return {"active_profile_id": None, "header": None, "profile": None}


def _profile_view(p: dict) -> dict:
    p = dict(p)
    p["workflow"] = profiles_mod.workflow_state(p)
    p["interview"] = profiles_mod.interview_status(p)
    p["header"] = profiles_mod.header_for(p)
    return p


@app.get("/api/profiles/{profile_id}")
def get_profile(profile_id: str):
    p = profiles_mod.get_profile(profile_id)
    if not p:
        raise HTTPException(404, "profile not found")
    return _profile_view(p)


@app.patch("/api/profiles/{profile_id}")
def patch_profile(profile_id: str, payload: dict):
    p, err = profiles_mod.update_profile(profile_id, payload)
    if err:
        raise HTTPException(400, err)
    if not p:
        raise HTTPException(404, "profile not found")
    return _profile_view(p)


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: str):
    if not profiles_mod.delete_profile(profile_id):
        raise HTTPException(404, "profile not found")
    return {"deleted": profile_id}


# ------------------------------------------------------------ interview
@app.get("/api/profiles/{profile_id}/interview")
def interview_get(profile_id: str):
    p = profiles_mod.get_profile(profile_id)
    if not p:
        raise HTTPException(404, "profile not found")
    return profiles_mod.interview_status(p)


@app.post("/api/profiles/{profile_id}/interview/answer")
def interview_answer(profile_id: str, payload: dict):
    res = profiles_mod.answer_interview(profile_id, payload.get("answer", ""))
    if "error" in res:
        raise HTTPException(404, res["error"])
    return res


# ------------------------------------------------------------ workflow
@app.get("/api/profiles/{profile_id}/workflow")
def workflow_get(profile_id: str):
    p = profiles_mod.get_profile(profile_id)
    if not p:
        raise HTTPException(404, "profile not found")
    return profiles_mod.workflow_state(p)


@app.post("/api/profiles/{profile_id}/workflow")
def workflow_mark(profile_id: str, payload: dict):
    st = profiles_mod.mark_workflow_step(profile_id, payload.get("step", ""))
    if st is None:
        raise HTTPException(404, "profile not found or bad step")
    return st


# ------------------------------------------------------------ documents (AED)
@app.get("/api/profiles/{profile_id}/documents")
def documents_list(profile_id: str):
    docs = profiles_mod.list_documents(profile_id)
    if docs is None:
        raise HTTPException(404, "profile not found")
    return {"documents": docs,
            "permissions": "Add / Edit / Delete — you own these files; "
                           "adding a document digests it into this profile's "
                           "resource and RAG store."}


@app.post("/api/profiles/{profile_id}/documents")
async def document_add(profile_id: str, file: UploadFile = File(...)):
    if not profiles_mod.get_profile(profile_id):
        raise HTTPException(404, "profile not found")
    data = await file.read()
    res = profiles_mod.add_document(profile_id, file.filename, data)
    if "error" in res:
        raise HTTPException(404, res["error"])
    return res


@app.patch("/api/profiles/{profile_id}/documents/{doc_id}")
def document_edit(profile_id: str, doc_id: str, payload: dict):
    res = profiles_mod.edit_document(profile_id, doc_id, payload)
    if "error" in res:
        raise HTTPException(404, res["error"])
    return res


@app.post("/api/profiles/{profile_id}/documents/{doc_id}/replace")
async def document_replace(profile_id: str, doc_id: str, file: UploadFile = File(...)):
    if not profiles_mod.get_profile(profile_id):
        raise HTTPException(404, "profile not found")
    data = await file.read()
    res = profiles_mod.edit_document(profile_id, doc_id, {}, data=data,
                                     filename=file.filename)
    if "error" in res:
        raise HTTPException(404, res["error"])
    return res


@app.delete("/api/profiles/{profile_id}/documents/{doc_id}")
def document_delete(profile_id: str, doc_id: str):
    if not profiles_mod.delete_document(profile_id, doc_id):
        raise HTTPException(404, "profile or document not found")
    return {"deleted": doc_id}


@app.get("/api/profiles/{profile_id}/saved-jobs")
def saved_jobs(profile_id: str):
    p = profiles_mod.get_profile(profile_id)
    if not p:
        raise HTTPException(404, "profile not found")
    return {"profile_id": profile_id, "saved_jobs": p["saved_jobs"]}


@app.post("/api/chat")
def chat(payload: dict):
    return concierge_answer(payload.get("message", ""),
                            profile_id=payload.get("profile_id", ""),
                            mode=payload.get("mode", ""))


# Serve the built React frontend (if built) — same pattern as PocketProNYL.
DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        candidate = DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")
