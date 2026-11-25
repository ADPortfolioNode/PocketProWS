"""Web search — keyless job search over the open web
(Anthony, 2026-11-24: "we gotta get away from these api keys —
we could use raw open internet search... whichever is most
responsive").

Engines, in order: Google, then Bing (Anthony, 2026-11-24: "add
google job search to web search"). Both are keyless — no API key,
no account, nothing to configure. Verified live 2026-11-24 from a
plain Python HTTP client: Bing answers in about a second with
parseable result blocks; Google answers some clients with a
script shell holding zero results (it did so from Muse's VM),
so Google is asked first and Bing carries the search whenever
Google's page holds nothing parseable — whichever responds with
real listings wins. DuckDuckGo is not used: it serves a 202
bot-challenge page to every Python client tried. Both engines
throttle bursts of automated queries, so this connector asks
each engine sparingly, caches briefly, and only returns results
that look like job listings — a throttled or shell page yields
an honest empty result, never junk.

Results are web listings, not a structured feed: title and link
are exact; the company is read from the listing title when it
follows the usual "Role at Company" shape, and the location is
only claimed when the listing's own text supports it.
"""
import base64
import hashlib
import html as html_mod
import re
import time
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

from .http import get as http_get

from .base import BaseConnector, Job, SearchResult

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
_BOARDS = ("indeed", "linkedin", "glassdoor", "ziprecruiter", "monster",
           "dice", "simplyhired", "careerbuilder", "wellfound", "remoteok",
           "arbeitnow", "remotive")
# Hosts whose pages are job listings by construction (boards and the
# big applicant-tracking systems employers post on directly).
_JOB_HOSTS = _BOARDS + ("greenhouse", "lever", "workable", "ashbyhq",
                        "smartrecruiters", "myworkdayjobs", "icims",
                        "taleo", "jobvite", "breezy", "workday")
_JOB_WORDS = ("job", "hiring", "career", "apply", "vacancy", "opening",
              "position", "employment")
# In a snippet, single words prove little ("we apply this method" is
# an abstract, not a listing) — only job-intent phrases count there.
_SNIPPET_PHRASES = ("apply now", "now hiring", "we are hiring", "hiring",
                    "job description", "careers", "vacanc", "open position",
                    "jobs", "employment opportunity")

# Bing throttles automated querying quickly (verified live
# 2026-11-24: after a burst of test queries it began serving a
# generic page for everything). The app searches on demand, so the
# volume is small — and a short cache keeps repeat searches inside
# a session from spending the budget twice.
_CACHE = {}
_CACHE_TTL = 120.0


def _is_job_listing(url, title, snippet):
    """A result counts only if it looks like a job listing: hosted
    on a board/ATS, or carrying job-intent words in its title,
    snippet or URL. A throttled generic page therefore yields zero
    jobs — honest emptiness — instead of junk results."""
    host = urlparse(url).netloc.lower()
    if any(b in host for b in _JOB_HOSTS):
        return True
    if any(w in f"{title} {url}".lower() for w in _JOB_WORDS):
        return True
    return any(p in (snippet or "").lower() for p in _SNIPPET_PHRASES)


def _clean(text):
    return re.sub(r"\s+", " ", html_mod.unescape(text or "")).strip()


class _BingParser(HTMLParser):
    """Collects (title, href, snippet) from Bing result blocks
    (<li class="b_algo">), skipping sponsored blocks (b_ad)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self._li_stack = []       # True = inside a b_algo block
        self._in_h2 = False
        self._capture = None      # "title" | "snippet"
        self._href = ""
        self._buf = []

    def _in_algo(self):
        return any(self._li_stack)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if tag == "li":
            self._li_stack.append("b_algo" in classes and "b_ad" not in classes)
            return
        if not self._in_algo():
            return
        if tag == "h2":
            self._in_h2 = True
        elif tag == "a" and self._in_h2 and self._capture is None:
            self._capture, self._href, self._buf = "title", attrs.get("href", ""), []
        elif tag == "p" and self._capture is None:
            self._capture, self._buf = "snippet", []

    def handle_endtag(self, tag):
        if tag == "li" and self._li_stack:
            self._li_stack.pop()
            return
        if tag == "h2":
            self._in_h2 = False
            return
        if not self._capture:
            return
        if (tag == "a" and self._capture == "title") or \
           (tag == "p" and self._capture == "snippet"):
            text = _clean("".join(self._buf))
            if self._capture == "title":
                self.results.append({"title": text, "href": self._href,
                                     "snippet": ""})
            elif self.results and not self.results[-1]["snippet"]:
                self.results[-1]["snippet"] = text
            self._capture, self._buf = None, []

    def handle_data(self, data):
        if self._capture:
            self._buf.append(data)


def _real_url(href):
    """Bing result links are usually direct; some go through its
    click tracker (bing.com/ck/a?...&u=a1<base64url target>).
    Returns the real URL, or "" for anything internal."""
    if not href or not href.startswith("http"):
        return ""
    parsed = urlparse(href)
    if "bing.com" in parsed.netloc and "/ck/a" in parsed.path:
        raw = parse_qs(parsed.query).get("u", [""])[0]
        if raw.startswith("a1"):
            try:
                padded = raw[2:] + "=" * (-len(raw[2:]) % 4)
                target = base64.urlsafe_b64decode(padded).decode("utf-8")
                return target if target.startswith("http") else ""
            except Exception:  # noqa: BLE001 - an undecodable tracker link is skipped
                return ""
        return ""
    if "bing.com" in parsed.netloc or "microsoft.com" in parsed.netloc:
        return ""
    return href


def _split_title(raw):
    """(job title, company) from a listing title. Only the common
    'Role at Company' shape is trusted; a trailing board name
    ('— Indeed') is stripped from the company."""
    title, company = raw.strip(), ""
    if " at " in title:
        title, company = title.rsplit(" at ", 1)
        company = re.split(r"\s+[|–—-]\s+", company)[0].strip()
        if company.lower() in _BOARDS:
            company = ""
    return title.strip(), company


class _GoogleParser(HTMLParser):
    """Collects (title, href, snippet) from a Google results page.
    A web result is an anchor holding an <h3> title; the snippet is
    the VwiC3b text block that follows it. When Google serves its
    script shell instead, nothing matches — by design."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self._a_href = None       # href of the anchor being read
        self._a_title = None      # h3 text captured inside it
        self._capture = None      # "title" | "snippet"
        self._buf = []
        self._div_depth = 0       # depth inside a snippet div

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "")
        if tag == "a" and self._capture is None:
            self._a_href, self._a_title = attrs.get("href", ""), None
        elif tag == "h3" and self._a_href is not None and self._capture is None:
            self._capture, self._buf = "title", []
        elif tag == "div":
            if self._div_depth:
                self._div_depth += 1
            elif "VwiC3b" in classes and self.results \
                    and not self.results[-1]["snippet"] and self._capture is None:
                self._capture, self._buf, self._div_depth = "snippet", [], 1

    def handle_endtag(self, tag):
        if tag == "h3" and self._capture == "title":
            self._a_title = _clean("".join(self._buf))
            self._capture, self._buf = None, []
            return
        if tag == "a" and self._a_href is not None:
            if self._a_title:
                self.results.append({"title": self._a_title,
                                     "href": self._a_href, "snippet": ""})
            self._a_href, self._a_title = None, None
            return
        if tag == "div" and self._div_depth:
            self._div_depth -= 1
            if not self._div_depth and self._capture == "snippet":
                self.results[-1]["snippet"] = _clean("".join(self._buf))
                self._capture, self._buf = None, []

    def handle_data(self, data):
        if self._capture:
            self._buf.append(data)


