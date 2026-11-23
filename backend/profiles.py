"""Per-profile resources + conversational interview + workflow.

Terminology (Anthony, 2026-11-07): the CLIENT is the job seeker — the
client seeks work; the EMPLOYER is the company posting the job — the
employer hires. A "person" is never an employer in this app, and "person"
is not the user-facing term for the job seeker.

Design (profile model, Anthony 2026-11-07):
- The PROFILE is the unit of separation. One PROFILE holds exactly ONE
  client (the job seeker; the employer hires) — never two people in one
  profile. A profile has: client (hire-relevant info for that one client),
  documents (AED: add / edit / delete), interview answers, workflow state,
  saved jobs, RAG store.
- EVERYTHING is per profile, keyed by profile_id, so the workstation scales
  to multiple profiles. Profiles are kept strictly separate.
- The concierge runs a conversational interview ONE question at a time.
  Each reply that holds relevant info is saved into that client's resource
  and the concierge confirms briefly what it saved.
- The interview establishes WHO the client is FIRST (name), before
  any job preferences are collected. Every search/chat is scoped to the
  active profile.
- RAG: client documents + interview answers are chunked into ChromaDB in
  a dedicated collection, filtered by profile_id metadata — client A's data
  never appears in client B's retrieval.
- Documents are DIGESTED on upload (and re-digested on replace): text is
  extracted (TXT/MD, DOCX via zipfile, PDF best-effort), structured facts
  (skills, certifications, education, email, phone, work years) are pulled
  into the client's profile, and the text is chunked into RAG.
- RESUME FIRST (Anthony, 2026-11-21): the workflow asks for the resume
  (documents step) BEFORE the interview, and the client's skills are
  ALWAYS the skills used or referenced in the resume — the union of the
  documents' digested skills, recomputed on every add / replace / delete.
  Nothing else writes the skills list: the interview's skills question
  only confirms the resume's list, so matching never runs on typed-in
  skills the resume does not back up.

Storage: profiles.json + documents/ + active_profile.json live under
CHROMA_PATH (the same data directory as Chroma, so tests that redirect
CHROMA_PATH stay isolated). Single process only, like the rest of
PocketProWS.
Single process only, like the rest of PocketProWS.
"""
import json
import re
import sys
import uuid
import zipfile
import zlib
from io import BytesIO
from pathlib import Path

from . import config as cfg
from . import vector_store as vs

WORKFLOW_STEPS = ["documents", "interview", "preferences",
                  "job_search", "applications", "follow_up"]

# One question at a time. First question establishes WHO the search is for.
INTERVIEW_QUESTIONS = [
    {"key": "name", "field": "name",
     "question": "Hi! I'm your recruiter concierge — friendly help, one question at a time. First, who is our client? What's the full name of the person seeking work? (The client seeks work; the employer hires.)",
     "why": "Everything is filed under the client's name — searches, saved jobs, cover letters and follow-ups all carry it, so we start there."},
    {"key": "current_role", "field": "current_role",
     "question": "Thanks! What do you do now — your current or most recent role?",
     "why": "It frames the whole search — and the cover letters open with where the client is coming from."},
    {"key": "target_roles", "field": "target_roles",
     "question": "What roles are you targeting? For example: AI Engineer, Web Developer, or AI Developer.",
     "why": "These drive the job search itself: I match postings against the roles the client actually wants, not just any opening."},
    {"key": "skills", "field": "skills",
     "question": "Skills come from your resume — I'll confirm the list it gives me.",
     "why": "Matching, the disqualifier filter and the apply packs all use exactly the resume's skills — nothing added, nothing guessed."},
    {"key": "work_history", "field": "work_history",
     "question": "Tell me about your work history — employers, roles, and dates, briefly. One or two sentences per job is fine.",
     "why": "Employers ask for it on every application. On file, the apply pack can answer those questions in one pass."},
    {"key": "certifications", "field": "certifications",
     "question": "Any certifications or courses? For example: IBM AI Engineering, AWS, or a degree course.",
     "why": "Postings that require a named certification get omitted when it isn't on file — and the ones held get cited in cover letters."},
    {"key": "education", "field": "education",
     "question": "What's your education background? (School, degree, year — whatever you have.)",
     "why": "Same protection as certifications: a posting that requires a degree above the one on file is omitted instead of wasting an application."},
    {"key": "location", "field": "location",
     "question": "Where are you based, and do you want remote, hybrid, or on-site work?",
     "why": "Location plus remote preference decide which postings are realistic for this client — and which ones get flagged."},
    {"key": "employment_type", "field": "employment_type",
     "question": "Full-time, contract, or either?",
     "why": "Full-time, part-time or contract changes which postings fit, and what the application answers say."},
    {"key": "salary", "field": "salary",
     "question": "What salary or hourly rate are you aiming for? It's fine to say 'not sure yet'.",
     "why": "Recorded once, then reused in every salary-expectation answer — and never shared anywhere beyond the application itself."},
    {"key": "cover_letter", "field": "cover_letter_highlights",
     "question": "Last one for now — for cover letters, what should I highlight about you, and what tone do you like? (For example: confident and direct, or warm and friendly.)",
     "why": "These highlights and this tone are exactly what the apply pack writes the cover letters from."},
]

