"""Web search connector (Anthony, 2026-11-24): keyless job search
over the open web — no API key, no account. Engine is Bing's public
results page: verified live, it answers a plain Python client in
about a second with parseable results, while Google returns a
script shell and DuckDuckGo serves a 202 bot-challenge. These
tests parse recorded-style fixtures; the live engine check is
separate."""
import base64

from backend.connectors import websearch as ws_mod
from backend.connectors.websearch import WebSearchConnector

_TRACKED = ("https://www.bing.com/ck/a?!&&p=xyz"
            "&u=a1" + base64.urlsafe_b64encode(
                b"https://example.org/job9").decode().rstrip("=") + "&ntb=1")

PAGE = f"""
<html><body><ol id="b_results">
<li class="b_algo"><div class="b_tpcn"><a class="tilk" href="https://example.com/">x</a></div>
  <h2><a href="https://example.com/jobs/1">Python Developer at Acme Corp</a></h2>
  <div class="b_caption"><p>Build APIs with Python. Fully remote team.</p></div></li>
<li class="b_algo b_ad"><h2><a href="https://ads.example.com/click">Sponsored Job at AdCo</a></h2>
  <div class="b_caption"><p>Ad snippet.</p></div></li>
<li class="b_algo"><h2><a href="https://boards.example.com/job2">Backend Engineer</a></h2>
  <div class="b_caption"><p>On-site role in New York, NY.</p></div></li>
<li class="b_algo"><h2><a href="https://example.com/jobs/1">Python Developer at Acme Corp</a></h2>
  <div class="b_caption"><p>Duplicate of the first result.</p></div></li>
<li class="b_algo"><h2><a href="{_TRACKED}">Data Analyst at DataCo</a></h2>
  <div class="b_caption"><p>Analyze data. Remote.</p></div></li>
<li class="b_algo"><h2><a href="https://www.bing.com/search?q=more">More results</a></h2>
  <div class="b_caption"><p>Internal link, not a job.</p></div></li>
</ol></body></html>
"""


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def test_parses_results_skips_ads_dupes_and_internal(monkeypatch):
    monkeypatch.setattr(ws_mod, "http_get",
                        lambda url, **kw: _Resp(PAGE))
    r = WebSearchConnector().search("python developer",
                                    location="New York", limit=10)
    assert r.status == "ok"
    assert [j["title"] for j in r.jobs] == [
        "Python Developer", "Backend Engineer", "Data Analyst"]
    first, second, third = r.jobs
    assert first["company"] == "Acme Corp"
    assert first["url"] == "https://example.com/jobs/1"
    assert first["location"] == "Remote"
    assert first["source"] == "websearch"
    assert second["company"] == ""
    assert second["location"] == "New York"
    # The click-tracker link is decoded to the real posting.
    assert third["company"] == "DataCo"
    assert third["url"] == "https://example.org/job9"


GENERIC_PAGE = """
<html><body><ol id="b_results">
<li class="b_algo"><h2><a href="https://www.python.org/">Welcome to Python.org</a></h2>
  <div class="b_caption"><p>The official home of the Python programming language.</p></div></li>
<li class="b_algo"><h2><a href="https://en.wikipedia.org/wiki/Python">Python (programming language) - Wikipedia</a></h2>
  <div class="b_caption"><p>Python is a high-level, general-purpose programming language.</p></div></li>
</ol></body></html>
"""


def test_generic_page_yields_no_jobs_not_junk(monkeypatch):
    # The page Bing serves when it throttles automated queries:
    # HTTP 200, real HTML, zero job listings in it.
    monkeypatch.setattr(ws_mod, "http_get",
                        lambda url, **kw: _Resp(GENERIC_PAGE))
    ws_mod._CACHE.clear()
    r = WebSearchConnector().search("python developer", limit=10)
    assert r.status == "ok"
    assert r.jobs == []


