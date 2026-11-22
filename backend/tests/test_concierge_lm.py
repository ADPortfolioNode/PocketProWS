"""Concierge LM layer + greeting (Anthony, 2026-11-22): with a rung
configured, Q&A answers are composed by the LM from the retrieved
material only; when the rung fails, the answer falls back to the
quoted material and says why; keyless behavior is unchanged. And an
empty conversation opens with the concierge's greeting — seeded
once, carrying the client's name, position, and a question."""
from fastapi.testclient import TestClient

from backend.main import app
from backend import llm as llm_mod

client = TestClient(app)

RESUME = (b"Anthony Dickerson\nPython and React developer in Queens.\n"
          b"Built recruiter tools with FastAPI and ChromaDB.\n")


def _profile_with_resume(name="LM Client"):
    p = client.post("/api/profiles", json={"name": name}).json()
    pid = p["id"]
    up = client.post(f"/api/profiles/{pid}/documents",
                     files={"file": ("resume.txt", RESUME, "text/plain")})
    assert up.status_code == 200, up.text
    return pid


def _ask(pid, q="What Python experience is on file?"):
    r = client.post("/api/chat", json={"message": q, "profile_id": pid})
    assert r.status_code == 200, r.text
    return r.json()


def test_greeting_seeded_once_with_name_position_and_question():
    pid = _profile_with_resume("Greeting Client")
    r = client.get(f"/api/profiles/{pid}/chat")
    msgs = r.json()["messages"]
    assert len(msgs) == 1
    g = msgs[0]
    assert g["role"] == "assistant"
    assert "your concierge" in g["text"] and "Greeting Client" in g["text"]
    # The resume is already in, so Documents is done and the greeting
    # meets the client at the Interview step.
    assert "step 2 of 6" in g["text"] and "interview" in g["text"]
    assert g["text"].rstrip().endswith("?")
    again = client.get(f"/api/profiles/{pid}/chat").json()["messages"]
    assert len(again) == 1  # seeded once, not on every open


def test_greeting_returns_after_clear():
    pid = _profile_with_resume()
    client.get(f"/api/profiles/{pid}/chat")
    client.delete(f"/api/profiles/{pid}/chat")
    msgs = client.get(f"/api/profiles/{pid}/chat").json()["messages"]
    assert len(msgs) == 1 and "your concierge" in msgs[0]["text"]


def test_llm_status_endpoint():
    r = client.get("/api/llm/status")
    assert r.status_code == 200
    assert "providers" in r.json() and "fallback" in r.json()


def test_lm_composes_from_material(monkeypatch):
    pid = _profile_with_resume()
    monkeypatch.setattr(llm_mod, "generate", lambda prompt: {
        "text": "The resume shows Python and React experience, including FastAPI tools.",
        "provider": "gemini", "errors": {}})
    res = _ask(pid)
    assert res["mode"] == "llm" and res["provider"] == "gemini"
    assert "Python and React experience" in res["answer"]
    assert "gemini composed this from" in res["answer"]
    assert "grounded only in that saved material" in res["answer"]


def test_lm_failure_falls_back_to_quotes_and_says_why(monkeypatch):
    pid = _profile_with_resume()
    monkeypatch.setattr(llm_mod, "generate", lambda prompt: {
        "text": None, "provider": None,
        "errors": {"gemini": "HTTPError: 429 Too Many Requests"}})
    monkeypatch.setattr(llm_mod, "status", lambda: {
        "providers": ["gemini"], "provider": "gemini", "fallback": "template"})
    res = _ask(pid)
    assert res["mode"] == "fallback"
    assert "didn't answer just now" in res["answer"]
    assert "429" in res["answer"]
    assert "Python" in res["answer"]  # the quoted material is still there


def test_keyless_still_quotes_and_says_so(monkeypatch):
    pid = _profile_with_resume()
    monkeypatch.setattr(llm_mod, "generate", lambda prompt: {
        "text": None, "provider": None,
        "errors": {"gemini": "GEMINI_API_KEY is not set",
                   "groq": "GROQ_API_KEY is not set"}})
    monkeypatch.setattr(llm_mod, "status", lambda: {
        "providers": [], "provider": None, "fallback": "template"})
    res = _ask(pid)
    assert res["mode"] == "fallback"
    assert "No LLM key is configured" in res["answer"]


def test_no_match_with_lm_configured_explains_compose_limit(monkeypatch):
    # A bare profile — no documents, no saved jobs — is the reliable
    # no-match case (similarity search over an existing resume returns
    # nearest passages even for an unrelated question).
    p = client.post("/api/profiles", json={"name": "Bare Client"}).json()
    monkeypatch.setattr(llm_mod, "status", lambda: {
        "providers": ["gemini"], "provider": "gemini", "fallback": "template"})
    res = _ask(p["id"], "Tell me about underwater basket weaving roles")
    assert res["mode"] == "fallback"
    assert "composes only from saved material" in res["answer"]