KNOWN_SKILLS = ["python", "fastapi", "flask", "react", "javascript", "typescript",
                "langchain", "langgraph", "rag", "chromadb", "pinecone", "faiss",
                "docker", "aws", "gcp", "azure", "gemini", "groq", "ollama",
                "openai", "sql", "postgres", "mongodb", "redis", "node", "vite",
                "next.js", "html", "css", "git", "ci/cd", "kubernetes", "terraform",
                "machine learning", "deep learning", "pytorch", "tensorflow",
                "nlp", "embeddings", "vector", "api", "rest", "graphql",
                # Office & administration
                "microsoft office", "microsoft excel", "excel", "microsoft word",
                "powerpoint", "outlook", "google workspace", "data entry",
                "typing", "bookkeeping", "quickbooks", "accounting", "payroll",
                "invoicing", "accounts payable", "accounts receivable",
                "scheduling", "filing", "receptionist", "office management",
                # Business, sales & customer-facing work
                "customer service", "sales", "retail", "cashier", "marketing",
                "social media", "negotiation", "leadership", "project management",
                "operations", "training", "supervision", "inventory",
                "merchandising", "crm", "salesforce", "bilingual", "spanish",
                # Healthcare & care work
                "nursing", "patient care", "phlebotomy", "medical assistant",
                "cpr", "first aid", "caregiving", "home health", "dental",
                "pharmacy", "medical records", "hipaa", "vital signs", "ekg",
                # Trades, warehouse & logistics
                "warehouse", "forklift", "logistics", "shipping", "receiving",
                "cdl", "driving", "delivery", "electrical", "plumbing",
                "carpentry", "hvac", "welding", "maintenance", "janitorial",
                "cleaning", "security", "construction", "painting",
                "landscaping", "automotive", "mechanic",
                # Food & hospitality
                "food service", "food preparation", "cooking", "chef",
                "bartending", "serving", "housekeeping", "hospitality",
                "catering",
                # Education, support & general
                "teaching", "tutoring", "childcare", "lesson planning",
                "help desk", "technical support", "troubleshooting"]

# Word-boundary matching: "excel" must not fire on "excellent", "git" not
# on "digital", "rag" not on "storage". Terms keep their list spelling in
# the digest output.
_SKILL_PATTERNS = {s: re.compile(rf"\b{re.escape(s)}\b") for s in KNOWN_SKILLS}


# ---------------------------------------------------------------- store
def _data_dir() -> Path:
    d = Path(cfg.CHROMA_PATH)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _profiles_file() -> Path:
    return _data_dir() / "profiles.json"


def _docs_dir(profile_id: str) -> Path:
    d = _data_dir() / "documents" / profile_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _digest_empty(digest) -> bool:
    d = digest or {}
    return not (d.get("skills") or d.get("email")
                or d.get("certifications") or d.get("education"))


def _repair_empty_digests(profiles: dict) -> bool:
    """Self-repair: a document whose stored digest is empty (uploaded
    under an older, weaker extractor — the certificate case) is
    re-digested from its stored file and re-indexed, so an extractor
    improvement heals existing documents on its own. Documents that
    still yield nothing are left exactly as they are (honestly empty)."""
    changed = False
    for p in profiles.values():
        for doc in p.get("documents") or []:
            if not _digest_empty(doc.get("digest")):
                continue
            try:
                stored = sorted(_docs_dir(p["id"]).glob(f"{doc['id']}-*"))
                if not stored:
                    continue
                data = stored[0].read_bytes()
                text = extract_text(data, doc["filename"])
                digest = digest_text(text)
                if _digest_empty(digest) and len(text) == (doc.get("text_chars") or 0):
                    continue  # nothing new to heal
                doc.update({"size": len(data), "text_chars": len(text),
                            "digest": digest})
                _merge_digest(p, digest)
                vs.delete_profile_doc_chunks(p["id"], doc["id"])
                vs.upsert_profile_chunks(p["id"], doc["id"], text)
                changed = True
            except Exception as exc:  # noqa: BLE001 - healing must never
                # break profile loading: one unreadable document leaves
                # its stored digest untouched and the rest still load.
                print(f"[repair] could not re-digest {doc.get('id')}: "
                      f"{type(exc).__name__}: {exc}", file=sys.stderr)
    return changed


def _load() -> dict:
    f = _profiles_file()
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    # A damaged store (valid JSON but not an object — e.g. a truncated or
    # hand-edited file) must not break profile creation forever: callers
    # assume a dict (.get / [pid] = ...), so anything else reads as empty
    # and the next save rewrites a clean store.
    if not isinstance(data, dict):
        return {}
    try:
        if _repair_empty_digests(data):
            _save(data)
    except Exception as exc:  # noqa: BLE001 - a failed repair/save must
        # never take profile loading (and every profile endpoint) down.
        print(f"[repair] digest self-repair skipped: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
    return data


def _save(profiles: dict) -> None:
    # Write-then-replace, so a crash or kill mid-write can never leave a
    # truncated profiles.json behind for the next run to trip over.
    f = _profiles_file()
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(profiles, indent=2))
    tmp.replace(f)


def _blank_client() -> dict:
    return {"name": "", "current_role": "", "target_roles": [], "skills": [],
            "work_history": [], "certifications": [], "education": [],
            "location": "", "remote_preference": "", "employment_type": "",
            "salary_min": "", "salary_max": "", "salary_text": "",
            "cover_letter_tone": "", "cover_letter_highlights": "",
            "email": "", "phone": "", "linkedin": "", "github": ""}


def create_profile(name: str = "") -> dict:
    # An empty name is allowed on purpose: the interview's first question
    # IS the client's name, so a profile can be created nameless and the
    # concierge fills it in on Q1. (Audit 2026-11-08: not a defect.)
    profiles = _load()
    pid = uuid.uuid4().hex[:12]
    client_data = _blank_client()
    client_data["name"] = name.strip()
    profile = {"id": pid, "client": client_data,
               "interview_step": 0, "interview_answers": {},
               "documents": [], "saved_jobs": [],
               "workflow_done": [], "chat": []}
    profiles[pid] = profile
    _save(profiles)
    # First profile becomes the active one, so the header has something to show.
    if not _active_file().exists():
        set_active_profile(pid)
    return profile


CHAT_CAP = 60


def get_chat(profile_id: str):
    """The profile's concierge conversation, oldest first (None when the
    profile does not exist)."""
    p = get_profile(profile_id)
    if not p:
        return None
    return p.get("chat") or []


