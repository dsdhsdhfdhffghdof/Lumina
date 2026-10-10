"""Tests for filename-aware / page-aware / intent-aware retrieval.

Validates fixes for the user bug: a query that mentions a filename and a page
number should surface those pages even when there is no keyword overlap with
page content. Also exercises summarize + question-generation intents and the
grounded-citation guardrail.
"""
import io
import os
import re
import uuid
import asyncio
from datetime import datetime, timezone, timedelta

import pytest
import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

load_dotenv("/app/backend/.env")

API = "http://localhost:8001/api"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

NOT_FOUND = ("I couldn't find this information in your uploaded materials. "
             "Please upload the relevant page or document.")

TEST_SUFFIX = "@lumina-intent-test.local"

# ---------- PDF builders ----------

def build_math_pdf() -> bytes:
    """Two-page math-ish PDF (text layer, no OCR needed)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont("Helvetica", 12)
    y = 740
    for line in [
        "EXAMWIZARD STUDY MATERIAL UNIT 1 TOPIC 3",
        "Page 1 - Quadratic Equations",
        "A quadratic equation has the form ax^2 + bx + c = 0.",
        "The discriminant is defined as D = b^2 - 4ac.",
        "If D > 0 there are two real roots; if D = 0 one real root; if D < 0 two complex roots.",
        "The quadratic formula is x = (-b +/- sqrt(b^2 - 4ac)) / (2a).",
        "Example problem: Solve 2x^2 - 4x - 6 = 0 using the quadratic formula.",
    ]:
        c.drawString(60, y, line); y -= 18
    c.showPage()
    c.setFont("Helvetica", 12)
    y = 740
    for line in [
        "Page 2 - Derivatives",
        "The derivative of a function f at a point x is defined as",
        "f'(x) = lim_{h -> 0} (f(x+h) - f(x)) / h.",
        "Common rules include the power rule d/dx x^n = n x^(n-1),",
        "the product rule (uv)' = u'v + uv', and the chain rule.",
        "Practice: Differentiate f(x) = 3x^2 + 2x + 1.",
    ]:
        c.drawString(60, y, line); y -= 18
    c.showPage()
    c.save()
    return buf.getvalue()


# ---------- fixtures ----------

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


async def _mint(email: str):
    cli = AsyncIOMotorClient(MONGO_URL)
    db = cli[DB_NAME]
    uid = "user_" + uuid.uuid4().hex[:12]
    tok = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    exp = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    await db.users.insert_one({
        "user_id": uid, "google_id": "test_" + uid, "email": email,
        "name": "Test " + email.split("@")[0], "picture": "",
        "created_at": now, "first_sign_in_at": now, "last_sign_in_at": now,
        "onboarded": False, "preferred_language": "English",
    })
    await db.user_sessions.insert_one(
        {"user_id": uid, "session_token": tok, "created_at": now, "expires_at": exp}
    )
    cli.close()
    return uid, tok


@pytest.fixture(scope="module")
def user_a():
    email = f"a-{uuid.uuid4().hex[:6]}{TEST_SUFFIX}"
    uid, tok = asyncio.get_event_loop().run_until_complete(_mint(email))
    return {"user_id": uid, "token": tok, "email": email}


@pytest.fixture(scope="module")
def user_b():
    email = f"b-{uuid.uuid4().hex[:6]}{TEST_SUFFIX}"
    uid, tok = asyncio.get_event_loop().run_until_complete(_mint(email))
    return {"user_id": uid, "token": tok, "email": email}


@pytest.fixture(scope="module")
def user_c_no_materials():
    email = f"c-{uuid.uuid4().hex[:6]}{TEST_SUFFIX}"
    uid, tok = asyncio.get_event_loop().run_until_complete(_mint(email))
    return {"user_id": uid, "token": tok, "email": email}


@pytest.fixture(scope="module")
def http():
    with httpx.Client(base_url=API, timeout=180) as c:
        yield c


def auth(u):
    return {"Authorization": f"Bearer {u['token']}"}


EXAM_FILENAME = "EXAMWIZARD STUDY MATERIAL UNIT 1 TOPIC 3.pdf"


@pytest.fixture(scope="module")
def uploaded_material(http, user_a):
    """Upload the math PDF for user A once, return its material row."""
    pdf = build_math_pdf()
    r = http.post(
        "/materials/upload",
        files={"file": (EXAM_FILENAME, pdf, "application/pdf")},
        headers=auth(user_a),
    )
    assert r.status_code == 200, r.text
    mat = r.json()
    assert mat["status"] == "ready", f"Material not ready: {mat}"
    assert mat["page_count"] == 2
    return mat


@pytest.fixture(scope="module")
def uploaded_material_user_b(http, user_b):
    """Different content for user B to validate cross-user isolation."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont("Helvetica", 12)
    c.drawString(60, 740, "USER B PRIVATE NOTES - World History")
    c.drawString(60, 720, "The Roman Empire fell in 476 CE.")
    c.showPage()
    c.save()
    r = http.post(
        "/materials/upload",
        files={"file": ("UserB_History.pdf", buf.getvalue(), "application/pdf")},
        headers=auth(user_b),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready"
    return r.json()


@pytest.fixture(scope="module", autouse=True)
def cleanup(user_a, user_b, user_c_no_materials):
    yield
    async def _c():
        cli = AsyncIOMotorClient(MONGO_URL)
        db = cli[DB_NAME]
        users = await db.users.find(
            {"email": {"$regex": TEST_SUFFIX}}, {"user_id": 1}
        ).to_list(length=500)
        uids = [u["user_id"] for u in users]
        if uids:
            await db.user_sessions.delete_many({"user_id": {"$in": uids}})
            await db.materials.delete_many({"user_id": {"$in": uids}})
            await db.material_pages.delete_many({"user_id": {"$in": uids}})
            await db.chat_messages.delete_many({"user_id": {"$in": uids}})
            await db.users.delete_many({"user_id": {"$in": uids}})
        cli.close()
    asyncio.get_event_loop().run_until_complete(_c())


# ---------- helpers ----------

CITATION_RE = re.compile(r"\[([^\]]+?),\s*p\.(\d+)\]")


def extract_citations(ans: str):
    return CITATION_RE.findall(ans or "")


# ---------- tests ----------

def test_user_reported_query_grounded_with_citation(http, user_a, uploaded_material):
    """The exact failing user query must now return grounded=true with [filename, p.1]."""
    msg = f"What are the main concepts in page 1 of {EXAM_FILENAME}?"
    r = http.post("/tutor/chat", json={"message": msg}, headers=auth(user_a))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["grounded"] is True, f"Expected grounded, got: {data}"
    assert data["answer"] != NOT_FOUND
    assert len(data["citations"]) > 0
    cites = extract_citations(data["answer"])
    assert cites, f"Answer has no [filename, p.N] marker: {data['answer']}"
    # At least one citation names the uploaded file
    assert any(EXAM_FILENAME in fn for fn, _ in cites), f"Filename not cited: {cites}"
    # Citation list from API should include page 1
    pages = {c["page"] for c in data["citations"]}
    assert 1 in pages, f"Page 1 not in citations: {data['citations']}"


def test_summarize_intent_multi_citation(http, user_a, uploaded_material):
    r = http.post(
        "/tutor/chat", json={"message": "Summarize my materials"}, headers=auth(user_a)
    )
    assert r.status_code == 200
    data = r.json()
    assert data["grounded"] is True
    assert data["answer"] != NOT_FOUND
    cites = extract_citations(data["answer"])
    assert len(cites) >= 2, f"Expected multiple citations in summary, got {cites}"
    assert len(data["citations"]) >= 2


def test_question_generation_intent(http, user_a, uploaded_material):
    r = http.post(
        "/tutor/chat",
        json={"message": "Generate 5 practice questions from my material with answers"},
        headers=auth(user_a),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["grounded"] is True
    ans = data["answer"]
    # Numbered question list (at least 3 of 1./2./3./...)
    numbered = re.findall(r"(?m)^\s*(?:\*\*|__)?\s*(\d+)[\.\)]", ans)
    assert len(numbered) >= 3, f"Expected >=3 numbered questions, got: {ans[:400]}"
    cites = extract_citations(ans)
    assert cites, f"No citations in generated questions: {ans[:400]}"


def test_specific_math_problem(http, user_a, uploaded_material):
    r = http.post(
        "/tutor/chat",
        json={"message": "Solve 2x^2 - 4x - 6 = 0"},
        headers=auth(user_a),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["grounded"] is True
    assert extract_citations(data["answer"]), data["answer"][:300]


def test_page_specific_query_targets_page_2(http, user_a, uploaded_material):
    r = http.post(
        "/tutor/chat", json={"message": "summarize page 2"}, headers=auth(user_a)
    )
    assert r.status_code == 200
    data = r.json()
    assert data["grounded"] is True
    pages = {c["page"] for c in data["citations"]}
    assert 2 in pages, f"Page 2 not retrieved for 'summarize page 2': {pages}"


def test_filename_only_query_no_keyword_overlap(http, user_a, uploaded_material):
    """Query mentions filename but shares no vocab with page text."""
    r = http.post(
        "/tutor/chat",
        json={"message": f"tell me about {EXAM_FILENAME}"},
        headers=auth(user_a),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["grounded"] is True
    assert len(data["citations"]) > 0


def test_off_material_question_returns_exact_fallback(http, user_a, uploaded_material):
    r = http.post(
        "/tutor/chat",
        json={"message": "What is the capital of France?"},
        headers=auth(user_a),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["grounded"] is False
    assert data["answer"] == NOT_FOUND


def test_no_materials_user_gets_exact_fallback(http, user_c_no_materials):
    r = http.post(
        "/tutor/chat",
        json={"message": "Summarize my materials"},
        headers=auth(user_c_no_materials),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["grounded"] is False
    assert data["answer"] == NOT_FOUND
    assert data["sources_available"] == 0


def test_cross_user_isolation_summarize(http, user_b, uploaded_material_user_b, user_a, uploaded_material):
    """User B asking to summarize must not reference user A's EXAMWIZARD file."""
    r = http.post(
        "/tutor/chat",
        json={"message": "summarize my materials"},
        headers=auth(user_b),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["grounded"] is True
    # None of user B's citations should reference user A's file
    for c in data["citations"]:
        assert EXAM_FILENAME not in c["filename"], f"Cross-user leak: {c}"
    assert EXAM_FILENAME not in data["answer"]
