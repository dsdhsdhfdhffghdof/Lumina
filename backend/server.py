from fastapi import FastAPI, APIRouter, UploadFile, File, HTTPException, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any, List, Optional
import os, uuid, io, re, logging, requests, mimetypes

from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone

from pypdf import PdfReader
from docx import Document as DocxDocument
import pytesseract
from PIL import Image
from pdf2image import convert_from_bytes

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]
STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
STORAGE_KEY: Optional[str] = None
APP_NAME = "lumina-academic"

NOT_FOUND_MESSAGE = "I couldn't find this information in your uploaded materials. Please upload the relevant page or document."
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB
ALLOWED_EXTS = {".pdf", ".docx", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp", ".tiff", ".bmp"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".bmp"}
OCR_LANG = os.environ.get("OCR_LANG", "eng")
OCR_PDF_DPI = int(os.environ.get("OCR_PDF_DPI", "200"))
OCR_MAX_PAGES = int(os.environ.get("OCR_MAX_PAGES", "40"))

app = FastAPI(title="Lumina Academic API")
api = APIRouter(prefix="/api")


# ---------- helpers ----------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_text(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def tokenize(t: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (t or "").lower())


STOPWORDS = {
    "the","a","an","and","or","of","to","in","on","for","is","are","was","were","be","been",
    "being","it","its","this","that","these","those","as","at","by","with","from","but","not",
    "what","which","who","whom","how","why","when","where","do","does","did","can","could",
    "should","would","will","shall","i","you","he","she","we","they","my","your","their",
    "me","him","her","us","them","so","if","then","than","there","here","about","into",
}


def keywords(q: str) -> List[str]:
    return [w for w in tokenize(q) if w not in STOPWORDS and len(w) > 2]


# ---------- storage ----------

def init_storage(force: bool = False) -> str:
    global STORAGE_KEY
    if STORAGE_KEY and not force:
        return STORAGE_KEY
    response = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": os.environ["EMERGENT_LLM_KEY"]}, timeout=30)
    response.raise_for_status()
    STORAGE_KEY = response.json()["storage_key"]
    return STORAGE_KEY


def _storage_request(method: str, path: str, *, data=None, content_type: Optional[str] = None, max_attempts: int = 3):
    url = f"{STORAGE_URL}/objects/{path}"
    last_exc: Optional[Exception] = None
    for attempt in range(max_attempts):
        key = init_storage(force=(attempt > 0))
        headers = {"X-Storage-Key": key}
        if content_type:
            headers["Content-Type"] = content_type
        try:
            r = requests.request(method, url, headers=headers, data=data, timeout=120)
        except requests.RequestException as exc:
            last_exc = exc
            continue
        if r.status_code < 400:
            return r
        if r.status_code in (401, 403, 404, 429) or 500 <= r.status_code < 600:
            last_exc = requests.HTTPError(f"{r.status_code} {r.text[:200]}", response=r)
            continue
        r.raise_for_status()
    if last_exc:
        raise last_exc
    raise RuntimeError("Storage request failed with no response")


def put_object(path: str, data: bytes, content_type: str) -> dict:
    r = _storage_request("PUT", path, data=data, content_type=content_type)
    return r.json()


def get_object(path: str) -> bytes:
    r = _storage_request("GET", path)
    return r.content


def delete_object(path: str) -> None:
    try:
        _storage_request("DELETE", path, max_attempts=2)
    except Exception:
        logging.warning("Storage delete failed for %s", path)


# ---------- extraction ----------

def _ocr_image(img: Image.Image) -> str:
    try:
        if img.mode not in ("L", "RGB"):
            img = img.convert("RGB")
        text = pytesseract.image_to_string(img, lang=OCR_LANG)
    except Exception as exc:
        logging.exception("OCR failed")
        raise ValueError(f"OCR failed: {exc}")
    return normalize_text(text or "")


def _ocr_pdf(data: bytes) -> List[dict]:
    try:
        images = convert_from_bytes(data, dpi=OCR_PDF_DPI, fmt="png")
    except Exception as exc:
        raise ValueError(f"Could not render PDF for OCR: {exc}")
    pages: List[dict] = []
    for i, img in enumerate(images[:OCR_MAX_PAGES], start=1):
        text = _ocr_image(img)
        if text:
            pages.append({"page": i, "text": text})
    return pages


def extract_pages(filename: str, data: bytes) -> List[dict]:
    """Return [{page: int, text: str}, ...]. Raise ValueError on unsupported/empty."""
    suffix = Path(filename).suffix.lower()
    pages: List[dict] = []
    if suffix == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(data))
            for i, page in enumerate(reader.pages, start=1):
                try:
                    text = normalize_text(page.extract_text() or "")
                except Exception:
                    text = ""
                if text:
                    pages.append({"page": i, "text": text})
        except Exception as exc:
            logging.warning("pypdf failed, will try OCR: %s", exc)
            pages = []
        # OCR fallback for scanned PDFs
        if not pages:
            pages = _ocr_pdf(data)
    elif suffix == ".docx":
        doc = DocxDocument(io.BytesIO(data))
        buf: List[str] = []
        page_num = 1
        for para in doc.paragraphs:
            txt = (para.text or "").strip()
            if txt:
                buf.append(txt)
            if sum(len(x) for x in buf) > 1800:
                pages.append({"page": page_num, "text": normalize_text(" ".join(buf))})
                buf = []
                page_num += 1
        if buf:
            pages.append({"page": page_num, "text": normalize_text(" ".join(buf))})
    elif suffix in {".txt", ".md"}:
        text = data.decode("utf-8", errors="ignore")
        chunks = []
        chunk: List[str] = []
        size = 0
        for line in text.splitlines():
            chunk.append(line)
            size += len(line) + 1
            if size > 1800:
                chunks.append("\n".join(chunk))
                chunk = []
                size = 0
        if chunk:
            chunks.append("\n".join(chunk))
        for i, c in enumerate(chunks, start=1):
            if normalize_text(c):
                pages.append({"page": i, "text": normalize_text(c)})
    elif suffix in IMAGE_EXTS:
        try:
            img = Image.open(io.BytesIO(data))
        except Exception as exc:
            raise ValueError(f"Could not open image: {exc}")
        text = _ocr_image(img)
        if text:
            pages.append({"page": 1, "text": text})
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    if not pages:
        raise ValueError("No readable text was found in this file. If it is a scanned document or photo, make sure the text is legible and try again.")
    return pages