def append_chat(profile_id: str, role: str, text: str):
    """Append one message to the profile's conversation, keeping the
    newest CHAT_CAP messages. Returns the updated history, or None."""
    from datetime import datetime, timezone
    profiles = _load()
    p = profiles.get(profile_id)
    if not p:
        return None
    chat = p.setdefault("chat", [])
    chat.append({"role": role, "text": text,
                 "ts": datetime.now(timezone.utc).isoformat()})
    del chat[:-CHAT_CAP]
    _save(profiles)
    return chat


def clear_chat(profile_id: str) -> bool:
    profiles = _load()
    p = profiles.get(profile_id)
    if not p:
        return False
    p["chat"] = []
    _save(profiles)
    return True


# The concierge greets first (Anthony, 2026-11-22): an empty
# conversation opens with his greeting — who he is, where this client
# stands in the workflow, and a question he expects an answer to.
_GREETING_NEXT = {
    "documents": "It all starts with the resume — shall we add it under Documents now?",
    "interview": "Shall we pick up the interview — a few short questions, one at a time, each one saying why I'm asking?",
    "preferences": "Shall we run the first job search with those preferences and see what fits?",
    "job_search": "Shall we run a fresh job search across the six boards and see what fits?",
    "applications": "Shall we review the saved jobs and build an apply pack for the strongest one?",
    "follow_up": "Shall we check which applications have gone quiet and draft their follow-ups?",
}


def greeting_text(profile) -> str:
    client = profile.get("client") or {}
    name = client.get("name") or "your client"
    ws = workflow_state(profile)
    steps = ws["steps"]
    current = ws["current_step"]
    idx = [s["step"] for s in steps].index(current) + 1
    done_count = sum(1 for s in steps if s["done"])
    position = f"We're at step {idx} of {len(steps)}: {current.replace('_', ' ')}."
    if done_count:
        position += f" {done_count} step{'s' if done_count != 1 else ''} already behind us."
    ask = _GREETING_NEXT.get(current, "Where would you like to start?")
    return (f"Hello — I'm your concierge, working for {name}. {position} "
            f"Ask me 'how are we doing' anytime for a full briefing, or "
            f"'explain my workflow' for the whole map. {ask}")


def ensure_greeting(profile_id: str):
    """Seed the greeting into an empty conversation — once; a cleared
    conversation greets again on next open. Returns the history, or
    None when the profile does not exist."""
    p = get_profile(profile_id)
    if not p:
        return None
    if p.get("chat"):
        return p["chat"]
    return append_chat(profile_id, "assistant", greeting_text(p))


def list_profiles() -> list:
    return list(_load().values())


def get_profile(profile_id: str):
    return _load().get(profile_id)


# Keys that would put a second person (or a list of people) into one profile.
# A profile holds exactly ONE client; these are always rejected.
FORBIDDEN_PROFILE_KEYS = {"clients", "persons", "people", "second_client",
                          "additional_clients", "extra_clients", "other_clients"}


def update_profile(profile_id: str, patch: dict):
    """Patch the profile's ONE client. Returns (profile, error) — error is
    a message string when the patch tries to add a second person."""
    profiles = _load()
    p = profiles.get(profile_id)
    if not p:
        return None, None
    if any(k in patch for k in FORBIDDEN_PROFILE_KEYS):
        return None, "one person per profile: a profile holds exactly one client"
    if "name" in patch:
        p["client"]["name"] = patch["name"]
    client_patch = patch.get("client") or {}
    if not isinstance(client_patch, dict):
        return None, "client must be a single object, not a list"
    for k, v in client_patch.items():
        if k in p["client"]:
            p["client"][k] = v
    _save(profiles)
    return p, None


def delete_profile(profile_id: str) -> bool:
    profiles = _load()
    if profile_id not in profiles:
        return False
    del profiles[profile_id]
    _save(profiles)
    if get_active_profile_id() == profile_id:
        clear_active_profile()
    vs.delete_profile_docs(profile_id)
    import shutil
    shutil.rmtree(_docs_dir(profile_id), ignore_errors=True)
    return True


# ------------------------------------------------------- active profile
# The header is populated from the ACTIVE profile. The active profile id is
# persisted (active_profile.json) so the header survives a restart, and every
# read goes back to the store — so an edit or a switch is reflected at once,
# never stale, never hard-coded.
def _active_file() -> Path:
    return _data_dir() / "active_profile.json"


def get_active_profile_id():
    f = _active_file()
    if not f.exists():
        return None
    try:
        pid = json.loads(f.read_text()).get("profile_id")
    except (json.JSONDecodeError, OSError, AttributeError):
        return None
    return pid if pid in _load() else None


def set_active_profile(profile_id: str) -> bool:
    if profile_id not in _load():
        return False
    _active_file().write_text(json.dumps({"profile_id": profile_id}))
    return True


def clear_active_profile() -> None:
    _active_file().unlink(missing_ok=True)


def header_for(profile: dict) -> dict:
    """What the header shows for the active profile, read fresh from the
    profile record: client name, target roles, location/remote, workflow step."""
    c = profile["client"]
    w = workflow_state(profile)
    return {
        "profile_id": profile["id"],
        "client_name": c.get("name") or "",
        "target_roles": list(c.get("target_roles") or []),
        "current_role": c.get("current_role") or "",
        "location": c.get("location") or "",
        "remote_preference": c.get("remote_preference") or "",
        "employment_type": c.get("employment_type") or "",
        "current_step": w["current_step"],
        "interview_complete": profile["interview_step"] >= len(INTERVIEW_QUESTIONS),
    }


def get_active_profile():
    pid = get_active_profile_id()
    return get_profile(pid) if pid else None


