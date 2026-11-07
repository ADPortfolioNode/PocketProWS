"""PocketProWS configuration. Keys come from the environment only — never commit them."""
import os
from pathlib import Path

# Load ~/workspace/pocketprows/.env (project-local keys) if present.
# python-dotenv is a declared dependency (requirements.txt).
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

CHROMA_PATH = os.environ.get("POCKETPROWS_CHROMA_PATH") or str(
    Path.home() / "workspace" / "pocketprows-data"
)
JOBS_COLLECTION = "pocketprows_jobs"
PROFILES_COLLECTION = "pocketprows_profiles"
BACKEND_PORT = int(os.environ.get("POCKETPROWS_BE_PORT", "5003"))

# Job-board keys (all optional; connectors degrade gracefully without them).
ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
JOOBLE_API_KEY = os.environ.get("JOOBLE_API_KEY", "")
USAJOBS_API_KEY = os.environ.get("USAJOBS_API_KEY", "")
USAJOBS_USER_AGENT = os.environ.get("USAJOBS_USER_AGENT", "")
