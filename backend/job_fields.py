"""Missing fields on a searched job post (Anthony, 2026-11-25:
"search job post for missing fields" — both: flag them AND fill
what can be filled).

Every searched job is annotated with:
- `missing_fields`: human labels for the fields the post does not
  carry — location, application email, salary, description, company.
- `application_email`: filled in when the posting's own text prints
  one (reuses submission.find_application_email over the full post
  description first, then the snippet).

The honest limit, stated plainly: fills come only from the post's
own explicit text. The application email is filled when the full
description prints one. Location and salary are filled only when
the description states them explicitly — a labeled location line
or a stated pay range — never from a stray place name or number.
Everything else is flagged, never guessed. A flagged field is a
fact about the post, not a defect in the app: the keyless boards
mostly do not return pay.
"""
import re

from .submission import find_application_email

# Order is deliberate: the fields that block the next step first
# (location gates the USA filter, the email gates submission),
# then the nice-to-know ones.
LABELS = {
    "location": "location",
    "application_email": "application email",
    "salary": "salary",
    "description": "description",
    "company": "company",
}


def _blank(job: dict, *keys: str) -> bool:
    return not any(str(job.get(k) or "").strip() for k in keys)


def _post_text(job: dict) -> str:
    parts = [str(job.get(k) or "") for k in ("description", "snippet")]
    return "\n".join(p for p in parts if p.strip())


_LOCATION_LABEL = re.compile(
    r"(?:^|[.!?]\s+|\n)\s*(?:job\s+|work\s+)?location\s*[:\-]\s*([^\n.;|]{2,80})",
    re.I,
)
_SALARY_LABEL = re.compile(
    r"\b(?:salary|pay|compensation|rate)(?:\s+range)?\s*[:\-]\s*([^\n.;|]{0,100})",
    re.I,
)
_MONEY_RANGE = re.compile(
    r"\$?\s*\d[\d,]*(?:\.\d+)?\s*(?:k|K)?\s*(?:-|–|—|to)\s*"
    r"\$?\s*\d[\d,]*(?:\.\d+)?\s*(?:k|K)?"
    r"(?:\s*(?:per\s+(?:year|annum|hour|hr)|/yr|/hr|annually|hourly))?",
    re.I,
)
_MONEY_SINGLE = re.compile(
    r"\$\s*\d[\d,]*(?:\.\d+)?\s*(?:k|K)?"
    r"(?:\s*(?:per\s+(?:year|annum|hour|hr)|/yr|/hr|annually|hourly))?",
    re.I,
)
_PLAIN_PAY = re.compile(
    r"\d[\d,]*(?:\.\d+)?\s*(?:k|K)?\s*"
    r"(?:per\s+(?:year|annum|hour|hr)|/yr|/hr|annually|hourly)",
    re.I,
)
_PAY_PERIOD = re.compile(
    r"per\s+(?:year|annum|hour|hr)|/yr|/hr|annually|hourly", re.I)


def _explicit_location(job: dict) -> str:
    """Location only from an explicit labeled line in the post
    description — never from a place name mentioned in prose."""
    m = _LOCATION_LABEL.search(_post_text(job))
    if not m:
        return ""
    loc = re.sub(r"\s+", " ", m.group(1)).strip(" ,-")
    if not loc or len(loc) > 80 or "@" in loc or "http" in loc.lower():
        return ""
    if loc.lower().startswith("is ") or "apply" in loc.lower():
        return ""
    return loc


def _explicit_salary(job: dict) -> str:
    """Salary only from a labeled pay line or a stated pay range
    with an explicit period — never from a stray number."""
    text = _post_text(job)
    m = _SALARY_LABEL.search(text)
    if m:
        chunk = m.group(1)
        hit = _MONEY_RANGE.search(chunk) or _MONEY_SINGLE.search(chunk) \
            or _PLAIN_PAY.search(chunk)
        if hit:
            return re.sub(r"\s+", " ", hit.group(0)).strip()
    for pat in (_MONEY_RANGE, _MONEY_SINGLE):
        for hit in pat.finditer(text):
            value = hit.group(0)
            if "$" in value and _PAY_PERIOD.search(value):
                return re.sub(r"\s+", " ", value).strip()
    return ""


def missing_fields(job: dict) -> list:
    """Labels for the fields this post does not carry. The email
    counts as present when the post carries one directly OR the
    posting text prints one (the fill step already ran); location
    and salary count as present when the description states them
    explicitly."""
    missing = []
    if _blank(job, "location") and not _explicit_location(job):
        missing.append(LABELS["location"])
    if _blank(job, "application_email") and not find_application_email(job):
        missing.append(LABELS["application_email"])
    if _blank(job, "salary") and not _explicit_salary(job):
        missing.append(LABELS["salary"])
    if _blank(job, "description", "snippet"):
        missing.append(LABELS["description"])
    if _blank(job, "company"):
        missing.append(LABELS["company"])
    return missing


def annotate(job: dict) -> dict:
    """A copy of the job with explicit post-description fills applied
    (application email, labeled location, stated salary), plus its
    `missing_fields`. The input dict is never mutated — connectors
    keep their own records."""
    out = dict(job)
    if _blank(out, "location"):
        loc = _explicit_location(out)
        if loc:
            out["location"] = loc
    if _blank(out, "salary"):
        salary = _explicit_salary(out)
        if salary:
            out["salary"] = salary
    email = find_application_email(out)
    if email:
        out["application_email"] = email
    out["missing_fields"] = missing_fields(out)
    return out


def annotate_jobs(jobs: list) -> list:
    return [annotate(j) for j in jobs]
