"""USAJOBS — official free US federal jobs API (OPM).
Register at developer.usajobs.gov/apirequest; key arrives by email, usually
in minutes. GET https://data.usajobs.gov/api/search with headers
Authorization-Key: <key> and User-Agent: <registered email>.
No cost, no published daily cap (10,000 rows/query, 500/page). Federal only.
Data is licensed to the registering company only — do not resell/redistribute.
"""
from .http import get as http_get, post as http_post

from ..config import USAJOBS_API_KEY, USAJOBS_USER_AGENT
from .base import BaseConnector, Job, SearchResult


class USAJobsConnector(BaseConnector):
    name = "usajobs"

    def search(self, query, location="", limit=10):
        if not USAJOBS_API_KEY or not USAJOBS_USER_AGENT:
            return SearchResult(
                source=self.name, status="unavailable",
                message="No USAJOBS key configured. Free key at developer.usajobs.gov/apirequest (set USAJOBS_API_KEY + USAJOBS_USER_AGENT=email).",
            )
        try:
            r = http_get(
                "https://data.usajobs.gov/api/search",
                params={"Keyword": query, "LocationName": location, "ResultsPerPage": limit},
                headers={"Authorization-Key": USAJOBS_API_KEY, "User-Agent": USAJOBS_USER_AGENT,
                         "Host": "data.usajobs.gov"},
                timeout=15,
            )
            r.raise_for_status()
            jobs = []
            for x in r.json().get("SearchResult", {}).get("SearchResultItems", []):
                d = x.get("MatchedObjectDescriptor", {})
                jobs.append(Job(
                    id=f"usajobs-{d.get('PositionID')}", title=d.get("PositionTitle", ""),
                    company=d.get("OrganizationName", ""), location=", ".join(d.get("PositionLocationDisplay", [])),
                    source="usajobs", url=d.get("PositionURI", ""),
                    snippet=(d.get("QualificationSummary") or "")[:300]).as_dict())
            return SearchResult(source=self.name, status="ok", jobs=jobs)
        except Exception as e:  # noqa: BLE001
            return SearchResult(source=self.name, status="error", message=str(e))
