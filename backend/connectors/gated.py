"""Indeed, Dice, Monster — GATED boards (verified 2026-11-07).

Indeed: public job-search Publisher API retired — sign-ups ended Nov 2020,
deprecated Mar 2023, endpoint stopped answering Oct 2024. Remaining APIs
(Job Sync, Indeed Apply, Disposition Sync, Sponsored Jobs) are partner-only,
provisioned via Indeed's Partner Console after approval; none returns search
results. Terms forbid scraping. Route to Indeed listings: a licensed
third-party jobs API (e.g. JobsPipe, which carries Indeed) or an Indeed
partnership — not a direct call.

Dice: no public self-serve job-search API was found. Dice data is available
only via third-party aggregators (e.g. Techmap via RapidAPI — free BASIC
100 queries / 1,000 postings per month) or a commercial partnership.
Composio offers a no-auth Dice MCP tool, which is a third-party wrapper,
not Dice's own API.

Monster: no public job-search API was found. Monster offers employer/ATS
partner integrations only; no self-serve key exists for reading listings.

These connectors stay in the registry so the UI can show the honest status
and the next step, instead of silently pretending the board is connected.
"""
from .base import BaseConnector, SearchResult

_GATED = {
    "indeed": ("Indeed's public job-search API is retired (2020–2024). "
               "Remaining APIs are partner-only and return no search results. "
               "Needs an Indeed partnership or a licensed third-party jobs API."),
    "dice": ("Dice has no public self-serve job-search API. "
             "Available via third-party aggregators (e.g. Techmap/RapidAPI, free BASIC tier) "
             "or a commercial partnership."),
    "monster": ("Monster has no public job-search API. "
                "Employer/ATS partner integrations only; no self-serve key."),
}


class GatedConnector(BaseConnector):
    def __init__(self, name):
        self.name = name

    def search(self, query, location="", limit=10):
        return SearchResult(source=self.name, status="unavailable",
                            message=_GATED[self.name])
