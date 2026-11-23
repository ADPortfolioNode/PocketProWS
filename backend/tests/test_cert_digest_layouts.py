"""Certificate titles read from the Coursera layout's own anchors.

The old heuristic took the longest line in a window around 'has
successfully completed' — on real certificates that is the
signatory's job title, and titles that wrap two lines came back
truncated. These fixtures mirror the extracted-text layouts of real
certificates (verified against the client's own 17 PDFs, 17/17).
"""
from backend.profiles import digest_text

CHATBOTS = """
Feb 19, 2024
Anthony
Dickerson
Building AI Powered Chatbots Without
Programming
an online non-credit course authorized by IBM and offered through Coursera
has successfully completed
Antonio Cangiano
Engineering Manager and AI Specialist
IBM Digital Business Group
Verify at:
https://coursera.org/verify/ZKHA7Y7GMXS2
"""

BOOTSTRAP = """
May 12, 2022
Anthony
Dickerson
Front-End Web UI Frameworks and Tools:
Bootstrap 4
an online non-credit course authorized by The Hong Kong University of Science and
Technology and offered through Coursera
has successfully completed
Jogesh K. Muppala
Associate Professor, Department of Computer Science and Engineering
The Hong Kong University of Science and Technology
Verify at:
https://coursera.org/verify/ZWEQ7XXCZ6G5
"""

WRAPPED = """
May 14, 2024
Anthony
Dickerson
Introduction to Computer Vision and Image
Processing
an online non-credit course authorized by IBM and offered through Coursera
has successfully completed
Aije Egwaikhide
Senior Data Scientist
IBM
Verify at:
https://coursera.org/verify/KZ2DZSKBW4GP
"""

PROGRAM = """
6 Courses
Machine Learning with
Python
Jul 11, 2024
Anthony
Dickerson
has successfully completed the online, non-credit Professional
Certiﬁcate
IBM AI Engineering
Learners who have completed this 6 course Professional Certiﬁcate
have a practical understanding of Machine Learning (ML) & Deep
Learning (DL).
"""

ONE_LINE_NAME = """
Feb 1, 2024
Anthony Dickerson
Python for Data Science, AI & Development
an online non-credit course authorized by IBM and offered through Coursera
has successfully completed
"""


def test_signatory_title_is_not_the_credential():
    assert digest_text(CHATBOTS)["certifications"] == [
        "Building AI Powered Chatbots Without Programming"]


def test_long_signatory_title_still_not_the_credential():
    assert digest_text(BOOTSTRAP)["certifications"] == [
        "Front-End Web UI Frameworks and Tools: Bootstrap 4"]


def test_wrapped_title_is_joined_not_truncated():
    assert digest_text(WRAPPED)["certifications"] == [
        "Introduction to Computer Vision and Image Processing"]


def test_professional_certificate_program_name():
    assert digest_text(PROGRAM)["certifications"] == [
        "IBM AI Engineering Professional Certificate"]


def test_one_line_name_is_not_part_of_the_title():
    assert digest_text(ONE_LINE_NAME)["certifications"] == [
        "Python for Data Science, AI & Development"]


def test_resume_certifications_line_still_wins():
    text = "Anthony Dickerson\nCertifications: IBM AI Engineering\nSkills: python"
    assert "IBM AI Engineering" in digest_text(text)["certifications"]