# ------------------------------------------------------------- workflow
def workflow_state(profile: dict) -> dict:
    p = profile["client"]
    done = set(profile.get("workflow_done") or [])
    if profile["interview_step"] >= len(INTERVIEW_QUESTIONS):
        done.add("interview")
    if profile.get("documents"):
        done.add("documents")
    if p.get("target_roles") and p.get("location"):
        done.add("preferences")
    if profile.get("saved_jobs"):
        done.add("job_search")
    if any((j.get("application_status") or "saved") != "saved"
           for j in profile.get("saved_jobs") or []):
        done.add("applications")
    steps = [{"step": s, "done": s in done} for s in WORKFLOW_STEPS]
    current = next((s["step"] for s in steps if not s["done"]), "follow_up")
    return {"steps": steps, "current_step": current, "done": sorted(done)}


def mark_workflow_step(profile_id: str, step: str):
    if step not in WORKFLOW_STEPS:
        return None
    profiles = _load()
    p = profiles.get(profile_id)
    if not p:
        return None
    done = set(p.get("workflow_done") or [])
    done.add(step)
    p["workflow_done"] = sorted(done)
    _save(profiles)
    return workflow_state(p)


# ------------------------------------------------------------- interview
def _skills_question(profile: dict) -> str:
    """The skills question is built from the resume, live: it names the
    skills the resume gave us and asks for a confirmation — it never
    collects a typed list (see RESUME FIRST in the module docstring)."""
    skills = list(profile["client"].get("skills") or [])
    if skills:
        return ("Skills come from your resume, and your resume lists: "
                + ", ".join(skills)
                + ". I'll use exactly these for matching — reply 'yes' to "
                  "confirm them. If a skill is missing, it has to be on the "
                  "resume: update the file under Documents and I'll pull "
                  "the new list from there.")
    return ("Skills come from your resume — but I don't have a resume for "
            "this client yet. Add it under Documents first (that's step 1), "
            "then I'll confirm the skills it lists. Skills typed here are "
            "not used; matching always reads the resume.")


def _question_text(profile: dict, q: dict) -> str:
    return _skills_question(profile) if q["key"] == "skills" else q["question"]


def interview_status(profile: dict) -> dict:
    step = profile["interview_step"]
    if step >= len(INTERVIEW_QUESTIONS):
        return {"complete": True, "step": step, "total": len(INTERVIEW_QUESTIONS),
                "next_question": None,
                "summary": interview_summary(profile)}
    q = INTERVIEW_QUESTIONS[step]
    return {"complete": False, "step": step, "total": len(INTERVIEW_QUESTIONS),
            "next_question": _question_text(profile, q), "question_key": q["key"],
            "why": q.get("why", "")}


def interview_summary(profile: dict) -> str:
    p = profile["client"]
    bits = [f"Client: {p.get('name') or '(name not set yet)'} — seeking work"]
    if p.get("current_role"):
        bits.append(f"Current role: {p['current_role']}")
    if p.get("target_roles"):
        bits.append(f"Target roles: {', '.join(p['target_roles'])}")
    if p.get("skills"):
        bits.append(f"Skills: {', '.join(p['skills'])}")
    if p.get("location"):
        bits.append(f"Location: {p['location']} ({p.get('remote_preference') or 'preference not set'})")
    if p.get("employment_type"):
        bits.append(f"Type: {p['employment_type']}")
    return " | ".join(bits)


def _parse_answer(qkey: str, answer: str, client_data: dict) -> str:
    """Store the answer in the profile; return a short 'saved' confirmation."""
    a = (answer or "").strip()
    if qkey == "name":
        client_data["name"] = a
        return f"Saved: our client is {a} — this job search is for them."
    if qkey == "target_roles":
        client_data["target_roles"] = [s.strip() for s in re.split(r"[,;]", a) if s.strip()]
        return f"Saved target roles: {', '.join(client_data['target_roles'])}."
    if qkey == "skills":
        # Skills are NEVER written from an interview answer — they come
        # from the resume only (module docstring, RESUME FIRST). This
        # answer is a confirmation; the list it confirms is whatever the
        # documents currently digest to.
        skills = list(client_data.get("skills") or [])
        if skills:
            return ("Confirmed — matching uses exactly the skills from the "
                    f"resume: {', '.join(skills)}.")
        return ("Noted — but no resume skills are on file yet. Add the "
                "resume under Documents and its skills will be pulled from "
                "there; skills typed here aren't used.")
    if qkey == "work_history":
        client_data["work_history"] = [s.strip() for s in re.split(r"[;\n]", a) if s.strip()]
        return "Saved your work history."
    if qkey == "certifications":
        client_data["certifications"] = [s.strip() for s in re.split(r"[,;\n]", a) if s.strip()]
        return f"Saved certifications: {', '.join(client_data['certifications'])}."
    if qkey == "education":
        client_data["education"] = [s.strip() for s in re.split(r"[;\n]", a) if s.strip()]
        return "Saved your education."
    if qkey == "location":
        client_data["location"] = a
        low = a.lower()
        for pref in ("remote", "hybrid", "on-site", "onsite"):
            if pref in low:
                client_data["remote_preference"] = "remote" if pref == "remote" else ("hybrid" if pref == "hybrid" else "on-site")
                break
        return f"Saved location: {a}."
    if qkey == "employment_type":
        client_data["employment_type"] = a
        return f"Saved: {a}."
    if qkey == "salary":
        client_data["salary_text"] = a
        nums = re.findall(r"\$?\s?(\d[\d,]*)", a)
        if len(nums) >= 2:
            client_data["salary_min"], client_data["salary_max"] = nums[0], nums[1]
        elif len(nums) == 1:
            client_data["salary_min"] = nums[0]
        return f"Saved salary expectations: {a}."
    if qkey == "cover_letter":
        client_data["cover_letter_highlights"] = a
        return "Saved what to highlight in cover letters."
    client_data[qkey] = a
    return f"Saved: {a}."