# ---------- auth ----------

class AuthSession(BaseModel):
    session_id: str


async def current_user(request: Request) -> dict:
    token = request.cookies.get("session_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else None
    if not token:
        raise HTTPException(401, "Not authenticated")
    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session:
        raise HTTPException(401, "Session not found")
    expiry = datetime.fromisoformat(session["expires_at"]) if isinstance(session["expires_at"], str) else session["expires_at"]
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry < datetime.now(timezone.utc):
        raise HTTPException(401, "Session expired")
    user = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(401, "User not found")
    return user


@api.post("/auth/session")
async def create_session(payload: AuthSession, response: Response):
    try:
        result = requests.get(
            "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
            headers={"X-Session-ID": payload.session_id},
            timeout=30,
        )
        result.raise_for_status()
        identity = result.json()
    except requests.RequestException:
        raise HTTPException(401, "Google session could not be verified")

    user = await db.users.find_one({"email": identity["email"]}, {"_id": 0})
    ts = now_iso()
    if user:
        user_id = user["user_id"]
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"name": identity["name"], "picture": identity.get("picture", ""), "last_sign_in_at": ts}},
        )
    else:
        user_id = "user_" + uuid.uuid4().hex[:12]
        user = {
            "user_id": user_id,
            "google_id": identity.get("id", ""),
            "email": identity["email"],
            "name": identity["name"],
            "picture": identity.get("picture", ""),
            "created_at": ts,
            "first_sign_in_at": ts,
            "last_sign_in_at": ts,
            "onboarded": False,
            "preferred_language": "English",
        }
        await db.users.insert_one(user)

    expires_at = (datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=7)).isoformat()
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": identity["session_token"],
        "created_at": ts,
        "expires_at": expires_at,
    })
    response.set_cookie("session_token", identity["session_token"], max_age=604800, httponly=True, secure=True, samesite="none", path="/")
    saved = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    return saved