def test_engine_failure_is_an_honest_error(monkeypatch):
    def boom(url, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(ws_mod, "http_get", boom)
    ws_mod._CACHE.clear()
    r = WebSearchConnector().search("python")
    assert r.status == "error"
    assert "network down" in r.message
    assert r.jobs == []


GOOGLE_PAGE = """
<html><body>
<div class="MjjYud"><div class="g">
  <a href="https://www.indeed.com/viewjob?jk=abc"><h3>Python Developer at Acme Corp</h3></a>
  <div class="VwiC3b">Build APIs with Python. Fully remote team.</div>
</div></div>
<div class="MjjYud"><div class="g">
  <a href="/url?q=https://boards.example.com/job7&amp;sa=U"><h3>Backend Engineer</h3></a>
  <div class="VwiC3b">On-site role in New York, NY. Apply now.</div>
</div></div>
<div class="MjjYud"><div class="g">
  <a href="https://support.google.com/accounts/answer/1"><h3>Google Account Help</h3></a>
  <div class="VwiC3b">Internal page, not a job.</div>
</div></div>
</body></html>
"""

GOOGLE_SHELL = "<html><head><title>Google Search</title></head><body><script>var x=1;</script><noscript>Please enable JavaScript</noscript></body></html>"


def _by_host(google_text, bing_text):
    def get(url, **kwargs):
        return _Resp(google_text if "google" in url else bing_text)
    return get


def test_google_results_parse_and_win_first(monkeypatch):
    monkeypatch.setattr(ws_mod, "http_get", _by_host(GOOGLE_PAGE, PAGE))
    ws_mod._CACHE.clear()
    r = WebSearchConnector().search("python developer",
                                    location="New York", limit=10)
    assert r.status == "ok"
    # Google answered with 2 listings (>= the thin threshold is not
    # met for count, but both Google jobs lead; Bing may merge after).
    assert r.jobs[0]["title"] == "Python Developer"
    assert r.jobs[0]["company"] == "Acme Corp"
    assert r.jobs[0]["location"] == "Remote"
    assert r.jobs[1]["title"] == "Backend Engineer"
    assert r.jobs[1]["url"] == "https://boards.example.com/job7"
    assert r.jobs[1]["location"] == "New York"
    assert all("google.com" not in j["url"] for j in r.jobs)


def test_google_shell_falls_back_to_bing(monkeypatch):
    monkeypatch.setattr(ws_mod, "http_get", _by_host(GOOGLE_SHELL, PAGE))
    ws_mod._CACHE.clear()
    r = WebSearchConnector().search("python developer",
                                    location="New York", limit=10)
    assert r.status == "ok"
    assert [j["title"] for j in r.jobs][:2] == ["Python Developer", "Backend Engineer"]
    assert r.jobs[0]["url"] == "https://example.com/jobs/1"


def test_snippet_smalltalk_does_not_make_a_listing(monkeypatch):
    # An academic abstract that merely uses the word "apply" is not
    # a job listing (seen live 2026-11-24: an arXiv paper surfaced).
    page = """
    <html><body><ol id="b_results">
    <li class="b_algo"><h2><a href="https://arxiv.org/abs/2210.03629">ReAct: Synergizing Reasoning and Acting</a></h2>
      <div class="b_caption"><p>We apply ReAct to a diverse set of language and decision making tasks.</p></div></li>
    </ol></body></html>
    """
    monkeypatch.setattr(ws_mod, "http_get", _by_host(GOOGLE_SHELL, page))
    ws_mod._CACHE.clear()
    r = WebSearchConnector().search("react developer", limit=10)
    assert r.status == "ok"
    assert r.jobs == []


def test_split_title_reads_dash_and_pipe_companies():
    assert ws_mod._split_title("React Developer - Acme Corp") == (
        "React Developer", "Acme Corp")
    assert ws_mod._split_title("Backend Engineer | Globex") == (
        "Backend Engineer", "Globex")
    assert ws_mod._split_title("AI Engineer at Initech — Indeed") == (
        "AI Engineer", "Initech")


def test_split_title_never_reads_mode_or_board_as_company():
    assert ws_mod._split_title("React Developer - Remote") == (
        "React Developer - Remote", "")
    assert ws_mod._split_title("React Developer - Indeed") == (
        "React Developer - Indeed", "")


POST_PAGE = """
<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "JobPosting",
 "title": "React Developer",
 "hiringOrganization": {"@type": "Organization", "name": "Acme Corp"},
 "jobLocation": {"@type": "Place", "address": {
   "addressLocality": "New York", "addressRegion": "NY",
   "addressCountry": "US"}},
 "baseSalary": {"@type": "MonetaryAmount", "currency": "USD",
   "value": {"@type": "QuantitativeValue", "value": 120000,
             "unitText": "YEAR"}},
 "description": "<p>Build <b>React</b> apps. Apply: jobs@acme.example</p>"}
</script></head><body>post</body></html>
"""


def test_enrich_reads_missing_fields_from_the_post(monkeypatch):
    monkeypatch.setattr(ws_mod, "http_get",
                        lambda url, **kw: _Resp(POST_PAGE))
    job = {"title": "React Developer", "company": "", "location": "",
           "salary": "", "description": "", "url": "https://example.com/j/1"}
    out = ws_mod._enrich_from_post(dict(job))
    assert out["company"] == "Acme Corp"
    assert out["location"] == "New York, NY, US"
    assert out["salary"] == "USD 120000 per year"
    assert "jobs@acme.example" in out["description"]


def test_enrich_failure_leaves_job_unchanged(monkeypatch):
    def boom(url, **kw):
        raise RuntimeError("blocked")
    monkeypatch.setattr(ws_mod, "http_get", boom)
    job = {"title": "React Developer", "company": "", "location": "",
           "salary": "", "description": "", "url": "https://example.com/j/2"}
    assert ws_mod._enrich_from_post(dict(job)) == job


def test_enrich_falls_back_to_og_title_company(monkeypatch):
    page = ('<html><head><meta property="og:title" '
            'content="Backend Engineer at Globex"></head></html>')
    monkeypatch.setattr(ws_mod, "http_get", lambda url, **kw: _Resp(page))
    job = {"title": "Backend Engineer", "company": "", "location": "",
           "salary": "", "description": "x", "url": "https://example.com/j/3"}
    assert ws_mod._enrich_from_post(dict(job))["company"] == "Globex"
