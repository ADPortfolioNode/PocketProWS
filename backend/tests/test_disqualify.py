"""Disqualifier filter (Anthony, 2026-11-22): omit jobs whose stated
requirements the profile PROVABLY fails — degree level, named
certifications, clearance. Softened requirements ("preferred",
"or equivalent") and unprovable ones never omit."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend import disqualify
from backend.main import app

client = TestClient(app)

ASSOCIATE = {"education": ["A.A.S. IT Web Development, LaGuardia Community College"],
             "certifications": ["IBM AI Engineering Professional Certificate"],
             "skills": ["python"]}
BACHELOR = {"education": ["B.S. Computer Science, NYU"], "certifications": [], "skills": []}
NO_EDU = {"education": [], "certifications": [], "skills": []}


def job(snippet, title="Developer"):
    return {"id": "j1", "title": title, "company": "Acme", "snippet": snippet}


def test_degree_above_the_record_omits():
    r = disqualify.disqualify_reasons(ASSOCIATE, job("Requirements: Bachelor's degree in Computer Science. Python experience."))
    assert any("bachelor" in x.lower() for x in r)
    r = disqualify.disqualify_reasons(ASSOCIATE, job("Master's degree in Data Science required for this role."))
    assert any("master" in x.lower() for x in r)


def test_degree_at_or_below_the_record_keeps():
    assert disqualify.disqualify_reasons(BACHELOR, job("Bachelor's degree required.")) == []
    assert disqualify.disqualify_reasons(ASSOCIATE, job("Associate degree in IT required.")) == []


def test_softened_degrees_never_omit():
    assert disqualify.disqualify_reasons(ASSOCIATE, job("Bachelor's degree preferred.")) == []
    assert disqualify.disqualify_reasons(ASSOCIATE, job("Bachelor's degree or equivalent experience.")) == []
    assert disqualify.disqualify_reasons(ASSOCIATE, job("Master's degree a plus.")) == []


def test_no_education_on_file_means_no_degree_filtering():
    assert disqualify.disqualify_reasons(NO_EDU, job("PhD in Physics required. Bachelor's degree required.")) == []


def test_named_certification_required_and_missing_omits():
    r = disqualify.disqualify_reasons(ASSOCIATE, job("Must hold AWS Certified Solutions Architect. Python a plus."))
    assert any("AWS" in x for x in r)
    r = disqualify.disqualify_reasons(ASSOCIATE, job("PMP certification required to lead projects."))
    assert any("PMP" in x for x in r)


def test_named_certification_held_or_softened_keeps():
    holder = {"education": [], "certifications": ["AWS Certified Cloud Practitioner"], "skills": []}
    assert disqualify.disqualify_reasons(holder, job("AWS Certified required for this role.")) == []
    assert disqualify.disqualify_reasons(ASSOCIATE, job("PMP preferred but not required.")) == []


def test_certification_as_stack_topic_keeps():
    # Regression (live find, 2026-11-22): Kayak/MSF postings mentioned
    # CKA as part of a stack and were wrongly omitted. A topic mention
    # without requirement language is not a gate.
    assert disqualify.disqualify_reasons(ASSOCIATE, job("Our stack: Kubernetes, CKA, Terraform, Docker.")) == []
    r = disqualify.disqualify_reasons(ASSOCIATE, job("CKA certification required for this platform role."))
    assert any("CKA" in x for x in r)


def test_generic_certification_with_none_on_file_omits():
    r = disqualify.disqualify_reasons(NO_EDU, job("A current certification is required for this position."))
    assert any("certification" in x.lower() for x in r)
    assert disqualify.disqualify_reasons(ASSOCIATE, job("A current certification is required for this position.")) == []


def test_clearance_required_omits():
    r = disqualify.disqualify_reasons(BACHELOR, job("Active Top Secret security clearance required."))
    assert any("clearance" in x.lower() for x in r)
    assert disqualify.disqualify_reasons(BACHELOR, job("We value clear communication.")) == []


def test_unprovable_requirements_never_omit():
    # Years of experience and wish-list skills are not provable from the
    # record — the apply pack's fit check covers them instead.
    assert disqualify.disqualify_reasons(ASSOCIATE, job("10+ years of experience required. Kubernetes expert needed.")) == []


def test_search_endpoint_omits_and_reports(monkeypatch):
    import backend.main as main_mod

    class FakeConnector:
        name = "fakeboard"

        def search(self, q, location, limit):
            jobs = [
                {"id": "keep1", "title": "Python Dev", "company": "Acme", "location": "Remote",
                 "source": "fakeboard", "url": "https://x/1", "snippet": "Python and FastAPI work."},
                {"id": "drop1", "title": "Data Scientist", "company": "Beta", "location": "NYC",
                 "source": "fakeboard", "url": "https://x/2", "snippet": "PhD in Statistics required. Master's degree required."},
            ]
            return SimpleNamespace(source="fakeboard", status="ok", message="", jobs=jobs)

    monkeypatch.setattr(main_mod, "CONNECTORS", [FakeConnector()])
    p = client.post("/api/profiles", json={"name": "Anthony Dickerson"}).json()
    from backend import profiles as profiles_mod
    store = profiles_mod._load()
    store[p["id"]]["client"]["education"] = ["A.A.S. IT Web Development, LaGuardia Community College"]
    profiles_mod._save(store)
    r = client.get("/api/jobs/search", params={"q": "dev", "source": "fakeboard", "profile_id": p["id"]})
    body = r.json()
    assert body["total"] == 1 and body["omitted_count"] == 1
    assert body["omitted"][0]["id"] == "drop1" and "degree" in body["omitted"][0]["reasons"][0]
    saved = client.get(f"/api/profiles/{p['id']}/saved-jobs").json()["saved_jobs"]
    assert [j["id"] for j in saved] == ["keep1"]  # the omitted job was never saved


# ------------------------------------------------------- USA only (2026-11-24)
def _loc_job(location, snippet="Python role."):
    return {"id": "j2", "title": "Developer", "company": "Acme",
            "snippet": snippet, "location": location}


def test_non_us_locations_omit():
    for loc in ("Utrecht, Netherlands", "Berlin, Germany", "London",
                "Toronto, Canada", "Bangalore, India", "Remote - Europe",
                "EMEA", "Sydney, Australia"):
        r = disqualify.disqualify_reasons(NO_EDU, _loc_job(loc))
        assert any("Outside the USA" in x for x in r), loc


def test_us_and_unproven_locations_keep():
    for loc in ("New York, NY", "Austin, TX", "Queens, New York",
                "United States", "Remote - US", "Remote", "Worldwide",
                "", "Paris, TX", "London, OH"):
        r = disqualify.disqualify_reasons(NO_EDU, _loc_job(loc))
        assert not any("Outside the USA" in x for x in r), loc


def test_missing_location_field_keeps():
    j = {"id": "j3", "title": "Developer", "company": "Acme",
         "snippet": "Python role."}
    assert disqualify.disqualify_reasons(NO_EDU, j) == []