def answer_interview(profile_id: str, answer: str) -> dict:
    profiles = _load()
    p = profiles.get(profile_id)
    if not p:
        return {"error": "profile not found"}
    step = p["interview_step"]
    if step >= len(INTERVIEW_QUESTIONS):
        return {"complete": True, "saved": "", "next_question": None,
                "summary": interview_summary(p)}
    q = INTERVIEW_QUESTIONS[step]
    if not (answer or "").strip():
        return {"error": "answer was empty — nothing was saved",
                "complete": False, "saved": "", "next_question": _question_text(p, q),
                "step": step, "total": len(INTERVIEW_QUESTIONS)}
    saved = _parse_answer(q["key"], answer, p["client"])
    p["interview_answers"][q["key"]] = (answer or "").strip()
    p["interview_step"] = step + 1
    _save(profiles)
    # Index the answer in RAG so the concierge can retrieve it later.
    vs.upsert_profile_text(profile_id, f"interview-{q['key']}",
                          f"{q['question']} Answer: {answer}",
                          kind="interview")
    st = interview_status(p)
    return {"complete": st["complete"], "saved": saved,
            "next_question": st["next_question"],
            "step": p["interview_step"], "total": len(INTERVIEW_QUESTIONS),
            "summary": st.get("summary") if st["complete"] else None}


# ------------------------------------------------------------- documents
def extract_text(data: bytes, filename: str) -> str:
    name = (filename or "").lower()
    if name.endswith((".txt", ".md", ".csv")):
        return data.decode("utf-8", errors="ignore")
    if name.endswith(".docx"):
        try:
            with zipfile.ZipFile(BytesIO(data)) as z:
                xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
            xml = re.sub(r"</w:p>", "\n", xml)
            return re.sub(r"<[^>]+>", "", xml)
        except Exception:  # noqa: BLE001 - fall through to empty text
            return ""
    if name.endswith(".pdf"):
        return _extract_pdf_text(data)
    return data.decode("utf-8", errors="ignore")


def _pdf_stream_bytes(data: bytes):
    """Yield each stream's bytes, FlateDecode-decoded when possible."""
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        raw = m.group(1)
        try:
            yield zlib.decompress(raw)
        except Exception:  # noqa: BLE001 - stream was not compressed
            yield raw


def _parse_tounicode(cmap: bytes) -> dict:
    """Parse a ToUnicode CMap (bfchar + bfrange) into {cid: text}."""
    text = cmap.decode("latin-1", errors="ignore")
    mapping = {}

    def _dst(hexs: str) -> str:
        raw = bytes.fromhex(hexs + ("0" if len(hexs) % 2 else ""))
        if len(raw) >= 2 and len(raw) % 2 == 0:
            try:
                return raw.decode("utf-16-be")
            except Exception:  # noqa: BLE001
                pass
        return raw.decode("latin-1", errors="replace")

    for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            mapping[int(src, 16)] = _dst(dst)
    for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        for lo, hi, dst in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            base = _dst(dst)
            if len(base) == 1:
                lo_i = int(lo, 16)
                for code in range(lo_i, int(hi, 16) + 1):
                    cp = ord(base) + code - lo_i
                    if 0 <= cp <= 0x10FFFF:
                        mapping[code] = chr(cp)
        for lo, hi, arr in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[([^\]]*)\]", block):
            for i, dst in enumerate(re.findall(r"<([0-9A-Fa-f]+)>", arr)):
                mapping[int(lo, 16) + i] = _dst(dst)
    return mapping


def _pdf_font_maps(data: bytes) -> dict:
    """Map /Fxx resource names to their font's ToUnicode map.

    Generated PDFs (Coursera-style certificates above all) show text as
    2-byte CIDs under Type0/Identity-H fonts; the bytes are meaningless
    without the font's ToUnicode CMap. This scans the classic object
    layout — font objects, their /ToUnicode references, and the /Font
    resource dictionaries that bind names to fonts.
    """
    cmap_by_obj = {}
    font_unicode = {}
    font_by_name = {}
    for m in re.finditer(rb"(\d+)\s+\d+\s+obj\b(.*?)endobj", data, re.S):
        num, body = int(m.group(1)), m.group(2)
        sm = re.search(rb"stream\r?\n(.*?)endstream", body, re.S)
        if sm:
            raw = sm.group(1)
            try:
                dec = zlib.decompress(raw)
            except Exception:  # noqa: BLE001
                dec = raw
            if b"begincmap" in dec or b"beginbf" in dec:
                try:
                    cmap_by_obj[num] = _parse_tounicode(dec)
                except Exception:  # noqa: BLE001 - one malformed CMap must
                    cmap_by_obj[num] = {}  # never fail the whole upload
        tu = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", body)
        if tu:
            font_unicode[num] = int(tu.group(1))
        fm = re.search(rb"/Font\s*<<(.*?)>>", body, re.S)
        if fm:
            for name, ref in re.findall(rb"/(F\w+)\s+(\d+)\s+\d+\s+R", fm.group(1)):
                font_by_name[name.decode("latin-1")] = int(ref)
    out = {}
    for name, fobj in font_by_name.items():
        cmap = cmap_by_obj.get(font_unicode.get(fobj))
        if cmap:
            out[name] = cmap
    return out


