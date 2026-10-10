"""OCR-focused backend tests for Lumina Academic API.

Covers:
- Scanned PDF (no text layer) upload -> OCR fallback -> ready + text persisted
- PNG/JPEG upload -> OCR -> ready
- Blank image upload -> failed with sensible error (material row preserved)
- .gif rejected with 400
- Text-based PDF, DOCX, TXT, MD still work
- Tutor grounded answer on OCR'd scanned PDF
- Tutor grounded answer on OCR'd image
- Off-material fallback (exact phrase)
- Cross-user isolation on OCR'd materials
- Delete removes material + material_pages
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
from reportlab.lib.utils import ImageReader
from docx import Document as DocxDocument
from PIL import Image, ImageDraw, ImageFont

load_dotenv("/app/backend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

TEST_EMAIL_SUFFIX = "@lumina-ocr-test.local"

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _font(size: int) -> ImageFont.ImageFont:
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


# ---------- builders ----------

def build_image_with_text(lines, size=(1400, 900), fontsize=56) -> Image.Image:
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    f = _font(fontsize)
    y = 60
    for line in lines:
        draw.text((60, y), line, fill="black", font=f)
        y += fontsize + 24
    return img


def build_png_image(lines) -> bytes:
    buf = io.BytesIO()
    build_image_with_text(lines).save(buf, format="PNG")
    return buf.getvalue()


def build_jpeg_image(lines) -> bytes:
    buf = io.BytesIO()
    build_image_with_text(lines).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def build_blank_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(buf, format="PNG")
    return buf.getvalue()


def build_scanned_pdf(lines) -> bytes:
    """Build a PDF whose pages are rasterized images (no selectable text)."""
    img = build_image_with_text(lines, size=(1600, 2000), fontsize=64)
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    img_buf.seek(0)

    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=letter)
    width, height = letter
    c.drawImage(ImageReader(img_buf), 0, 0, width=width, height=height)
    c.showPage()
    c.save()
    return out.getvalue()


def build_text_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont("Helvetica", 14)
    c.drawString(72, 720, "Mitochondria are the powerhouse of the cell.")
    c.showPage()
    c.save()
    return buf.getvalue()


def build_docx() -> bytes:
    buf = io.BytesIO()
    d = DocxDocument()
    d.add_paragraph("DOCX content: Enzymes catalyze biochemical reactions.")
    d.save(buf)
    return buf.getvalue()


def build_txt() -> bytes:
    return b"TXT content: DNA stores genetic information."


def build_md() -> bytes:
    return b"# Heading\n\nMarkdown content: RNA transcribes DNA."


# ---------- session helpers ----------

async def _mint(email: str):
    cli = AsyncIOMotorClient(MONGO_URL)
    db = cli[DB_NAME]
    uid = "user_" + uuid.uuid4().hex[:12]
    tok = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    exp = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    await db.users.insert_one({
        "user_id": uid, "email": email, "name": "OCR Test",
        "created_at": now, "first_sign_in_at": now, "last_sign_in_at": now,
        "onboarded": False, "preferred_language": "English",
    })
    await db.user_sessions.insert_one({
        "user_id": uid, "session_token": tok, "created_at": now, "expires_at": exp,
    })
    cli.close()
    return uid, tok


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def user_a():
    email = f"a-{uuid.uuid4().hex[:6]}{TEST_EMAIL_SUFFIX}"
    uid, tok = asyncio.get_event_loop().run_until_complete(_mint(email))
    return {"user_id": uid, "token": tok, "email": email}


@pytest.fixture(scope="module")
def user_b():
    email = f"b-{uuid.uuid4().hex[:6]}{TEST_EMAIL_SUFFIX}"
    uid, tok = asyncio.get_event_loop().run_until_complete(_mint(email))
    return {"user_id": uid, "token": tok, "email": email}


@pytest.fixture(scope="module")
def http():
    # OCR can take up to ~20s per page
    with httpx.Client(base_url=API, timeout=180) as c:
        yield c


@pytest.fixture(scope="module", autouse=True)
def cleanup(user_a, user_b):
    yield
    async def _c():
        cli = AsyncIOMotorClient(MONGO_URL)
        db = cli[DB_NAME]
        test_users = await db.users.find({"email": {"$regex": TEST_EMAIL_SUFFIX}}, {"user_id": 1}).to_list(length=500)
        ids = [u["user_id"] for u in test_users]
        if ids:
            await db.user_sessions.delete_many({"user_id": {"$in": ids}})
            await db.users.delete_many({"user_id": {"$in": ids}})
            await db.materials.delete_many({"user_id": {"$in": ids}})
            await db.material_pages.delete_many({"user_id": {"$in": ids}})
            await db.chat_messages.delete_many({"user_id": {"$in": ids}})
        cli.close()
    asyncio.get_event_loop().run_until_complete(_c())


def auth(u):
    return {"Authorization": f"Bearer {u['token']}"}


# ---------- helper to query db ----------

async def _get_pages(material_id: str):
    cli = AsyncIOMotorClient(MONGO_URL)
    db = cli[DB_NAME]
    pages = await db.material_pages.find({"material_id": material_id}, {"_id": 0}).to_list(length=100)
    mat = await db.materials.find_one({"material_id": material_id}, {"_id": 0})
    cli.close()
    return mat, pages


# ---------- shared state across tests ----------

class S:
    scanned_pdf_id = None
    png_id = None
    jpeg_id = None
    blank_png_id = None
    text_pdf_id = None
    docx_id = None
    txt_id = None
    md_id = None
    image_user_b = None  # image for user B isolation test


# ---------- tests ----------

class TestOCRUploads:
    def test_scanned_pdf_ocr(self, http, user_a):
        """Scanned PDF (no text layer) -> OCR fallback -> ready + pages contain OCR text."""
        pdf = build_scanned_pdf([
            "Ribosomes synthesize proteins",
            "from mRNA inside every cell.",
        ])
        r = http.post("/materials/upload",
                      files={"file": ("scanned.pdf", pdf, "application/pdf")},
                      headers=auth(user_a))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "ready", f"status={data['status']} err={data.get('error')}"
        assert data["page_count"] >= 1
        assert data["type"] == "PDF"
        S.scanned_pdf_id = data["id"]

        mat, pages = asyncio.get_event_loop().run_until_complete(_get_pages(data["id"]))
        assert mat is not None
        assert len(pages) >= 1
        joined = " ".join(p["text"] for p in pages).lower()
        # allow some OCR noise -- require key words to appear
        assert "ribosomes" in joined or "ribosome" in joined, f"text={joined[:400]}"
        assert "proteins" in joined or "protein" in joined
        assert "mrna" in joined.replace(" ", "") or "mrna" in joined

    def test_png_ocr(self, http, user_a):
        png = build_png_image(["Photosynthesis converts", "light into chemical energy."])
        r = http.post("/materials/upload",
                      files={"file": ("note.png", png, "image/png")},
                      headers=auth(user_a))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "ready", f"err={data.get('error')}"
        assert data["page_count"] == 1
        assert data["type"] == "PNG"
        S.png_id = data["id"]
        _, pages = asyncio.get_event_loop().run_until_complete(_get_pages(data["id"]))
        joined = pages[0]["text"].lower()
        assert "photosynthesis" in joined or "photo" in joined

    def test_jpeg_ocr(self, http, user_a):
        jpg = build_jpeg_image(["Gravity pulls objects", "toward the Earth."])
        r = http.post("/materials/upload",
                      files={"file": ("note.jpg", jpg, "image/jpeg")},
                      headers=auth(user_a))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "ready", f"err={data.get('error')}"
        assert data["page_count"] == 1
        assert data["type"] in ("JPG", "JPEG")
        S.jpeg_id = data["id"]

    def test_blank_image_fails_gracefully(self, http, user_a):
        """Blank image -> status=failed, error present, material row preserved for retry."""
        png = build_blank_png()
        r = http.post("/materials/upload",
                      files={"file": ("blank.png", png, "image/png")},
                      headers=auth(user_a))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "failed", f"got {data['status']}"
        assert data.get("error"), "expected error message on failed upload"
        S.blank_png_id = data["id"]
        # material row must still exist (for retry)
        mat, _ = asyncio.get_event_loop().run_until_complete(_get_pages(data["id"]))
        assert mat is not None
        assert mat.get("status") == "failed"

    def test_gif_rejected_400(self, http, user_a):
        r = http.post("/materials/upload",
                      files={"file": ("a.gif", b"GIF89a\x00\x00", "image/gif")},
                      headers=auth(user_a))
        assert r.status_code == 400


class TestPreviouslySupportedStillWork:
    def test_text_pdf(self, http, user_a):
        r = http.post("/materials/upload",
                      files={"file": ("text.pdf", build_text_pdf(), "application/pdf")},
                      headers=auth(user_a))
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ready", data.get("error")
        S.text_pdf_id = data["id"]

    def test_docx(self, http, user_a):
        r = http.post("/materials/upload",
                      files={"file": ("n.docx", build_docx(),
                                      "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                      headers=auth(user_a))
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

    def test_txt(self, http, user_a):
        r = http.post("/materials/upload",
                      files={"file": ("n.txt", build_txt(), "text/plain")},
                      headers=auth(user_a))
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

    def test_md(self, http, user_a):
        r = http.post("/materials/upload",
                      files={"file": ("n.md", build_md(), "text/markdown")},
                      headers=auth(user_a))
        assert r.status_code == 200
        assert r.json()["status"] == "ready"


class TestTutorOnOCRMaterials:
    def test_tutor_grounded_on_scanned_pdf(self, http, user_a):
        assert S.scanned_pdf_id is not None, "scanned pdf must have been uploaded"
        r = http.post("/tutor/chat",
                      json={"message": "What do ribosomes do?"},
                      headers=auth(user_a), timeout=120)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["grounded"] is True, f"answer={data['answer'][:300]}"
        assert len(data["citations"]) > 0
        # At least one citation should reference the scanned.pdf filename and p.1
        found = any(c.get("filename") == "scanned.pdf" and c.get("page") == 1 for c in data["citations"])
        assert found, f"no citation for scanned.pdf p.1 in: {data['citations']}"
        # inline citation marker [scanned.pdf, p.1] should appear
        assert re.search(r"\[scanned\.pdf,\s*p\.1\]", data["answer"]), f"no [scanned.pdf, p.1] in: {data['answer'][:300]}"

    def test_tutor_grounded_on_image(self, http, user_b):
        # Upload a fresh image under user_b to test image-only grounding
        png = build_png_image(["The Mariana Trench is the", "deepest ocean trench on Earth."])
        up = http.post("/materials/upload",
                       files={"file": ("ocean.png", png, "image/png")},
                       headers=auth(user_b))
        assert up.status_code == 200, up.text
        assert up.json()["status"] == "ready"
        S.image_user_b = up.json()["id"]

        r = http.post("/tutor/chat",
                      json={"message": "What is the Mariana Trench?"},
                      headers=auth(user_b), timeout=120)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["grounded"] is True, f"answer={data['answer'][:300]}"
        assert any(c.get("filename") == "ocean.png" and c.get("page") == 1 for c in data["citations"])
        assert re.search(r"\[ocean\.png,\s*p\.1\]", data["answer"]), f"no [ocean.png, p.1] in: {data['answer'][:300]}"

    def test_tutor_off_material_fallback_exact(self, http, user_a):
        r = http.post("/tutor/chat",
                      json={"message": "Who won the 1998 FIFA World Cup?"},
                      headers=auth(user_a), timeout=120)
        assert r.status_code == 200
        data = r.json()
        assert data["grounded"] is False
        assert data["answer"] == (
            "I couldn't find this information in your uploaded materials. "
            "Please upload the relevant page or document."
        )


class TestIsolationAndDelete:
    def test_cross_user_isolation(self, http, user_a, user_b):
        # user_a has multiple materials; user_b only has ocean.png
        la = http.get("/materials", headers=auth(user_a)).json()
        lb = http.get("/materials", headers=auth(user_b)).json()
        a_ids = {i["id"] for i in la["items"]}
        b_ids = {i["id"] for i in lb["items"]}
        assert S.scanned_pdf_id in a_ids
        assert S.scanned_pdf_id not in b_ids
        # user_b cannot download/delete user_a's material
        assert http.get(f"/materials/{S.scanned_pdf_id}/download", headers=auth(user_b)).status_code == 404
        assert http.delete(f"/materials/{S.scanned_pdf_id}", headers=auth(user_b)).status_code == 404

    def test_delete_scanned_pdf_removes_pages(self, http, user_a):
        mid = S.scanned_pdf_id
        # confirm pages exist first
        _, pages_before = asyncio.get_event_loop().run_until_complete(_get_pages(mid))
        assert len(pages_before) >= 1
        r = http.delete(f"/materials/{mid}", headers=auth(user_a))
        assert r.status_code == 200
        # pages gone
        _, pages_after = asyncio.get_event_loop().run_until_complete(_get_pages(mid))
        assert pages_after == []
        # list excludes it
        items = http.get("/materials", headers=auth(user_a)).json()["items"]
        assert all(i["id"] != mid for i in items)
