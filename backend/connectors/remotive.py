"""Remotive — free public API, NO key. Verified live 2026-11-07.
GET https://remotive.com/api/remote-jobs?search=<q>&limit=<n>
Remote jobs only. Terms (in the API response itself): link back to the
job URL on Remotive and mention Remotive as the source; jobs are delayed
24h; do NOT re-submit Remotive jobs to third-party job sites; max ~4
requests/day — do not poll it. Our use is an internal recruiter
workstation that links back to Remotive, which fits; we cache results
in Chroma and do not re-post them anywhere.
"""
import html
import re

from .http import get as http_get, post as http_post

from .base import BaseConnector, Job, SearchResult


def _clean(text):
    return re.sub(r"<[^>]+>", " ", html.unescape(text or "")).strip()


class RemotiveConnector(BaseConnector):
    name = "remotive"

    def search(self, query, location="", limit=10):
        try:
            r = http_get(
                "https://remotive.com/api/remote-jobs",
                params={"search": query, "limit": max(limit * 5, 20)},
                timeout=20,
            )
            r.raise_for_status()
            data = r.json()
            jobs = []
            for x in data.get("jobs", []):
                text = f"{x.get('title','')} {x.get('company_name','')} {' '.join(x.get('tags') or [])}"
                if query and query.lower() not in text.lower():
                    continue
                jobs.append(Job(
                    id=f"remotive-{x.get('id')}", title=x.get("title", ""),
                    company=x.get("company_name", ""),
                    location=x.get("candidate_required_location", "Remote"),
                    source="remotive", url=x.get("url", ""),
                    snippet=_clean(x.get("description", ""))[:300],
                    salary=str(x.get("salary") or ""),
                ).as_dict())
                if len(jobs) >= limit:
                    break
            return SearchResult(source=self.name, status="ok", jobs=jobs)
        except Exception as e:  # noqa: BLE001 - per-source error, not a 500
            return SearchResult(source=self.name, status="error", message=str(e))
