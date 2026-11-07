"""Jooble — free key by request form at jooble.org/api/about.
POST https://jooble.org/api/{key} with JSON {keywords, location, page}.
Free plan: 500 requests TOTAL per key (lifetime cap, per Jooble help centre,
verified 2026-11-07) — not per month. One key per country domain (jooble.org = US).
"""
from .http import get as http_get, post as http_post

from ..config import JOOBLE_API_KEY
from .base import BaseConnector, Job, SearchResult


class JoobleConnector(BaseConnector):
    name = "jooble"

    def search(self, query, location="", limit=10):
        if not JOOBLE_API_KEY:
            return SearchResult(
                source=self.name, status="unavailable",
                message="No Jooble key configured. Request a free key at jooble.org/api/about (500 requests lifetime per key).",
            )
        try:
            r = http_post(
                f"https://jooble.org/api/{JOOBLE_API_KEY}",
                json={"keywords": query, "location": location, "page": 1},
                timeout=15,
            )
            r.raise_for_status()
            jobs = [
                Job(id=f"jooble-{x.get('id')}", title=x.get("title", ""),
                    company=x.get("company", ""), location=x.get("location", ""),
                    source="jooble", url=x.get("link", ""),
                    snippet=(x.get("snippet") or "")[:300],
                    salary=x.get("salary", ""))
                for x in r.json().get("jobs", [])[:limit]
            ]
            return SearchResult(source=self.name, status="ok", jobs=[j.as_dict() for j in jobs])
        except Exception as e:  # noqa: BLE001
            return SearchResult(source=self.name, status="error", message=str(e))
