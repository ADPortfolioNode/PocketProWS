"""Missing fields on a searched job post (Anthony, 2026-11-25:
"search job post for missing fields" — both: flag them AND fill
what can be filled).

Every searched job is annotated with:
- `missing_fields`: human labels for the fields the post does not
  carry — location, application email, salary, description, company.
- `application_email`: filled in when the posting's own text prints
  one (reuses submission.find_application_email).

The honest limit, stated plainly: the application email is the
ONLY field that can be filled from the posting's own text. Location,
salary, description and company are flagged, never guessed — a
place read out of a snippet is not the job's location (the USA
filter judges the location field only), and a number in a snippet
is not a salary. A flagged field is a fact about the post, not a
defect in the app: the keyless boards mostly do not return pay.
"""

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


def missing_fields(job: dict) -> list:
    """Labels for the fields this post does not carry. The email
    counts as present when the post carries one directly OR the
    posting text prints one (the fill step already ran)."""
    missing = []
    if _blank(job, "location"):
        missing.append(LABELS["location"])
    if _blank(job, "application_email") and not find_application_email(job):
        missing.append(LABELS["application_email"])
    if _blank(job, "salary"):
        missing.append(LABELS["salary"])
    if _blank(job, "description", "snippet"):
        missing.append(LABELS["description"])
    if _blank(job, "company"):
        missing.append(LABELS["company"])
    return missing


def annotate(job: dict) -> dict:
    """A copy of the job with the email filled when the posting
    prints one, plus its `missing_fields`. The input dict is never
    mutated — connectors keep their own records."""
    out = dict(job)
    email = find_application_email(out)
    if email:
        out["application_email"] = email
    out["missing_fields"] = missing_fields(out)
    return out


def annotate_jobs(jobs: list) -> list:
    return [annotate(j) for j in jobs]
