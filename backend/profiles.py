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

Storage: profiles.json + documents/ + active_profile.json live under
CHROMA_PATH (the same data directory as Chroma, so tests that redirect
CHROMA_PATH stay isolated). Single process only, like the rest of
PocketProWS.
Single process only, like the rest of PocketProWS.
"""
import json
import re
import uuid
import zipfile
import zlib
from io import BytesIO
from pathlib import Path

from . import config as cfg
from . import vector_store as vs

WORKFLOW_STEPS = ["interview", "documents", "preferences",
                  "job_search", "applications", "follow_up"]

# One question at a time. First question establishes WHO the search is for.
INTERVIEW_QUESTIONS = [
    {"key": "name", "field": "name",
     "question": "Hi! I'm your recruiter concierge — friendly help, one question at a time. First, who is our client? What's the full name of the person seeking work? (The client seeks work; the employer hires.)"},
    {"key": "current_role", "field": "current_role",
     "question": "Thanks! What do you do now — your current or most recent role?"},
    {"key": "target_roles", "field": "target_roles",
     "question": "What roles are you targeting? For example: AI Engineer, Web Developer, or AI Developer."},
    {"key": "skills", "field": "skills",
     "question": "What are your top skills and technologies? (Python, React, RAG, LangChain — whatever applies.)"},
    {"key": "work_history", "field": "work_history",
     "question": "Tell me about your work history — employers, roles, and dates, briefly. One or two sentences per job is fine."},
    {"key": "certifications", "field": "certifications",
     "question": "Any certifications or courses? For example: IBM AI Engineering, AWS, or a degree course."},
    {"key": "education", "field": "education",
     "question": "What's your education background? (School, degree, year — whatever you have.)"},
    {"key": "location", "field": "location",
     "question": "Where are you based, and do you want remote, hybrid, or on-site work?"},
    {"key": "employment_type", "field": "employment_type",
     "question": "Full-time, contract, or either?"},
    {"key": "salary", "field": "salary",
     "question": "What salary or hourly rate are you aiming for? It's fine to say 'not sure yet'."},
    {"key": "cover_letter", "field": "cover_letter_highlights",
     "question": "Last one for now — for cover letters, what should I highlight about you, and what tone do you like? (For example: confident and direct, or warm and friendly.)"},
]

KNOWN_SKILLS = ["python", "fastapi", "flask", "react", "javascript", "typescript",
                "langchain", "langgraph", "rag", "chromadb", "pinecone", "faiss",
                "docker", "aws", "gcp", "azure", "gemini", "groq", "ollama",
                "openai", "sql", "postgres", "mongodb", "redis", "node", "vite",
                "next.js", "html", "css", "git", "ci/cd", "kubernetes", "terraform",
                "machine learning", "deep learning", "pytorch", "tensorflow",
                "nlp", "embeddings", "vector", "api", "rest", "graphql"]


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


def _load() -> dict:
    f = _profiles_file()
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save(profiles: dict) -> None:
    _profiles_file().write_text(json.dumps(profiles, indent=2))


def _blank_client() -> dict:
    return {"name": "", "current_role": "", "target_roles": [], "skills": [],
            "work_history": [], "certifications": [], "education": [],
            "location": "", "remote_preference": "", "employment_type": "",
            "salary_min": "", "salary_max": "", "salary_text": "",
            "cover_letter_tone": "", "cover_letter_highlights": "",
            "email": "", "phone": "", "linkedin": "", "github": ""}


def create_profile(name: str = "") -> dict:
    profiles = _load()
    pid = uuid.uuid4().hex[:12]
    client_data = _blank_client()
    client_data["name"] = name or ""
    profile = {"id": pid, "client": client_data,
               "interview_step": 0, "interview_answers": {},
               "documents": [], "saved_jobs": [],
               "workflow_done": []}
    profiles[pid] = profile
    _save(profiles)
    # First profile becomes the active one, so the header has something to show.
    if not _active_file().exists():
        set_active_profile(pid)
    return profile


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
def interview_status(profile: dict) -> dict:
    step = profile["interview_step"]
    if step >= len(INTERVIEW_QUESTIONS):
        return {"complete": True, "step": step, "total": len(INTERVIEW_QUESTIONS),
                "next_question": None,
                "summary": interview_summary(profile)}
    q = INTERVIEW_QUESTIONS[step]
    return {"complete": False, "step": step, "total": len(INTERVIEW_QUESTIONS),
            "next_question": q["question"], "question_key": q["key"]}


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
        client_data["skills"] = [s.strip() for s in re.split(r"[,;]", a) if s.strip()]
        return f"Saved skills: {', '.join(client_data['skills'])}."
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


def _extract_pdf_text(data: bytes) -> str:
    """Best-effort PDF text: decompress streams, pull (text) Tj / [...] TJ."""
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        raw = m.group(1)
        try:
            raw = zlib.decompress(raw)
        except Exception:  # noqa: BLE001 - stream was not compressed
            pass
        for t in re.findall(rb"\((?:[^()\\]|\\.)*\)", raw):
            try:
                out.append(t[1:-1].decode("latin-1"))
            except Exception:  # noqa: BLE001
                pass
    return " ".join(out)


def digest_text(text: str) -> dict:
    """Pull structured facts out of a document's text into the profile."""
    low = text.lower()
    found = {
        "email": (re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text) or [None])[0] or "",
        "phone": (re.search(r"(\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}", text) or [None])[0] or "",
        "skills": sorted({s for s in KNOWN_SKILLS if s in low}),
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
            found["certifications"].append(l[:160])
        if any(k in ll for k in ("bachelor", "master", "a.a.s", "aas ", "degree", "university", "college")):
            found["education"].append(l[:160])
    found["certifications"] = found["certifications"][:10]
    found["education"] = found["education"][:10]
    return found


def _merge_digest(profile: dict, digest: dict) -> None:
    p = profile["client"]
    if digest["email"] and not p.get("email"):
        p["email"] = digest["email"]
    if digest["phone"] and not p.get("phone"):
        p["phone"] = digest["phone"]
    for s in digest["skills"]:
        if s not in p["skills"]:
            p["skills"].append(s)
    for c in digest["certifications"]:
        if c not in p["certifications"]:
            p["certifications"].append(c)
    for e in digest["education"]:
        if e not in p["education"]:
            p["education"].append(e)


def add_document(profile_id: str, filename: str, data: bytes) -> dict:
    profiles = _load()
    p = profiles.get(profile_id)
    if not p:
        return {"error": "profile not found"}
    doc_id = uuid.uuid4().hex[:12]
    path = _docs_dir(profile_id) / f"{doc_id}-{filename}"
    path.write_bytes(data)
    text = extract_text(data, filename)
    digest = digest_text(text)
    doc = {"id": doc_id, "filename": filename, "title": filename,
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
        new_name = filename or doc["filename"]
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


def delete_document(profile_id: str, doc_id: str) -> bool:
    profiles = _load()
    p = profiles.get(profile_id)
    if not p:
        return False
    doc = next((d for d in p["documents"] if d["id"] == doc_id), None)
    if not doc:
        return False
    p["documents"] = [d for d in p["documents"] if d["id"] != doc_id]
    _save(profiles)
    vs.delete_profile_doc_chunks(profile_id, doc_id)
    for f in _docs_dir(profile_id).glob(f"{doc_id}-*"):
        f.unlink(missing_ok=True)
    return True


def list_documents(profile_id: str):
    p = get_profile(profile_id)
    return None if p is None else p["documents"]
