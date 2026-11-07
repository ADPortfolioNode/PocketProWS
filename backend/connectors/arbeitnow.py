"""Arbeitnow — free public API, NO key. Verified live 2026-11-07.
GET https://www.arbeitnow.com/api/job-board-api?search=<q>&remote=true
Coverage caveat: Arbeitnow is Germany-focused (English-speaking jobs in
Germany) with some US-remote roles mixed in. It is a free, no-key source,
so it earns its place as the 6th free source — but for a US job seeker
its hit rate is lower than Adzuna/Remotive/RemoteOK. No key, no stated
rate limit; keep calls modest.
"""
import html
import re

from .http import get as http_get, post as http_post

from .base import BaseConnector, Job, SearchResult


def _clean(text):
    return re.sub(r"<[^>]+>", " ", html.unescape(text or "")).strip()


class ArbeitnowConnector(BaseConnector):
    name = "arbeitnow"

    def search(self, query, location="", limit=10):
        try:
            r = http_get(
                "https://www.arbeitnow.com/api/job-board-api",
                params={"search": query},
                timeout=20,
            )
            r.raise_for_status()
            jobs = []
            for x in r.json().get("data", []):
                text = f"{x.get('title','')} {x.get('company_name','')} {' '.join(x.get('tags') or [])}"
                if query and query.lower() not in text.lower():
                    continue
                jobs.append(Job(
                    id=f"arbeitnow-{x.get('slug')}", title=x.get("title", ""),
                    company=x.get("company_name", ""),
                    location=x.get("location", ""),
                    source="arbeitnow", url=x.get("url", ""),
                    snippet=_clean(x.get("description", ""))[:300],
                ).as_dict())
                if len(jobs) >= limit:
                    break
            return SearchResult(source=self.name, status="ok", jobs=jobs)
        except Exception as e:  # noqa: BLE001 - per-source error, not a 500
            return SearchResult(source=self.name, status="error", message=str(e))
