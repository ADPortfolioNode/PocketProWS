"""HTTP 429 retry-with-backoff in the LM chain (Anthony, 2026-11-24).

Gemini's free tier rate-limits per minute; a 429 used to fail the
rung instantly and the concierge fell back to quoted material. Now
the rung's call retries after 3s and 9s before failing — most limits
clear inside that window. Non-429 errors never retry.
"""
import json
import time
import urllib.error
import urllib.request

from backend import llm


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._b


_GEMINI_OK = {"candidates": [{"content": {"parts": [{"text": "composed answer"}]}}]}


def _rig(monkeypatch, outcomes):
    """urlopen replays `outcomes` (exceptions or payloads); sleeps are
    recorded, never actually waited out."""
    calls = {"n": 0}
    sleeps = []

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        out = outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return _Resp(out)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    return calls, sleeps


def _429():
    return urllib.error.HTTPError("https://x", 429, "Too Many Requests",
                                  hdrs=None, fp=None)


def test_429_retries_with_backoff_then_answers(monkeypatch):
    calls, sleeps = _rig(monkeypatch, [_429(), _429(), _GEMINI_OK])
    res = llm.generate("hello")
    assert res["provider"] == "gemini"
    assert res["text"] == "composed answer"
    assert calls["n"] == 3
    assert sleeps == [3, 9]


def test_429_exhausts_retries_and_the_rung_fails_honestly(monkeypatch):
    calls, sleeps = _rig(monkeypatch, [_429(), _429(), _429()])
    res = llm.generate("hello")
    assert res["text"] is None
    assert "429" in res["errors"]["gemini"]
    assert calls["n"] == 3  # initial + two retries, no more
    assert sleeps == [3, 9]


def test_non_429_errors_never_retry(monkeypatch):
    err = urllib.error.HTTPError("https://x", 500, "Server Error",
                                 hdrs=None, fp=None)
    calls, sleeps = _rig(monkeypatch, [err])
    res = llm.generate("hello")
    assert res["text"] is None
    assert "500" in res["errors"]["gemini"]
    assert calls["n"] == 1
    assert sleeps == []
