"""RemoteOK — free public API, NO key. Verified live 2026-11-07.
GET https://remoteok.com/api?tag=<tag> (or no params for the latest jobs).
Terms (first element of the response): link back to the job URL on
Remote OK and mention Remote OK as the source; do not use the logo.
The first JSON element is a legal notice, not a job — skip it.
"""
import html
import re

from .http import get as http_get, post as http_post

from .base import BaseConnector, Job, SearchResult


def _clean(text):
    return re.sub(r"<[^>]+>", " ", html.unescape(text or "")).strip()


class RemoteOKConnector(BaseConnector):
    name = "remoteok"

    def search(self, query, location="", limit=10):
        try:
            params = {}
            tag = (query or "").strip().lower().split()
            if len(tag) == 1 and tag[0].isalpha():
                params["tag"] = tag[0]
            r = http_get("https://remoteok.com/api", params=params, timeout=20)
            r.raise_for_status()
            items = r.json()
            jobs = []
            for x in items:
                if not isinstance(x, dict) or "position" not in x:
                    continue  # legal notice element
                text = f"{x.get('position','')} {x.get('company','')} {' '.join(x.get('tags') or [])}"
                if query and query.lower() not in text.lower():
                    continue
                salary = ""
                if x.get("salary_min") or x.get("salary_max"):
                    salary = f"{x.get('salary_min') or ''}-{x.get('salary_max') or ''}"
                jobs.append(Job(
                    id=f"remoteok-{x.get('id')}", title=x.get("position", ""),
                    company=x.get("company", ""), location="Remote",
                    source="remoteok",
                    url=x.get("apply_url") or x.get("url", ""),
                    snippet=_clean(x.get("description", ""))[:300],
                    salary=salary,
                ).as_dict())
                if len(jobs) >= limit:
                    break
            return SearchResult(source=self.name, status="ok", jobs=jobs)
        except Exception as e:  # noqa: BLE001 - per-source error, not a 500
            return SearchResult(source=self.name, status="error", message=str(e))
