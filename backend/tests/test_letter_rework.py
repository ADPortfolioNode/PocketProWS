"""Cover letter rework (Anthony, 2026-11-24): his live template
letter for the Berenschot posting printed the tone setting as a
bare paragraph ('warm and friendly.'), a garbled certification
line with a year-less date and a wrong count ('along with 18
further certification(s)'), 'a Ai developer consultant', a doubled
period after 'B.V.', an unformatted phone number, and lowercase
skill names. The template now produces a clean letter from the
same record, and a deterministic lint checks every letter even
when no LM rung answers to run the LM check."""
from backend import apply_pack, llm

CERTS = (["Professional Certificates IBM AI Engineering Professional "
          "Certificate — IBM / Coursera — Jul 11",
          "IBM AI Developer Professional Certificate",
          "Machine Learning with Python",
          "Introduction to Deep Learning & Neural Networks with Keras",
          "Introduction to Computer Vision and Image Processing",
          "Deep Neural Networks with PyTorch",
          "Building Deep Learning Models with TensorFlow",
          "AI Capstone Project with Deep Learning",
          "Python for Data Science, AI & Development",
          "Introduction to Artificial Intelligence (AI)",
          "Generative AI: Introduction and Applications",
          "Generative AI: Prompt Engineering Basics",
          "Building AI Powered Chatbots Without Programming",
          "Developing AI Applications with Python and Flask",
          "Building AI Applications with Watson APIs",
          "Introduction to Front-End Development",
          "Front-End Web UI Frameworks and Tools: Bootstrap 4",
          "Machine Learning with Python"])  # duplicate on file


def _client():
    return {"name": "Anthony Dickerson",
            "current_role": "Ai developer consultant",
            "email": "deoism@gmail.com", "phone": "7189140313",
            "linkedin": "https://www.linkedin.com/in/anthony-d-aidev/",
            "skills": ["api", "chromadb", "ci/cd", "css", "data entry",
                       "python"],
            "certifications": list(CERTS),
            "cover_letter_highlights": "warm and friendly",
            "cover_letter_tone": "warm and friendly"}


def _job():
    return {"id": "job1", "title": "Stagiair(e) Backend AI Developer",
            "company": "Berenschot Groep B.V.",
            "snippet": "You will work with api design, chromadb, ci/cd "
                       "pipelines, css and data entry tooling."}


def _letter():
    client, job = _client(), _job()
    return apply_pack.template_letter(client, job,
                                      apply_pack.fit_for(client, job))


def test_template_letter_is_clean():
    letter = _letter()
    # No doubled period after a company name ending in one.
    assert "B.V.." not in letter
    assert "position at Berenschot Groep B.V." in letter
    # The role is the record's, with the right article.
    assert "as an Ai developer consultant." in letter
    assert "as a Ai" not in letter
    # Skills are presented properly, not as lowercase digest tokens.
    assert "API" in letter and "ChromaDB" in letter and "CI/CD" in letter
    # Certifications: label stripped, partial date dropped, true
    # deduplicated count, no hedged plural.
    assert "Professional Certificates IBM" not in letter
    assert "Jul 11" not in letter
    assert "(s)" not in letter
    assert "17 in total on file" in letter
    assert "IBM AI Engineering Professional Certificate" in letter
    # The tone is the letter's overall posture — it is never
    # printed, even though the tone text sits in the highlights
    # field on this record (the old interview's combined question).
    assert "warm and friendly" not in letter.lower()
    # The phone's digits are the record's, formatted for a letter.
    assert "718-914-0313" in letter
    assert "7189140313" not in letter


def test_content_fragment_is_woven_not_standalone():
    client, job = _client(), _job()
    client["cover_letter_highlights"] = "team leadership"
    letter = apply_pack.template_letter(client, job,
                                        apply_pack.fit_for(client, job))
    assert "I bring a team leadership approach to my work." in letter
    assert "warm and friendly" not in letter.lower()


def test_tone_like_highlights_with_empty_tone_field_never_print():
    # Deo's live record shape (2026-11-25): the tone answer sits in
    # highlights and the tone field is empty. The tone must shape
    # the letter, not be woven into its middle.
    client, job = _client(), _job()
    client["cover_letter_tone"] = ""
    fit = apply_pack.fit_for(client, job)
    letter = apply_pack.template_letter(client, job, fit)
    assert "warm and friendly" not in letter.lower()
    assert apply_pack.lint_letter(client, job, fit, letter) == []
    facts = apply_pack._facts_block(client, job, fit)
    assert "Tone on record" in facts and "warm and friendly" in facts
    assert "Highlights the applicant asked to include: \n" in facts
    woven = letter.replace(
        "I would welcome",
        "I bring a warm and friendly approach to my work.\n\n"
        "I would welcome")
    issues = apply_pack.lint_letter(client, job, fit, woven)
    assert "tone setting is printed" in " ".join(issues)


def test_lint_passes_the_fixed_template():
    client, job = _client(), _job()
    fit = apply_pack.fit_for(client, job)
    letter = apply_pack.template_letter(client, job, fit)
    assert apply_pack.lint_letter(client, job, fit, letter) == []


def test_lint_catches_the_old_defects():
    client, job = _client(), _job()
    fit = apply_pack.fit_for(client, job)
    old = ("Dear Berenschot Groep B.V. hiring team,\n\n"
           "I am applying for the Stagiair(e) Backend AI Developer "
           "position at Berenschot Groep B.V.. I currently work as a "
           "Ai developer consultant.\n\n"
           "My resume covers the skills this posting calls for. "
           "I also hold X, along with 18 further certification(s).\n\n"
           "warm and friendly.\n\nSincerely,\nAnthony Dickerson\n"
           "deoism@gmail.com · 718-914-0413")
    issues = apply_pack.lint_letter(client, job, fit, old)
    joined = " ".join(issues)
    assert "tone setting is printed" in joined
    assert "hedged plural" in joined
    assert "doubled period" in joined
    assert "wrong article" in joined
    assert "phone number in the letter does not match" in joined
    assert "certification count does not match" in joined


def test_pack_carries_lint_even_when_lm_is_down(monkeypatch):
    monkeypatch.setattr(llm, "generate",
                        lambda prompt: {"text": None, "provider": None,
                                        "errors": {"gemini": "HTTP 429"}})
    pack = apply_pack.build_pack(_client(), _job())
    assert pack["provider"] == "template"
    assert pack["letter_check"]["checked"] is False
    assert pack["letter_check"]["lint_issues"] == []
