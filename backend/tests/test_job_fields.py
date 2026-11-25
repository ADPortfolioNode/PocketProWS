"""Missing-fields annotation on searched job posts (2026-11-25):
flag what a post does not carry, fill the application email when
the posting prints one, never guess the rest."""

from backend.job_fields import annotate, annotate_jobs, missing_fields

FULL = {
    "id": "x-1", "title": "AI Engineer", "company": "Acme",
    "location": "New York, NY", "url": "https://example.com/jobs/1",
    "snippet": "Build RAG systems. Apply by email to jobs@acme.com.",
    "salary": "$120,000 - $150,000",
}


def test_full_post_has_nothing_missing_and_email_filled():
    out = annotate(FULL)
    assert out["missing_fields"] == []
    assert out["application_email"] == "jobs@acme.com"


def test_board_post_without_salary_or_email_flags_both():
    job = {k: v for k, v in FULL.items() if k not in ("salary",)}
    job["snippet"] = "Build RAG systems."
    assert missing_fields(job) == ["application email", "salary"]


def test_blank_salary_counts_as_missing():
    job = dict(FULL, salary="  ")
    assert "salary" in missing_fields(job)


def test_missing_location_description_company_each_flagged():
    assert "location" in missing_fields(dict(FULL, location=""))
    assert "description" in missing_fields(dict(FULL, snippet=""))
    assert "company" in missing_fields(dict(FULL, company=""))


def test_email_with_trailing_period_is_filled_clean():
    job = dict(FULL, snippet="Send your resume to jobs@acme.com.")
    assert annotate(job)["application_email"] == "jobs@acme.com"
    assert "application email" not in annotate(job)["missing_fields"]


def test_post_description_is_used_for_email_fill():
    job = dict(FULL, snippet="",
               description="Build RAG systems. Apply by email to jobs@acme.com.")
    out = annotate(job)
    assert out["application_email"] == "jobs@acme.com"
    assert out["missing_fields"] == []


def test_direct_application_email_counts_as_present():
    job = dict(FULL, application_email="hiring@acme.com", snippet="Build RAG systems.")
    assert "application email" not in missing_fields(job)


def test_annotate_never_mutates_the_input():
    job = dict(FULL)
    annotate(job)
    assert "missing_fields" not in job
    assert "application_email" not in job


def test_annotate_jobs_maps_a_list():
    outs = annotate_jobs([FULL, dict(FULL, location="")])
    assert outs[0]["missing_fields"] == []
    assert outs[1]["missing_fields"] == ["location"]