def _unescape_literal(raw: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == 0x5C and i + 1 < len(raw):  # backslash escape
            nxt = raw[i + 1]
            simple = {0x6E: 0x0A, 0x72: 0x0D, 0x74: 0x09, 0x62: 0x08,
                      0x66: 0x0C, 0x28: 0x28, 0x29: 0x29, 0x5C: 0x5C}
            if nxt in simple:
                out.append(simple[nxt])
                i += 2
                continue
            if 0x30 <= nxt <= 0x37:  # up to 3 octal digits
                j = i + 1
                val = 0
                while j < len(raw) and j < i + 4 and 0x30 <= raw[j] <= 0x37:
                    val = val * 8 + (raw[j] - 0x30)
                    j += 1
                out.append(val & 0xFF)
                i = j
                continue
            i += 1  # escaped newline / unknown escape: drop the backslash
            continue
        out.append(c)
        i += 1
    return bytes(out)


def _decode_pdf_bytes(raw: bytes, cmap) -> str:
    """Decode shown-text bytes: through the font's ToUnicode map when the
    font has one (2-byte CIDs), else UTF-16BE when it looks like it, else
    latin-1 (simple-font literal text)."""
    if cmap:
        return "".join(cmap.get((raw[i] << 8) | raw[i + 1], "")
                       for i in range(0, len(raw) - 1, 2))
    if raw[:2] == b"\xfe\xff":
        return raw[2:].decode("utf-16-be", errors="replace")
    if len(raw) >= 4 and len(raw) % 2 == 0 and raw[0] == 0 and raw[2] == 0:
        try:
            t = raw.decode("utf-16-be")
            if sum(c.isprintable() or c in "\n\r\t" for c in t) >= 0.9 * len(t):
                return t
        except Exception:  # noqa: BLE001
            pass
    return raw.decode("latin-1", errors="replace")


def _hex_bytes(hexs: bytes) -> bytes:
    """PDF hex strings may have an odd number of digits (the last nibble
    is padded with 0) — bytes.fromhex alone would raise on those."""
    s = hexs.decode("latin-1").strip()
    if len(s) % 2:
        s += "0"
    return bytes.fromhex(s)


def _tj_array_text(arr: bytes, cmap) -> str:
    parts = []
    for m in re.finditer(rb"\((?:\\.|[^()\\])*\)|<([0-9A-Fa-f\s]+)>|(-?\d+(?:\.\d+)?)", arr):
        tok = m.group(0)
        if tok.startswith(b"("):
            parts.append(_decode_pdf_bytes(_unescape_literal(tok[1:-1]), cmap))
        elif tok.startswith(b"<"):
            parts.append(_decode_pdf_bytes(_hex_bytes(m.group(1)), cmap))
        elif m.group(2) is not None and float(m.group(2)) < -150:
            parts.append(" ")  # a large negative kern is a word gap
    return "".join(parts)


_PDF_TOKEN = re.compile(rb"""
    /(?P<font>[A-Za-z0-9]+)\s+[\d.]+\s+Tf
  | \((?P<lit>(?:\\.|[^()\\])*)\)\s*(?P<lop>Tj|'|")
  | <(?P<hex>[0-9A-Fa-f\s]+)>\s*(?P<hop>Tj|'|")
  | \[(?P<arr>(?:\\.|[^\\\]])*)\]\s*TJ
  | (?P<tdx>-?[\d.]+)\s+(?P<tdy>-?[\d.]+)\s+(?:Td|TD)\b
  | (?P<move>\bT\*|\bTm\b)
""", re.X)


def _pdf_content_text(content: bytes, font_maps: dict) -> str:
    out = []
    cmap = None
    for m in _PDF_TOKEN.finditer(content):
        if m.group("font"):
            cmap = font_maps.get(m.group("font").decode("latin-1"))
        elif m.group("lit") is not None:
            if m.group("lop") in (b"'", b'"'):
                out.append("\n")
            out.append(_decode_pdf_bytes(_unescape_literal(m.group("lit")), cmap))
        elif m.group("hex") is not None:
            if m.group("hop") in (b"'", b'"'):
                out.append("\n")
            out.append(_decode_pdf_bytes(_hex_bytes(m.group("hex")), cmap))
        elif m.group("arr") is not None:
            out.append(_tj_array_text(m.group("arr"), cmap))
        elif m.group("tdy") is not None:
            # A Td with no vertical move is a per-glyph advance along the
            # SAME line (generated certificates position every glyph this
            # way) — only a vertical move starts a new line.
            if float(m.group("tdy")) != 0:
                out.append("\n")
        elif m.group("move"):
            out.append("\n")
    return "".join(out)


def _extract_pdf_text(data: bytes) -> str:
    """Extract a PDF's text the way it is actually encoded: content
    streams tokenized for Tj/TJ, strings decoded through each font's
    ToUnicode CMap. (The pre-2026-11-21 scrape — every parenthesized run
    in every stream, latin-1 — returned image bytes as garbage on real
    certificates and none of their text.)"""
    font_maps = _pdf_font_maps(data)
    parts = []
    for content in _pdf_stream_bytes(data):
        if b"Tj" not in content and b"TJ" not in content:
            continue
        t = _pdf_content_text(content, font_maps)
        if t.strip():
            parts.append(t)
    text = "\n".join(parts)
    if text.strip():
        return text
    # Last resort for odd files the tokenizer missed: the old scrape.
    out = []
    for raw in _pdf_stream_bytes(data):
        for t in re.findall(rb"\((?:[^()\\]|\\.)*\)", raw):
            try:
                out.append(t[1:-1].decode("latin-1"))
            except Exception:  # noqa: BLE001
                pass
    return " ".join(out)


def _coursera_title(lines: list, low_lines: list) -> str:
    """The credential on a Coursera-style certificate, read from the
    layout's own anchors. The old longest-line-in-a-window heuristic
    kept landing on the signatory's job title ('Engineering Manager
    and AI Specialist', 'Associate Professor, Department of...') and
    truncating titles that wrap two lines. Two forms:
    - Professional Certificate: the completion sentence names it and
      the program name follows on its own line ('IBM AI Engineering'
      under '...Professional Certificate').
    - Course: the title is the block of lines directly above the
      'an online non-credit course authorized by...' line, under the
      date and the recipient's name (name lines come first in the
      block and read as one to three capitalized words)."""
    idx = next((i for i, l in enumerate(low_lines)
                if "successfully completed" in l), None)
    if idx is None:
        return ""
    block = " ".join(low_lines[idx:idx + 3]).replace("ﬁ", "fi")
    if "professional" in block and "certificate" in block:
        for k in range(idx + 1, min(idx + 5, len(lines))):
            cand = lines[k].strip()
            if cand.lower().replace("ﬁ", "fi") in (
                    "certificate", "professional certificate"):
                continue
            if len(cand) >= 3:
                return (cand if "certificate" in cand.lower()
                        else cand + " Professional Certificate")
    j = next((i for i, l in enumerate(low_lines)
              if "non-credit" in l and "authorized" in l and i <= idx), None)
    if j is None:
        return ""
    block_lines = []
    for k in range(j - 1, -1, -1):
        if re.search(r"\b(19|20)\d{2}\b", lines[k]):
            break
        block_lines.append(lines[k])
        if len(block_lines) >= 5:
            break
    block_lines.reverse()

    def _name_like(s: str) -> bool:
        ws = s.split()
        return (1 <= len(ws) <= 3
                and all(w[:1].isupper() and not any(c.isdigit() for c in w)
                        for w in ws))

    while len(block_lines) > 1 and _name_like(block_lines[0]):
        block_lines.pop(0)
    title = " ".join(block_lines).strip()
    if 8 <= len(title) <= 120 and len(title.split()) >= 2:
        return title
    return ""


def digest_text(text: str) -> dict:
    """Pull structured facts out of a document's text into the profile."""
    low = text.lower()
    found = {
        "email": (re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text) or [None])[0] or "",
        "phone": (re.search(r"(\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}", text) or [None])[0] or "",
        "skills": sorted({s for s, pat in _SKILL_PATTERNS.items() if pat.search(low)}),
        "certifications": [],
        "education": [],
        "years": sorted(set(re.findall(r"\b(?:19|20)\d{2}\b", text))),
    }
    for line in text.splitlines():
        l = line.strip()
        if not l:
            continue
        ll = l.lower()
        if "certif" in ll or "aws certified" in ll or "ibm" in ll and "certificate" in ll:
            # Store the credential, not its label: "Certifications: X"
            # reads as "X" everywhere the record is used (letters too).
            l = re.sub(r"(?i)^(certifications?|certs?)\s*:\s*", "", l)
            found["certifications"].append(l[:160])
        if any(k in ll for k in ("bachelor", "master", "a.a.s", "aas ", "degree", "university", "college")):
            found["education"].append(l[:160])
    # Certificate documents: the credential IS the course/program title,
    # which usually sits near the completion sentence and does not itself
    # contain the word "certificate" (e.g. "Python for Data Science, AI &
    # Development" under "has successfully completed"). Take the longest
    # plausible title line in the window around that sentence, skipping
    # boilerplate (authorization / verify / identity lines) and names.
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    low_lines = [l.lower() for l in lines]
    if not found["certifications"]:
        coursera = _coursera_title(lines, low_lines)
        if coursera:
            found["certifications"].append(coursera)
    if not found["certifications"] and any(
            "successfully completed" in l or "certificate of" in l for l in low_lines):
        boiler = ("successfully completed", "non-credit", "authorized",
                  "verify", "http", "confirmed the identity", "participation",
                  "certificate", "instructor", "director")
        for idx, l in enumerate(low_lines):
            if "successfully completed" in l or "certificate of" in l:
                window = lines[max(0, idx - 5): idx + 6]
                cands = [c for c in window
                         if 8 <= len(c) <= 120 and len(c.split()) >= 2
                         and not any(b in c.lower() for b in boiler)
                         and not re.search(r"\b(19|20)\d{2}\b", c)]
                if cands:
                    title = max(cands, key=len)[:160]
                    if title not in found["certifications"]:
                        found["certifications"].append(title)
                break
    found["certifications"] = found["certifications"][:10]
    found["education"] = found["education"][:10]
    return found


