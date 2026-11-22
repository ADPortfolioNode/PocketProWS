"""Disqualifier filter (Anthony, 2026-11-22): omit jobs whose STATED
requirements the client's profile provably fails — "omit jobs that
would disqualify me".

A job is omitted only on a PROVEN mismatch between the posting's own
words and facts on the profile:

- DEGREE: the posting names a degree level (in a sentence that is not
  softened by "preferred", "a plus", "nice to have" or "or
  equivalent") higher than the highest degree on the client's record.
  No education on file -> no degree filtering (unproven either way).
- CERTIFICATIONS: the posting requires a named credential (AWS
  Certified, PMP, CISSP, ...) that is not among the client's
  certifications; or requires a certification generically while the
  client has none on file.
- CLEARANCE: the posting requires a security clearance; the profile
  has no way to hold one, so it is never on file.

Anything else — years of experience, citizenship, skills the posting
would like — is NOT filtered: the profile cannot prove it, and the
apply pack's fit check already shows skill gaps honestly. Omitted
jobs are reported with their reasons, never silently dropped, and
they are not saved to the profile.
"""
import re

# ---------------------------------------------------------------- degrees
_LEVELS = [
    (5, "doctorate", re.compile(r"\b(ph\.?d|doctorate|doctoral)\b")),
    (4, "master's", re.compile(r"\b(master'?s?|m\.?s\.?|m\.?a\.?|mba|m\.?b\.?a\.?)\b")),
    (3, "bachelor's", re.compile(r"\b(bachelor'?s?|b\.?s\.?|b\.?a\.?|undergraduate degree)\b")),
    (2, "associate", re.compile(r"\b(associate'?s?|a\.?a\.?s\.?|a\.?a\.?)\b")),
]
_SOFTENERS = ("preferred", "a plus", "nice to have", "or equivalent",
              "ideally", "bonus", "not required", "not necessary")


def _sentences(text: str) -> list:
    return [s.strip() for s in re.split(r"[.!?;\n]+", text or "") if s.strip()]


def _client_degree_level(client: dict) -> int:
    """Highest degree level named anywhere in the education record;
    0 when nothing recognizable is on file."""
    text = " ".join(client.get("education") or []).lower()
    for level, _name, pat in _LEVELS:
        if pat.search(text):
            return level
    return 0


def _required_degree_level(job: dict) -> int:
    text = " ".join([job.get("title", ""), job.get("snippet", "")])
    required = 0
    for sent in _sentences(text):
        low = sent.lower()
        if any(s in low for s in _SOFTENERS):
            continue
        if "degree" not in low and not re.search(r"\b(ph\.?d|mba)\b", low):
            continue
        for level, _name, pat in _LEVELS:
            if pat.search(low):
                required = max(required, level)
    return required


def _level_name(level: int) -> str:
    return next((name for lv, name, _p in _LEVELS if lv == level), str(level))


# ---------------------------------------------------------- certifications
_NAMED_CERTS = {
    "aws certified": ("AWS Certified", ("aws",)),
    "pmp": ("PMP", ("pmp",)), "cissp": ("CISSP", ("cissp",)),
    "security+": ("Security+", ("security+", "security plus")),
    "ccna": ("CCNA", ("ccna",)),
    "comptia a+": ("CompTIA A+", ("a+", "comptia")),
    "scrum master": ("Certified Scrum Master", ("scrum",)),
    "cka": ("CKA", ("cka", "kubernetes")), "cpa": ("CPA", ("cpa",)),
    "azure certified": ("Microsoft Azure Certified", ("azure",)),
    "salesforce certified": ("Salesforce Certified", ("salesforce",)),
    "phr": ("PHR", ("phr",)), "shrm": ("SHRM", ("shrm",)),
    "series 7": ("Series 7", ("series 7",)),
    "real estate license": ("Real Estate License", ("real estate",)),
    "cdl": ("CDL", ("cdl",)),
}
_GENERIC_CERT = re.compile(
    r"(certification|certificate|licen[cs]e)\s+(is\s+)?required"
    r"|must\s+(hold|have|possess|be)\s+[^.]{0,40}(certif|licen[cs])", re.I)
_CLEARANCE = re.compile(
    r"(security clearance|ts/sci|top secret|secret clearance)", re.I)
_CLEARANCE_HARD = re.compile(r"(required|must|active|current|hold|possess)", re.I)


def disqualify_reasons(client: dict, job: dict) -> list:
    """The reasons this posting's stated requirements rule this client
    out — empty when nothing provable rules them out."""
    reasons = []
    text = " ".join([job.get("title", ""), job.get("snippet", "")])
    low = text.lower()

    required_level = _required_degree_level(job)
    client_level = _client_degree_level(client)
    if required_level and client_level and required_level > client_level:
        reasons.append(f"Requires a {_level_name(required_level)} degree — "
                       f"highest on file is {_level_name(client_level)}")

    certs_text = " ".join(client.get("certifications") or []).lower()
    hard_sentences = [s.lower() for s in _sentences(text)
                      if not any(sf in s.lower() for sf in _SOFTENERS)]
    # A named credential only disqualifies when its sentence carries
    # requirement language — the same words in a tech-stack list
    # ("our stack: Kubernetes, CKA, Terraform") are a topic, not a
    # gate. ("Certified" inside the name itself counts.)
    req_words = re.compile(r"\b(required|must|needs?|hold|possess|certification|certified|license[ds]?)\b")
    for name, (label, aliases) in _NAMED_CERTS.items():
        name_pat = re.compile(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])")
        if any(name_pat.search(s) and req_words.search(s) for s in hard_sentences) \
                and not any(a in certs_text for a in aliases):
            reasons.append(f"Requires {label} certification — not on file")
    if _GENERIC_CERT.search(text) and not (client.get("certifications") or []):
        if not any("certification" in r for r in reasons):
            reasons.append("Requires a certification — none on file")

    if _CLEARANCE.search(text) and _CLEARANCE_HARD.search(text):
        reasons.append("Requires a security clearance — none on file")
    return reasons


def filter_jobs(client: dict, jobs: list) -> tuple:
    """Split jobs into (kept, omitted); omitted entries carry reasons."""
    kept, omitted = [], []
    for job in jobs:
        reasons = disqualify_reasons(client, job)
        if reasons:
            omitted.append({"id": job.get("id", ""), "title": job.get("title", ""),
                            "company": job.get("company", ""), "reasons": reasons})
        else:
            kept.append(job)
    return kept, omitted