def _google_url(href):
    """Google result links are direct, or wrapped as /url?q=<real>.
    Returns the real URL, or "" for Google-internal links."""
    if not href:
        return ""
    if href.startswith("/url?"):
        target = parse_qs(urlparse(href).query).get("q", [""])[0]
        return target if target.startswith("http") else ""
    if not href.startswith("http"):
        return ""
    if "google." in urlparse(href).netloc:
        return ""
    return href


def _to_jobs(raw_results, url_fn, location, limit):
    jobs, seen = [], set()
    for r in raw_results:
        url = url_fn(r["href"])
        if not url or url in seen:
            continue
        seen.add(url)
        title, company = _split_title(r["title"])
        if not title or not _is_job_listing(url, title, r["snippet"]):
            continue
        text = f"{title} {r['snippet']}"
        if location and location.lower() in text.lower():
            loc = location
        elif "remote" in text.lower():
            loc = "Remote"
        else:
            loc = ""
        jobs.append(Job(
            id="websearch-" + hashlib.md5(url.encode()).hexdigest()[:10],
            title=title, company=company, location=loc,
            source="websearch", url=url,
            snippet=r["snippet"][:300],
        ).as_dict())
        if len(jobs) >= limit:
            break
    return jobs


def _parse_results(page_html, location, limit):
    parser = _BingParser()
    parser.feed(page_html or "")
    return _to_jobs(parser.results, _real_url, location, limit)


def _parse_google_results(page_html, location, limit):
    parser = _GoogleParser()
    parser.feed(page_html or "")
    return _to_jobs(parser.results, _google_url, location, limit)


class WebSearchConnector(BaseConnector):
    name = "websearch"

    def _fetch_bing(self, q, location, limit):
        r = http_get("https://www.bing.com/search", params={"q": q},
                     timeout=20, headers={"User-Agent": _UA,
                                          "Accept-Language": "en-US,en;q=0.9"})
        r.raise_for_status()
        return _parse_results(r.text, location, limit)

    def _fetch_google(self, q, location, limit):
        r = http_get("https://www.google.com/search",
                     params={"q": q, "num": 20},
                     timeout=20, headers={"User-Agent": _UA,
                                          "Accept-Language": "en-US,en;q=0.9"})
        r.raise_for_status()
        return _parse_google_results(r.text, location, limit)

    def search(self, query, location="", limit=10):
        key = (query.lower().strip(), location.lower().strip(), limit)
        hit = _CACHE.get(key)
        if hit and time.time() - hit[0] < _CACHE_TTL:
            return SearchResult(source=self.name, status="ok", jobs=hit[1])
        plain = f"{query} jobs"
        if location:
            plain += f" {location}"
        scoped = f"site:indeed.com {query} jobs"
        if location:
            scoped += f" {location}"
        # Google first (Anthony's ask), then Bing scoped to the
        # largest board, then Bing unscoped — each pass only runs
        # while the merged result is still thin, and a failed engine
        # never sinks the ones after it. Only when every engine
        # failed does the search report an error.
        jobs, seen, errors, answered = [], set(), [], False

        def merge(found):
            for j in found:
                if j["url"] not in seen:
                    seen.add(j["url"])
                    jobs.append(j)
                if len(jobs) >= limit:
                    break

        for fetch, q in ((self._fetch_google, plain),
                         (self._fetch_bing, scoped),
                         (self._fetch_bing, plain)):
            if len(jobs) >= 3:
                break
            try:
                merge(fetch(q, location, limit))
                answered = True
            except Exception as e:  # noqa: BLE001 - next engine's turn
                errors.append(str(e))
        if not answered:
            return SearchResult(source=self.name, status="error",
                                message=errors[0] if errors else "no engine answered")
        _CACHE[key] = (time.time(), jobs)
        return SearchResult(source=self.name, status="ok", jobs=jobs)
