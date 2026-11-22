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
./start.sh            # Docker stack: backend :5003, frontend :3003 (bumps +1 while taken)
./start.sh --test     # monitored startup: waits for both health endpoints, PASS/FAIL
./start.sh --build    # rebuild the images from scratch, then start
./start.sh --rebuild  # rebuild the images (cached), then start
./start.sh --down     # stop the stack (data is kept)
./start.sh --native   # local venv/Vite processes instead of Docker
```
Each port bumps +1 while taken (never stops another app); a stale PocketProWS server is stopped instead and the port is kept. `start-dev.sh` is an alias for `./start.sh`, and `./stop-dev.sh` stops the stack. The first run builds the images automatically; `./start.sh --no-build` skips that. With `--native`, the first run builds the venv/frontend instead.

### Docker
`./start.sh` runs the Compose stack in `docker-compose.yml` (backend + frontend images, container ports fixed at 5003/3003) — the standard startup, same as the other PocketPro apps. The same port resolver picks the host ports, the same health and backend-identity pairing checks gate startup, and `./start.sh --down` stops the stack. `--build`/`--rebuild` map to image builds. Chroma data persists in the `pocketprows-data` volume — separate from the native flow's data dir, and never removed by `--down`. API keys are read from the project `.env` when present. `./start.sh --native` opts into the local venv/Vite processes instead; `--docker` is still accepted and means the default.

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
- Documents (Add/Edit/Delete): `GET /api/profiles/{id}/documents`, `POST` (upload), `PATCH /api/profiles/{id}/documents/{doc_id}`, `POST .../{doc_id}/replace`, `POST .../{doc_id}/redigest`, `DELETE .../{doc_id}`
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
retrieval. Workflow steps: documents → interview → preferences →
job search → applications → follow-up. The resume comes FIRST: the
client's skills are always the skills used or referenced in the resume
(recomputed from the documents on every add/replace/delete) — the
interview's skills question only confirms that list, and the page
focuses the current step's panel full-width while the other steps
minimize to slim bars.

Certificates are identified too: PDF text is decoded through each
font's ToUnicode map, so generated certificates (Coursera-style)
digest to their course title as a certification plus the skills they
name, and a document counts as digested when it yields any of skills,
contact, certifications or education. A document uploaded before an
extractor improvement heals itself: a document with an empty stored
digest is re-digested from its stored file on load, and its
**Re-digest** button (`POST .../documents/{doc_id}/redigest`) does
the same on demand — no re-upload needed. Clicking a document's
title views it: the extracted text and the digest it produced
(`GET .../documents/{doc_id}/view`, read-only), plus an **Open
original** link that serves the stored file inline
(`GET .../documents/{doc_id}/file`) so a PDF opens in the browser.

The concierge chat is a real conversation: a per-profile transcript
(`GET`/`DELETE /api/profiles/{id}/chat`, newest 60 messages kept) is
recorded server-side and rendered as bubbles with starter-question
chips, job cards under the answers that found them, Enter-to-send and
a Clear chat. Short follow-ups ("and in Texas?") are searched
together with the previous question, and status questions ("How are
we doing?") are part of the same transcript. Interview turns keep
their own guided panel and are not recorded as chat.

Each saved job has an **Apply pack** (`POST .../saved-jobs/{id}/apply-pack`):
a fit check (the posting's named skills matched against the resume's,
never invented), a cover letter, and draft answers to the standard
application questions — all from the client's own profile. The letter
is written by the LLM chain when a key is configured
(`GEMINI_API_KEY`, then `GROQ_API_KEY`, in the local `.env`;
`backend/llm.py`), otherwise by a built-in template from the same
facts, and the pack names its provider. Preparation only: the client
reviews, opens the posting, and submits themselves — nothing is ever
sent automatically.

Profile-scoped searches run a **disqualifier filter**
(`backend/disqualify.py`): a job is omitted only when its own stated
requirements provably fail against the client's record — a degree
level above the highest on file (softened wording like "preferred"
or "or equivalent" never omits), a named certification the client
does not hold (requirement language required; a stack mention is a
topic, not a gate), a generic certification requirement with none on
file, or a required security clearance. Omitted jobs are reported in
the search response with their reasons and shown in the UI under
"Show what was omitted" — never silently dropped, never saved.
Unprovable requirements (years of experience, wish-list skills) are
not filtered; the apply pack's fit check covers those.

The concierge is **helpful and verbose, for transparency**: it teaches
the workflow while it works it. "Explain my workflow" (a starter chip,
or just ask) returns the full six-step walkthrough marked with the
client's position — ✓ done, → you are here, upcoming — and the next
move. Status answers are narrated briefings: what the current step
is, what the pipeline numbers mean, why follow-ups matter, and a
computed "Next best step". Q&A answers close with a "How I answered"
line naming exactly what was searched and that nothing was invented.
Every interview question carries a "Why I ask" line, shown in the
panel and in chat, so the client always knows what an answer is for.

## Tests
```bash
.venv/bin/python -m pytest backend/tests/ -q
cd frontend && npm test   # vitest smoke
```