@api.get("/auth/me")
async def me(user: dict = Depends(current_user)):
    return user


@api.post("/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else None
    if token:
        await db.user_sessions.delete_many({"session_token": token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


# ---------- materials ----------

def material_public(doc: dict) -> dict:
    return {
        "id": doc["material_id"],
        "filename": doc["filename"],
        "type": doc.get("ext", "").replace(".", "").upper() or "FILE",
        "size": doc.get("size", 0),
        "page_count": doc.get("page_count", 0),
        "status": doc.get("status", "processing"),
        "error": doc.get("error"),
        "created_at": doc.get("created_at"),
    }


async def process_and_persist(user_id: str, material_id: str, filename: str, data: bytes, ext: str, content_type: str) -> dict:
    storage_path = f"{APP_NAME}/users/{user_id}/materials/{material_id}{ext}"
    storage_result = put_object(storage_path, data, content_type or "application/octet-stream")
    try:
        pages = extract_pages(filename, data)
    except ValueError as exc:
        await db.materials.update_one(
            {"material_id": material_id, "user_id": user_id},
            {"$set": {"status": "failed", "error": str(exc), "storage_path": storage_result["path"], "size": storage_result.get("size", len(data))}},
        )
        return {"status": "failed", "error": str(exc)}

    # Replace any previous page records (retry case)
    await db.material_pages.delete_many({"material_id": material_id, "user_id": user_id})
    docs = []
    for p in pages:
        docs.append({
            "page_id": uuid.uuid4().hex,
            "material_id": material_id,
            "user_id": user_id,
            "page_number": p["page"],
            "text": p["text"],
            "tokens": tokenize(p["text"]),
            "created_at": now_iso(),
        })
    if docs:
        await db.material_pages.insert_many(docs)

    await db.materials.update_one(
        {"material_id": material_id, "user_id": user_id},
        {"$set": {
            "status": "ready",
            "error": None,
            "page_count": len(pages),
            "storage_path": storage_result["path"],
            "size": storage_result.get("size", len(data)),
            "processed_at": now_iso(),
        }},
    )
    await db.users.update_one({"user_id": user_id}, {"$set": {"onboarded": True, "onboarded_at": now_iso()}})
    return {"status": "ready", "page_count": len(pages)}


@api.post("/materials/upload")
async def upload_material(file: UploadFile = File(...), user: dict = Depends(current_user)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, "Only PDF, DOCX, TXT, MD, or image files (PNG, JPG, JPEG, WEBP, TIFF, BMP) are supported.")
    data = await file.read()
    if not data:
        raise HTTPException(400, "The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File is larger than {MAX_UPLOAD_BYTES // (1024*1024)} MB.")

    material_id = "m_" + uuid.uuid4().hex[:12]
    doc = {
        "material_id": material_id,
        "user_id": user["user_id"],
        "filename": file.filename,
        "ext": ext,
        "content_type": file.content_type or "application/octet-stream",
        "size": len(data),
        "status": "processing",
        "error": None,
        "page_count": 0,
        "storage_path": None,
        "is_deleted": False,
        "created_at": now_iso(),
    }
    await db.materials.insert_one(doc)

    try:
        await process_and_persist(user["user_id"], material_id, file.filename, data, ext, file.content_type or "application/octet-stream")
    except requests.RequestException as exc:
        logging.exception("Object storage failed")
        await db.materials.update_one(
            {"material_id": material_id, "user_id": user["user_id"]},
            {"$set": {"status": "failed", "error": f"Storage error: {exc}"}},
        )

    saved = await db.materials.find_one({"material_id": material_id, "user_id": user["user_id"]}, {"_id": 0})
    return material_public(saved)


@api.get("/materials")
async def list_materials(user: dict = Depends(current_user)):
    cursor = db.materials.find({"user_id": user["user_id"], "is_deleted": {"$ne": True}}, {"_id": 0}).sort("created_at", -1)
    items = [material_public(d) async for d in cursor]
    return {"items": items, "count": len(items)}


async def owned_material(material_id: str, user_id: str) -> dict:
    m = await db.materials.find_one({"material_id": material_id, "user_id": user_id, "is_deleted": {"$ne": True}}, {"_id": 0})
    if not m:
        raise HTTPException(404, "Material not found")
    return m


@api.delete("/materials/{material_id}")
async def delete_material(material_id: str, user: dict = Depends(current_user)):
    m = await owned_material(material_id, user["user_id"])
    await db.materials.update_one(
        {"material_id": material_id, "user_id": user["user_id"]},
        {"$set": {"is_deleted": True, "deleted_at": now_iso()}},
    )
    await db.material_pages.delete_many({"material_id": material_id, "user_id": user["user_id"]})
    if m.get("storage_path"):
        try:
            delete_object(m["storage_path"])
        except requests.RequestException:
            logging.warning("Storage delete failed for %s", m["storage_path"])
    return {"ok": True}


@api.post("/materials/{material_id}/retry")
async def retry_material(material_id: str, user: dict = Depends(current_user)):
    m = await owned_material(material_id, user["user_id"])
    if not m.get("storage_path"):
        raise HTTPException(400, "Original file is not available for retry.")
    try:
        data = get_object(m["storage_path"])
    except requests.RequestException as exc:
        raise HTTPException(502, f"Could not fetch original file: {exc}")
    await db.materials.update_one(
        {"material_id": material_id, "user_id": user["user_id"]},
        {"$set": {"status": "processing", "error": None}},
    )
    await process_and_persist(user["user_id"], material_id, m["filename"], data, m["ext"], m.get("content_type") or "application/octet-stream")
    saved = await db.materials.find_one({"material_id": material_id, "user_id": user["user_id"]}, {"_id": 0})
    return material_public(saved)


@api.get("/materials/{material_id}/download")
async def download_material(material_id: str, user: dict = Depends(current_user)):
    m = await owned_material(material_id, user["user_id"])
    if not m.get("storage_path"):
        raise HTTPException(404, "File is not available")
    try:
        data = get_object(m["storage_path"])
    except requests.RequestException as exc:
        raise HTTPException(502, f"Could not fetch file: {exc}")
    media = m.get("content_type") or mimetypes.guess_type(m["filename"])[0] or "application/octet-stream"
    return StreamingResponse(io.BytesIO(data), media_type=media, headers={"Content-Disposition": f'inline; filename="{m["filename"]}"'})


@api.get("/materials/{material_id}/pages/{page_number}")
async def material_page(material_id: str, page_number: int, user: dict = Depends(current_user)):
    await owned_material(material_id, user["user_id"])
    page = await db.material_pages.find_one(
        {"material_id": material_id, "user_id": user["user_id"], "page_number": page_number},
        {"_id": 0, "tokens": 0},
    )
    if not page:
        raise HTTPException(404, "Page not found")
    return page


# ---------- onboarding ----------

@api.get("/onboarding/status")
async def onboarding_status(user: dict = Depends(current_user)):
    ready = await db.materials.count_documents({"user_id": user["user_id"], "is_deleted": {"$ne": True}, "status": "ready"})
    return {"onboarded": bool(user.get("onboarded")) and ready > 0, "ready_materials": ready}


# ---------- retrieval + tutor ----------

BROAD_INTENT_WORDS = {
    "summarize", "summarise", "summary", "overview", "outline", "recap",
    "explain", "describe", "introduce", "introduction",
    "questions", "quiz", "practice", "mcq", "problems", "exercises", "test",
    "flashcards", "flashcard",
    "main", "key", "important", "topics", "concepts", "ideas", "points",
    "list", "generate", "create", "give", "all",
}


def _detect_intent(q_lower: str) -> str:
    toks = set(tokenize(q_lower))
    if toks & {"questions", "quiz", "practice", "mcq", "problems", "exercises", "flashcards", "flashcard"}:
        return "questions"
    if toks & {"summarize", "summarise", "summary", "overview", "outline", "recap"}:
        return "summarize"
    if (toks & {"main", "key", "important", "topics", "concepts", "ideas", "points", "list", "all"}) and (
        toks & {"page", "pages", "chapter", "section", "document", "file", "material", "pdf", "unit", "topic"}
    ):
        return "summarize"
    return "specific"


def _mentioned_materials(mats: List[dict], q_lower: str) -> List[str]:
    matched: List[str] = []
    for m in mats:
        fn = (m.get("filename") or "").lower()
        if not fn:
            continue
        stem = fn.rsplit(".", 1)[0]
        if fn in q_lower or (len(stem) >= 4 and stem in q_lower):
            matched.append(m["material_id"])
    return matched


async def retrieve_pages(user_id: str, query: str, top_k: int = 6) -> List[dict]:
    q_lower = (query or "").lower()
    mats = await db.materials.find(
        {"user_id": user_id, "is_deleted": {"$ne": True}, "status": "ready"},
        {"_id": 0},
    ).to_list(length=200)
    if not mats:
        return []
    mat_name = {m["material_id"]: m.get("filename", "Unknown") for m in mats}
    mentioned = _mentioned_materials(mats, q_lower)
    intent = _detect_intent(q_lower)

    # Page number mention: "page N", "p. N", "pg N"
    page_match = re.search(r"\b(?:page|pg|p\.?)\s*(\d{1,4})\b", q_lower)
    target_page = int(page_match.group(1)) if page_match else None

    selected: List[dict] = []

    # 1) If the user explicitly names a file and/or page, return those exact pages.
    if mentioned:
        q: dict = {"user_id": user_id, "material_id": {"$in": mentioned}}
        if target_page is not None:
            q["page_number"] = target_page
        cursor = db.material_pages.find(q, {"_id": 0, "tokens": 0}).sort("page_number", 1).limit(max(top_k, 12))
        selected = [p async for p in cursor]

    # 2) Keyword retrieval over the (optionally filtered) pool.
    if not selected:
        kws = keywords(query)
        scoped: dict = {"user_id": user_id}
        if mentioned:
            scoped["material_id"] = {"$in": mentioned}
        if kws:
            scoped["tokens"] = {"$in": kws}
            cursor = db.material_pages.find(scoped, {"_id": 0, "tokens": 0}).limit(500)
            pool = [p async for p in cursor]
            if pool:
                kw_set = set(kws)
                scored = sorted(
                    ((sum(1 for t in tokenize(p["text"]) if t in kw_set), p) for p in pool),
                    key=lambda x: x[0], reverse=True,
                )
                selected = [p for _, p in scored[:top_k]]

    # 3) Broad intent (summarize / questions / overview) or empty retrieval: fetch top pages of the (named or all) materials.
    if (not selected) or intent in ("summarize", "questions"):
        q = {"user_id": user_id}
        if mentioned:
            q["material_id"] = {"$in": mentioned}
        cursor = db.material_pages.find(q, {"_id": 0, "tokens": 0}).sort([("material_id", 1), ("page_number", 1)]).limit(12)
        pool = [p async for p in cursor]
        if pool:
            # Merge with any keyword-selected pages (dedupe by page_id)
            seen = {p["page_id"] for p in selected}
            for p in pool:
                if p["page_id"] not in seen:
                    selected.append(p)
                    seen.add(p["page_id"])
            selected = selected[:max(top_k, 8)]

    for p in selected:
        p["filename"] = mat_name.get(p["material_id"], "Unknown")
    return selected


class ChatInput(BaseModel):
    message: str


async def llm_grounded_answer(prompt: str, session_id: str) -> str:
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        raise HTTPException(500, "LLM key is not configured")
    system = (
        "You are Lumina, an expert, patient study tutor. You answer ONLY from the Excerpts the student provides "
        "(from their own uploaded textbooks, slides, scans, and notes). Follow these rules strictly:\n"
        "1. GROUNDING: Do not use outside knowledge. Do not invent facts, references, page numbers, filenames, or formulas. "
        "Every substantive claim must be followed inline by a citation of the form [Filename, p.N], using ONLY the exact "
        "Filename and page numbers that appear in the Excerpts. If the Excerpts truly do not contain the information "
        f"needed to answer, respond with EXACTLY this sentence and nothing else: {NOT_FOUND_MESSAGE}\n"
        "2. OCR + MATH: The Excerpts may come from OCR of scans and may contain typos, missing symbols, or jumbled "
        "math. Infer the student's intended meaning from context, reconstruct equations using plain math notation "
        "(e.g. x^2, sqrt(x), (a+b)/c, integral from 0 to 1, sum, dy/dx), and define any symbols you use. If OCR is too "
        "garbled to interpret a particular formula, say so and point to the page citation.\n"
        "3. PEDAGOGY: Be concise and clear. Use short paragraphs, bullet lists, or numbered steps when they help. "
        "For math or multi-step problems, show the solution step-by-step and justify each step with a citation.\n"
        "4. SUMMARIES: When asked to summarize, give an organized outline of the main concepts, each line cited.\n"
        "5. QUESTIONS / QUIZZES: When asked to generate practice questions, output a numbered list. For each question "
        "include: the question text, (if MCQ) 4 options labelled A-D, the correct answer, a 1-sentence explanation, "
        "and the [Filename, p.N] citation for where the answer comes from.\n"
        "6. FORMAT: After the main answer, add a line that starts with 'Evidence:' listing the distinct citations used, "
        "separated by commas. Do not add citations that do not appear in the Excerpts."
    )
    chat = LlmChat(api_key=key, session_id=session_id, system_message=system).with_model("gemini", "gemini-3.1-pro-preview")
    chunks: List[str] = []
    async for event in chat.stream_message(UserMessage(text=prompt)):
        if isinstance(event, TextDelta):
            chunks.append(event.content)
        elif isinstance(event, StreamDone):
            break
    return "".join(chunks).strip()


@api.post("/tutor/chat")
async def tutor_chat(payload: ChatInput, user: dict = Depends(current_user)):
    question = (payload.message or "").strip()
    if not question:
        raise HTTPException(400, "Please ask a question.")
    ready_count = await db.materials.count_documents({"user_id": user["user_id"], "is_deleted": {"$ne": True}, "status": "ready"})
    if ready_count == 0:
        return {
            "answer": NOT_FOUND_MESSAGE,
            "citations": [],
            "grounded": False,
            "sources_available": 0,
        }

    pages = await retrieve_pages(user["user_id"], question, top_k=6)
    if not pages:
        answer = NOT_FOUND_MESSAGE
        record = {"id": uuid.uuid4().hex, "user_id": user["user_id"], "role": "assistant", "question": question, "answer": answer, "citations": [], "grounded": False, "created_at": now_iso()}
        await db.chat_messages.insert_one(record)
        return {"answer": answer, "citations": [], "grounded": False, "sources_available": ready_count}

    intent = _detect_intent(question.lower())
    excerpts_text = "\n\n".join(
        f"[{p['filename']}, p.{p['page_number']}]\n{p['text'][:1800]}" for p in pages
    )
    task_hint = {
        "summarize": (
            "The student wants a summary / overview. Produce an organized outline of the main concepts, "
            "formulas, and definitions found in the Excerpts. Use short bullets. Cite each bullet with "
            "[Filename, p.N]."
        ),
        "questions": (
            "The student wants practice questions. Generate 5 varied practice questions from the Excerpts "
            "(mix of multiple-choice with 4 options A-D, short-answer, and if the material contains math, "
            "at least one numerical/problem-solving question). For every question, provide the correct "
            "answer, a 1-sentence explanation, and a [Filename, p.N] citation."
        ),
        "specific": (
            "Answer the student's question directly and clearly, step-by-step when it is a math or multi-step "
            "problem. Keep every claim grounded in the Excerpts and cited."
        ),
    }[intent]
    prompt = (
        f"Student request: {question}\n\n"
        f"Task hint: {task_hint}\n\n"
        f"Excerpts from the student's uploaded materials (use ONLY these; they may contain OCR noise — "
        f"interpret math and formulas thoughtfully):\n{excerpts_text}\n\n"
        "Write your response following the system rules. Finish with an 'Evidence:' line listing citations. "
        f"If the Excerpts do not contain enough information, reply with exactly: {NOT_FOUND_MESSAGE}"
    )
    try:
        answer = await llm_grounded_answer(prompt, f"user-{user['user_id']}")
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("LLM call failed")
        raise HTTPException(502, f"Tutor is temporarily unavailable: {exc}")

    # Guardrail: if the model produced an answer with no recognizable citation and did not use the fallback, treat as ungrounded.
    allowed_tags = {f"[{p['filename']}, p.{p['page_number']}]" for p in pages}
    cited = any(tag in answer for tag in allowed_tags)
    if not cited and NOT_FOUND_MESSAGE not in answer:
        answer = NOT_FOUND_MESSAGE

    grounded = NOT_FOUND_MESSAGE not in answer
    citations = [
        {"material_id": p["material_id"], "filename": p["filename"], "page": p["page_number"], "excerpt": p["text"][:260]}
        for p in pages
    ] if grounded else []
    record = {"id": uuid.uuid4().hex, "user_id": user["user_id"], "role": "assistant", "question": question, "answer": answer, "citations": citations, "grounded": grounded, "created_at": now_iso()}
    await db.chat_messages.insert_one(record)
    return {"answer": answer, "citations": citations, "grounded": grounded, "sources_available": ready_count}


@api.get("/tutor/history")
async def tutor_history(user: dict = Depends(current_user), limit: int = 50):
    cursor = db.chat_messages.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).limit(min(limit, 200))
    items = [d async for d in cursor]
    items.reverse()
    return {"items": items}


# ---------- learner dashboard (user-scoped, computed from real data) ----------

@api.get("/dashboard")
async def dashboard(user: dict = Depends(current_user)):
    mats = await db.materials.find({"user_id": user["user_id"], "is_deleted": {"$ne": True}}, {"_id": 0}).to_list(length=200)
    ready = [m for m in mats if m.get("status") == "ready"]
    total_pages = sum(m.get("page_count", 0) for m in ready)
    questions = await db.chat_messages.count_documents({"user_id": user["user_id"]})
    grounded = await db.chat_messages.count_documents({"user_id": user["user_id"], "grounded": True})
    confidence = int(round(100 * grounded / questions)) if questions else 0
    return {
        "materials": [material_public(m) for m in mats],
        "ready_count": len(ready),
        "total_pages": total_pages,
        "questions": questions,
        "grounded": grounded,
        "confidence": confidence,
        "onboarded": bool(user.get("onboarded")) and len(ready) > 0,
    }


# ---------- misc ----------

@api.get("/")
async def root():
    return {"message": "Lumina Academic API", "status": "ok"}


app.include_router(api)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origin_regex=r".*", allow_methods=["*"], allow_headers=["*"])
logging.basicConfig(level=logging.INFO)


@app.on_event("shutdown")
async def shutdown():
    client.close()
