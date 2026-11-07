from backend.vector_store import get_jobs_collection, search_jobs_text, upsert_jobs


def test_embedded_chroma_init_and_roundtrip():
    col = get_jobs_collection()
    assert col.count() == 0
    n = upsert_jobs([{"id": "c1", "title": "Python Developer", "company": "Beta",
                      "location": "New York", "source": "usajobs",
                      "url": "", "snippet": "FastAPI and ChromaDB"}])
    assert n == 1
    assert get_jobs_collection().count() == 1
    found = search_jobs_text("Python FastAPI")
    assert len(found) == 1
    assert found[0]["id"] == "c1"


def test_search_empty_store():
    assert search_jobs_text("anything") == []
