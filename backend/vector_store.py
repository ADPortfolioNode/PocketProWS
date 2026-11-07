"""Embedded ChromaDB — PersistentClient only, no HTTP server, no Docker.

Single worker/process only: the embedded folder must never be opened by two
processes at once (same constraint as funkStudio / the Asura reseller plan).
"""
import chromadb

from . import config
from .config import JOBS_COLLECTION

_client = None


def get_client():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=config.CHROMA_PATH)
    return _client


def get_jobs_collection():
    return get_client().get_or_create_collection(
        name=JOBS_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


def upsert_jobs(jobs):
    """jobs: list of dicts with id, title, company, location, source, url, snippet."""
    if not jobs:
        return 0
    col = get_jobs_collection()
    col.upsert(
        ids=[j["id"] for j in jobs],
        documents=[f"{j.get('title','')} at {j.get('company','')}. {j.get('snippet','')}" for j in jobs],
        metadatas=[{k: str(v) for k, v in j.items() if k != "id"} for j in jobs],
    )
    return len(jobs)


def search_jobs_text(query, n=5):
    col = get_jobs_collection()
    if col.count() == 0:
        return []
    res = col.query(query_texts=[query], n_results=min(n, col.count()))
    out = []
    for i, doc in enumerate(res["documents"][0]):
        meta = res["metadatas"][0][i]
        out.append({"id": res["ids"][0][i], "text": doc, **meta})
    return out


# ------------------------------------------------- per-client RAG store
# One collection for ALL clients, filtered by profile_id metadata — that is
# what makes per-client isolation a query-time guarantee, not a hope:
# every client-scoped query passes where={"profile_id": <id>}.
PROFILES_COLLECTION = "pocketprows_profiles"


def get_profiles_collection():
    return get_client().get_or_create_collection(
        name=PROFILES_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


def _chunks(text, size=1200):
    text = (text or "").strip()
    return [text[i:i + size] for i in range(0, len(text), size)] or []


def upsert_profile_chunks(profile_id, doc_id, text):
    chunks = _chunks(text)
    if not chunks:
        return 0
    col = get_profiles_collection()
    col.upsert(
        ids=[f"{profile_id}-{doc_id}-{i}" for i in range(len(chunks))],
        documents=chunks,
        metadatas=[{"profile_id": profile_id, "doc_id": doc_id, "kind": "document"}
                   for _ in chunks],
    )
    return len(chunks)


def upsert_profile_text(profile_id, item_id, text, kind="interview"):
    col = get_profiles_collection()
    col.upsert(
        ids=[f"{profile_id}-{item_id}"],
        documents=[text],
        metadatas=[{"profile_id": profile_id, "doc_id": item_id, "kind": kind}],
    )
    return 1


def search_profile_text(profile_id, query, n=5):
    """Retrieval scoped to ONE profile — profile A's data never leaks to B."""
    col = get_profiles_collection()
    if col.count() == 0:
        return []
    res = col.query(query_texts=[query], n_results=min(n, col.count()),
                    where={"profile_id": profile_id})
    out = []
    for i, doc in enumerate(res["documents"][0]):
        meta = res["metadatas"][0][i]
        out.append({"id": res["ids"][0][i], "text": doc, **meta})
    return out


def delete_profile_doc_chunks(profile_id, doc_id):
    col = get_profiles_collection()
    try:
        col.delete(where={"$and": [{"profile_id": profile_id}, {"doc_id": doc_id}]})
    except Exception:  # noqa: BLE001 - best effort; a missing doc is fine
        pass


def delete_profile_docs(profile_id):
    col = get_profiles_collection()
    try:
        col.delete(where={"profile_id": profile_id})
    except Exception:  # noqa: BLE001 - best effort
        pass
