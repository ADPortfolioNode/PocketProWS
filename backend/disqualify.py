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
- USA ONLY (Anthony, 2026-11-24): the posting's stated location is
  provably outside the USA — it names a non-US country, a major
  non-US city, or a non-US region (Europe, EMEA, APAC). Judged from
  the location field only: a bare "Remote", an empty location, or a
  US signal anywhere in the field (a state name, a ", ST" suffix,
  "USA" / "United States") is never omitted — unproven either way.

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


# ---------------------------------------------------------------- location
_US_STATES = (
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming", "district of columbia",
)
_US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI",
    "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC",
    "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
    "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}
_NON_US = (
    # countries and country-like names
    "netherlands", "holland", "germany", "france", "spain", "portugal",
    "italy", "belgium", "luxembourg", "austria", "switzerland", "poland",
    "czech", "slovakia", "hungary", "romania", "bulgaria", "croatia",
    "serbia", "greece", "turkey", "ukraine", "russia", "belarus",
    "estonia", "latvia", "lithuania", "denmark", "sweden", "norway",
    "finland", "iceland", "ireland", "united kingdom", "england",
    "scotland", "wales", "canada", "mexico", "brazil", "argentina",
    "chile", "colombia", "peru", "venezuela", "india", "pakistan",
    "bangladesh", "sri lanka", "nepal", "china", "japan", "korea",
    "taiwan", "vietnam", "thailand", "malaysia", "singapore",
    "indonesia", "philippines", "australia", "new zealand", "israel",
    "egypt", "morocco", "nigeria", "kenya", "ghana", "south africa",
    "united arab emirates", "saudi arabia", "qatar", "kuwait",
    # major non-US cities (US namesakes are rescued by the US checks)
    "london", "berlin", "munich", "hamburg", "frankfurt", "cologne",
    "amsterdam", "utrecht", "rotterdam", "eindhoven", "paris", "lyon",
    "madrid", "barcelona", "valencia", "lisbon", "porto", "dublin",
    "zurich", "geneva", "vienna", "warsaw", "krakow", "prague", "brno",
    "budapest", "stockholm", "oslo", "copenhagen", "helsinki",
    "brussels", "antwerp", "milan", "rome", "athens", "istanbul",
    "ankara", "toronto", "vancouver", "montreal", "ottawa", "calgary",
    "sydney", "melbourne", "brisbane", "perth", "auckland", "wellington",
    "bangalore", "bengaluru", "hyderabad", "mumbai", "delhi", "pune",
    "chennai", "kolkata", "tokyo", "osaka", "seoul", "shanghai",
    "beijing", "shenzhen", "taipei", "jakarta", "manila", "hanoi",
    "bangkok", "kuala lumpur", "dubai", "abu dhabi", "riyadh", "doha",
    "tel aviv", "jerusalem", "cairo", "lagos", "nairobi", "cape town",
    "johannesburg", "sao paulo", "buenos aires", "santiago", "bogota",
    "lima", "mexico city",
    # non-US regions
    "europe", "emea", "apac", "latam", "european union",
)
_NON_US_PAT = re.compile(r"\b(" + "|".join(re.escape(x) for x in _NON_US) + r")\b")
_US_PAT = re.compile(r"\b(usa|u\.s\.a\.|united states)\b")
_STATE_NAME_PAT = re.compile(r"\b(" + "|".join(re.escape(x) for x in _US_STATES) + r")\b")
_STATE_SUFFIX = re.compile(r",\s*([A-Z]{2})\s*$")


def _non_us_reason(job: dict):
    """'Outside the USA' reason when the posting's stated location is
    provably non-US; None when it is US, bare-remote, or unstated."""
    loc = (job.get("location") or "").strip()
    if not loc:
        return None
    low = loc.lower()
    if _US_PAT.search(low) or _STATE_NAME_PAT.search(low):
        return None
    suffix = _STATE_SUFFIX.search(loc)
    if suffix and suffix.group(1) in _US_STATE_CODES:
        return None
    if _NON_US_PAT.search(low) or re.search(r"\buk\b", low):
        return f"Outside the USA — located in {loc}"
    return None


def disqualify_reasons(client: dict, job: dict) -> list:
    """The reasons this posting's stated requirements rule this client
    out — empty when nothing provable rules them out."""
    reasons = []
    loc_reason = _non_us_reason(job)
    if loc_reason:
        reasons.append(loc_reason)
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
