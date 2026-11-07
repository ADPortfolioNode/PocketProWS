import os
import sys
from pathlib import Path

import pytest

# Isolate Chroma per test run (never touch the real pocketprows-data).
os.environ["POCKETPROWS_CHROMA_PATH"] = str(Path(__file__).parent / ".test-chroma")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.config as cfg  # noqa: E402
import backend.vector_store as vs  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_chroma(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "CHROMA_PATH", str(tmp_path / "chroma"))
    vs._client = None
    yield
    vs._client = None
