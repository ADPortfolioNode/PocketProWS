"""Adzuna — the wired, working connector.
Free self-serve key: register at developer.adzuna.com for app_id + app_key.
GET https://api.adzuna.com/v1/api/jobs/us/search/1?app_id=..&app_key=..&what=..&where=..
Default limits (per Adzuna terms, verified 2026-11-07): 25/min, 250/day,
1,000/week, 2,500/month. Commercial use: 14-day trial, then a licence.
Attribution "Jobs by Adzuna" required when displaying results.
"""
from .http import get as http_get, post as http_post

from ..config import ADZUNA_APP_ID, ADZUNA_APP_KEY
from .base import BaseConnector, Job, SearchResult


class AdzunaConnector(BaseConnector):
    name = "adzuna"

    def search(self, query, location="", limit=10):
        if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
            return SearchResult(
                source=self.name, status="unavailable",
                message="No Adzuna key configured. Set ADZUNA_APP_ID and ADZUNA_APP_KEY (free at developer.adzuna.com).",
            )
        try:
            r = http_get(
                "https://api.adzuna.com/v1/api/jobs/us/search/1",
                params={"app_id": ADZUNA_APP_ID, "app_key": ADZUNA_APP_KEY,
                        "what": query, "where": location, "results_per_page": limit},
                timeout=15,
            )
            r.raise_for_status()
            jobs = [
                Job(id=f"adzuna-{x.get('id')}", title=x.get("title", ""),
                    company=(x.get("company") or {}).get("display_name", ""),
                    location=(x.get("location") or {}).get("display_name", ""),
                    source="adzuna", url=x.get("redirect_url", ""),
                    snippet=(x.get("description") or "")[:300],
                    salary=str(x.get("salary_min") or ""))
                for x in r.json().get("results", [])
            ]
            return SearchResult(source=self.name, status="ok", jobs=[j.as_dict() for j in jobs])
        except Exception as e:  # noqa: BLE001 - surface as a per-source error, not a 500
            return SearchResult(source=self.name, status="error", message=str(e))
