"""PocketPro LLM chain — Gemini, then Groq, then nothing (stdlib only).

Same pattern as the other PocketPro apps: keys live in the environment
(the local .env), never in code or chat. Each rung's failure is
captured and reported, never raised — callers fall back to their
deterministic template output and say which provider answered.
"""
import json
import os
import urllib.request

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
TIMEOUT = 30


def _post(url: str, payload: dict, headers: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def _gemini(prompt: str) -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    out = _post(GEMINI_URL.format(model=model) + f"?key={key}",
                {"contents": [{"parts": [{"text": prompt}]}]}, {})
    return out["candidates"][0]["content"]["parts"][0]["text"]


def _groq(prompt: str) -> str:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set")
    model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b").strip() or "openai/gpt-oss-20b"
    out = _post(GROQ_URL,
                {"model": model, "messages": [{"role": "user", "content": prompt}]},
                {"Authorization": f"Bearer {key}"})
    return out["choices"][0]["message"]["content"]


RUNGS = (("gemini", _gemini), ("groq", _groq))


def generate(prompt: str) -> dict:
    """First rung that answers wins. Returns {text, provider, errors} —
    text/provider are None when no rung is configured or all failed."""
    errors = {}
    for name, fn in RUNGS:
        try:
            text = fn(prompt)
            if text and text.strip():
                return {"text": text.strip(), "provider": name, "errors": errors}
            errors[name] = "empty response"
        except Exception as exc:  # noqa: BLE001 - a dead rung falls through
            errors[name] = f"{type(exc).__name__}: {exc}"[:200]
    return {"text": None, "provider": None, "errors": errors}


def status() -> dict:
    configured = [name for name, env in (("gemini", "GEMINI_API_KEY"), ("groq", "GROQ_API_KEY"))
                  if os.environ.get(env, "").strip()]
    return {"providers": configured,
            "provider": configured[0] if configured else None,
            "fallback": "template"}