def _resume_skills(profile: dict) -> list:
    """The client's skills: exactly the skills used or referenced in
    their documents — the sorted union of every document's digested
    skills. Recomputed (never merged with typed-in values) on every
    document add / replace / delete, so the list can shrink as well as
    grow and always matches what the resume actually says."""
    out = set()
    for d in profile.get("documents") or []:
        out.update((d.get("digest") or {}).get("skills") or [])
    return sorted(out)


def _merge_digest(profile: dict, digest: dict) -> None:
    p = profile["client"]
    if digest["email"] and not p.get("email"):
        p["email"] = digest["email"]
    if digest["phone"] and not p.get("phone"):
        p["phone"] = digest["phone"]
    for c in digest["certifications"]:
        if c not in p["certifications"]:
            p["certifications"].append(c)
    for e in digest["education"]:
        if e not in p["education"]:
            p["education"].append(e)
    # Skills are resume-sourced only (module docstring, RESUME FIRST):
    # recompute from all documents rather than unioning with whatever
    # the client record happened to hold.
    p["skills"] = _resume_skills(profile)


# File types the document pipeline can actually read. Anything else is
# rejected at upload instead of being stored as garbage text.
ALLOWED_UPLOAD_SUFFIXES = {".txt", ".md", ".csv", ".docx", ".pdf"}


