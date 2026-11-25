"""Interview placement (Anthony, 2026-11-24): highlights and tone
are separate questions with separate fields. The old interview
asked both in one question and stored the whole answer as
highlights — a tone answer ('warm and friendly') landed in the
highlights field, the tone field stayed empty, and the letter
printed the tone as a paragraph. Tone is the letter's overall
posture, never a printed line."""
from fastapi.testclient import TestClient

from backend.main import app
from backend.profiles import INTERVIEW_QUESTIONS

client = TestClient(app)

ANSWERS = ["Anthony Dickerson", "AI Engineer", "AI Engineer",
           "Python", "Freelance 2024–present", "IBM AI Engineering",
           "A.A.S. IT, TCI", "Queens, NY — remote", "Either",
           "$100,000", "Shipped three AI products end to end",
           "warm and friendly"]


def test_highlights_and_tone_land_in_their_own_fields():
    keys = [q["key"] for q in INTERVIEW_QUESTIONS]
    assert keys[-2:] == ["cover_letter", "cover_letter_tone"]
    p = client.post("/api/profiles", json={"name": ""}).json()
    last = None
    for a in ANSWERS:
        last = client.post(f"/api/profiles/{p['id']}/interview/answer",
                           json={"answer": a}).json()
    assert last["complete"] is True
    got = client.get(f"/api/profiles/{p['id']}").json()["client"]
    assert got["cover_letter_highlights"] == "Shipped three AI products end to end"
    assert got["cover_letter_tone"] == "warm and friendly"
