"""Common job record + connector interface.

Every connector returns the same shape so the frontend and the concierge
never care which board a job came from. A connector with no key (or a
gated board) returns status="unavailable" with an honest reason instead
of failing the whole search.
"""
from dataclasses import dataclass, field


@dataclass
class Job:
    id: str
    title: str
    company: str = ""
    location: str = ""
    source: str = ""
    url: str = ""
    snippet: str = ""
    salary: str = ""

    def as_dict(self):
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class SearchResult:
    source: str
    status: str  # "ok" | "unavailable" | "error"
    jobs: list = field(default_factory=list)
    message: str = ""


class BaseConnector:
    name = "base"

    def search(self, query: str, location: str = "", limit: int = 10) -> SearchResult:
        raise NotImplementedError