def add_document(profile_id: str, filename: str, data: bytes) -> dict:
    profiles = _load()
    p = profiles.get(profile_id)
    if not p:
        return {"error": "profile not found"}
    # Sanitize: strip any directory components so a crafted name like
    # "../../x.txt" can never escape the profile's docs folder.
    safe_name = Path(filename or "").name.strip()
    if not safe_name:
        return {"error": "a file name is required"}
    if Path(safe_name).suffix.lower() not in ALLOWED_UPLOAD_SUFFIXES:
        return {"error": f"unsupported file type: {Path(safe_name).suffix or '(none)'} — upload .txt, .md, .csv, .docx or .pdf"}
    doc_id = uuid.uuid4().hex[:12]
    path = _docs_dir(profile_id) / f"{doc_id}-{safe_name}"
    path.write_bytes(data)
    text = extract_text(data, safe_name)
    digest = digest_text(text)
    doc = {"id": doc_id, "filename": safe_name, "title": safe_name,
           "size": len(data), "text_chars": len(text), "digest": digest,
           "notes": ""}
    p["documents"].append(doc)
    _merge_digest(p, digest)
    _save(profiles)
    vs.upsert_profile_chunks(profile_id, doc_id, text)
    return {"document": doc, "extracted": digest, "text_chars": len(text)}


def edit_document(profile_id: str, doc_id: str, patch: dict, data: bytes = None,
                  filename: str = None) -> dict:
    """Edit = rename title / notes, or replace the file (re-digest + re-index)."""
    profiles = _load()
    p = profiles.get(profile_id)
    if not p:
        return {"error": "profile not found"}
    doc = next((d for d in p["documents"] if d["id"] == doc_id), None)
    if not doc:
        return {"error": "document not found"}
    if "title" in patch:
        doc["title"] = patch["title"]
    if "notes" in patch:
        doc["notes"] = patch["notes"]
    if data is not None:
        vs.delete_profile_doc_chunks(profile_id, doc_id)
        new_name = Path(filename or doc["filename"]).name.strip() or doc["filename"]
        if Path(new_name).suffix.lower() not in ALLOWED_UPLOAD_SUFFIXES:
            return {"error": f"unsupported file type: {Path(new_name).suffix or '(none)'} — upload .txt, .md, .csv, .docx or .pdf"}
        # Remove the old stored file(s) first so a replaced version does
        # not linger on disk under the old name.
        for stale in _docs_dir(profile_id).glob(f"{doc_id}-*"):
            stale.unlink(missing_ok=True)
        path = _docs_dir(profile_id) / f"{doc_id}-{new_name}"
        path.write_bytes(data)
        text = extract_text(data, new_name)
        digest = digest_text(text)
        doc.update({"filename": new_name, "size": len(data),
                    "text_chars": len(text), "digest": digest})
        _merge_digest(p, digest)
        vs.upsert_profile_chunks(profile_id, doc_id, text)
    _save(profiles)
    return {"document": doc}


def redigest_document(profile_id: str, doc_id: str) -> dict:
    """Re-run extraction + digestion on the document's stored file and
    re-index its chunks — how documents uploaded under an older, weaker
    extractor (certificates whose text it could not read) get repaired
    in place, with no re-upload."""
    profiles = _load()
    p = profiles.get(profile_id)
    if not p:
        return {"error": "profile not found"}
    doc = next((d for d in p["documents"] if d["id"] == doc_id), None)
    if not doc:
        return {"error": "document not found"}
    stored = sorted(_docs_dir(profile_id).glob(f"{doc_id}-*"))
    if not stored:
        return {"error": "the stored file is missing — re-upload the document"}
    data = stored[0].read_bytes()
    text = extract_text(data, doc["filename"])
    digest = digest_text(text)
    doc.update({"size": len(data), "text_chars": len(text), "digest": digest})
    _merge_digest(p, digest)
    _save(profiles)
    vs.delete_profile_doc_chunks(profile_id, doc_id)
    vs.upsert_profile_chunks(profile_id, doc_id, text)
    return {"document": doc, "extracted": digest, "text_chars": len(text)}


VIEW_TEXT_CAP = 100_000


def _stored_file(profile_id: str, doc_id: str):
    stored = sorted(_docs_dir(profile_id).glob(f"{doc_id}-*"))
    return stored[0] if stored else None


def view_document(profile_id: str, doc_id: str) -> dict:
    """Read-only view of a document (Anthony, 2026-11-22: "clicking a
    document views a document"). The stored file is re-extracted on
    demand — nothing is saved, merged or re-indexed — and its text is
    returned with the digest, so the UI shows exactly what the app
    read from the file."""
    p = get_profile(profile_id)
    if not p:
        return {"error": "profile not found"}
    doc = next((d for d in p["documents"] if d["id"] == doc_id), None)
    if not doc:
        return {"error": "document not found"}
    path = _stored_file(profile_id, doc_id)
    if path is None:
        return {"error": "the stored file is missing — re-upload the document"}
    text = extract_text(path.read_bytes(), doc["filename"])
    return {"document": doc, "text": text[:VIEW_TEXT_CAP],
            "truncated": len(text) > VIEW_TEXT_CAP,
            "text_chars": len(text)}


def document_file(profile_id: str, doc_id: str) -> dict:
    """Locate the stored original so it can be served for viewing."""
    p = get_profile(profile_id)
    if not p:
        return {"error": "profile not found"}
    doc = next((d for d in p["documents"] if d["id"] == doc_id), None)
    if not doc:
        return {"error": "document not found"}
    path = _stored_file(profile_id, doc_id)
    if path is None:
        return {"error": "the stored file is missing — re-upload the document"}
    return {"path": path, "filename": doc["filename"]}


def delete_document(profile_id: str, doc_id: str) -> bool:
    profiles = _load()
    p = profiles.get(profile_id)
    if not p:
        return False
    doc = next((d for d in p["documents"] if d["id"] == doc_id), None)
    if not doc:
        return False
    p["documents"] = [d for d in p["documents"] if d["id"] != doc_id]
    # The deleted document's skills leave with it (resume-sourced only).
    p["client"]["skills"] = _resume_skills(p)
    _save(profiles)
    vs.delete_profile_doc_chunks(profile_id, doc_id)
    for f in _docs_dir(profile_id).glob(f"{doc_id}-*"):
        f.unlink(missing_ok=True)
    return True


def list_documents(profile_id: str):
    p = get_profile(profile_id)
    return None if p is None else p["documents"]
