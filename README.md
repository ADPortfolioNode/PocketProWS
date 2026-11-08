# PocketProWS — Recruiter Workstation

Recruiter workstation in the PocketPro family. Job search across six
job boards, a concierge recruiter (RAG chat over saved jobs), embedded
ChromaDB, FastAPI routing, React single-page dashboard.

## Routing — no Node server
FastAPI is the only server. Node/Vite is a **build-time tool only**:
`npm run build` produces static files in `frontend/dist`, and FastAPI
serves them (see `backend/main.py`). No Node runtime is needed in
production — this is what the Asura DirectAdmin Python-app host supports.

## Host — yes, Asura works (with constraints)
Target host: Asura reseller hosting, DirectAdmin Python app, $49.99/yr
(stainlessdeoism.biz, server d5.my-control-panel.com, no Docker).
Constraints, same as the other PocketPro apps:
- Single worker/process only — embedded ChromaDB's folder must never be
  opened by two processes at once.
- ChromaDB embedded via `chromadb.PersistentClient(path=...)`, data under
  the app directory (`~/workspace/pocketprows-data/` locally).
- Pre-built React static files (no Node runtime); outbound HTTPS to the
  job-board APIs; env vars in DirectAdmin for the API keys.
- Python version / pip install of chromadb / data persistence are still
  unconfirmed with Asura support — see the saved support-ticket draft
  pattern used for the other PocketPro apps before going live.

## Setup (dev)
One command, same pattern as the other PocketPro projects:
```bash
./start.sh            # backend :5003, frontend :3003 (Vite dev, proxies /api)
./start.sh --test     # monitored startup: waits for both health endpoints, PASS/FAIL
./start.sh --build    # recreate the venv + clean frontend install and build, then start
./start.sh --rebuild  # reinstall deps + rebuild (cached), then start
./start.sh --down     # stop the stack (data is kept)
```
Each port bumps +1 while taken (never stops another app); a stale PocketProWS server is stopped instead and the port is kept. `start-dev.sh` is an alias for `./start.sh`, and `./stop-dev.sh` stops the stack. The first run builds the venv/frontend automatically; `./start.sh --no-build` skips that.

## API keys (env vars, never commit)
```bash
ADZUNA_APP_ID=... ADZUNA_APP_KEY=...        # free, developer.adzuna.com
JOOBLE_API_KEY=...                          # free form, jooble.org/api/about
USAJOBS_API_KEY=... USAJOBS_USER_AGENT=...  # free, developer.usajobs.gov/apirequest
```
Indeed, Dice and Monster have **no usable public search API** — see
`~/workspace/your_files/pocketprows-job-board-apis-2026-11-07.md`.
Their connectors report `status: "unavailable"` with the reason, honestly.

## Endpoints
- `GET /api/health` — status + sources (6 free + 3 gated)
- `GET /api/sources` — per-board status + key configured?
- `GET /api/jobs/search?q=&location=&source=&limit=&profile_id=` — search all / one board; results are upserted into Chroma and, when profile_id is given, saved to that profile's saved jobs
- `POST /api/chat {"message": "...", "profile_id": "...", "mode": ""}` — concierge recruiter, keyless retrieved-text fallback, scoped to the active profile; mode "interview" runs the one-question interview
- Profiles: `POST /api/profiles`, `GET /api/profiles`, `GET/PATCH/DELETE /api/profiles/{id}`
- Active profile / header: `GET /api/profiles/active` (header data, read fresh from the store), `POST /api/profiles/active {"profile_id": ...}`, `DELETE /api/profiles/active`
- Interview: `GET /api/profiles/{id}/interview`, `POST /api/profiles/{id}/interview/answer`
- Workflow: `GET /api/profiles/{id}/workflow`, `POST /api/profiles/{id}/workflow {"step": ...}`
- Documents (Add/Edit/Delete): `GET /api/profiles/{id}/documents`, `POST` (upload), `PATCH /api/profiles/{id}/documents/{doc_id}`, `POST .../{doc_id}/replace`, `DELETE .../{doc_id}`
- `GET /api/profiles/{id}/saved-jobs`

## Profiles — one person (one client) per profile (2026-11-07)

Terminology (Anthony, 2026-11-07): the **client** is the job seeker — the
client seeks work; the **employer** is the company posting the job — the
employer hires. A "person" is never an employer in this app, and "person"
is not the user-facing term for the job seeker.

**Profile model (Anthony, 2026-11-07): the PROFILE is the unit of
separation.** One profile holds exactly ONE client (one person per profile,
never two — a patch that tries to add a second person is rejected with
400). Each profile gets its own personal resources: work history,
documents, interview answers, job search preferences, saved jobs, workflow
state, RAG store. Profiles are kept strictly separate: profile A's work
history, documents, saved jobs and RAG hits never appear in profile B.
Everything is scoped by `profile_id` (the single scoping key; `client_id`
is gone — clean rename, no backwards-compatible alias).

**Header (Anthony, 2026-11-07): dynamically populated from the ACTIVE
profile.** `GET /api/profiles/active` returns the header (client name,
target roles, current role, location, remote preference, employment type,
workflow step) read fresh from the store on every call. The frontend
re-fetches it whenever the active profile is switched, created, edited, or
an interview answer is saved, and re-loads every profile-scoped panel
(documents, interview, jobs, workflow) from the new profile's data. No
client name is hard-coded in the UI. The first profile created becomes
active; deleting the active profile clears it.

The concierge interviews one question at a time (11 questions, identity
first), saves each answer, and confirms what it saved. Documents are
digested on upload/replace (TXT/MD, DOCX, PDF best-effort): skills,
certifications, education, email/phone are extracted into the profile's
client record and the text is chunked into a dedicated Chroma collection
filtered by profile_id — profile A's data never appears in profile B's
retrieval. Workflow steps: interview → documents → preferences →
job search → applications → follow-up.

## Tests
```bash
.venv/bin/python -m pytest backend/tests/ -q
cd frontend && npm test   # vitest smoke
```
