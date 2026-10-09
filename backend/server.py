from fastapi import FastAPI, APIRouter, UploadFile, File, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any, List
import os, uuid, json, logging, requests

from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]
STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
STORAGE_KEY = None
APP_NAME = "lumina-academic"

app = FastAPI(title="Lumina Academic API")
api = APIRouter(prefix="/api")

TOPICS = [
    {"id": "t1", "name": "Cellular respiration", "detail": "How cells convert glucose into usable energy", "mastery": 74, "color": "terracotta", "prerequisite": "Cell structure"},
    {"id": "t2", "name": "Glycolysis", "detail": "The ten-step pathway that begins glucose breakdown", "mastery": 61, "color": "ochre", "prerequisite": "Cellular respiration"},
    {"id": "t3", "name": "Krebs cycle", "detail": "Carbon oxidation and electron carrier production", "mastery": 82, "color": "forest", "prerequisite": "Acetyl-CoA"},
    {"id": "t4", "name": "Electron transport chain", "detail": "A proton gradient powers ATP synthase", "mastery": 48, "color": "rose", "prerequisite": "Redox reactions"},
]
SOURCES = [
    {"id": "s1", "name": "Week 04 · Cellular Respiration.pdf", "type": "PDF", "meta": "24 pages · processed", "status": "Ready", "accent": "terracotta", "topics": 4},
    {"id": "s2", "name": "Mitochondria & ATP · Lecture 04.pptx", "type": "SLIDES", "meta": "18 slides · diagrams extracted", "status": "Ready", "accent": "forest", "topics": 3},
    {"id": "s3", "name": "Office hours · 14:32 recording.mp4", "type": "VIDEO", "meta": "42:18 · transcript indexed", "status": "Ready", "accent": "ochre", "topics": 5},
]
EXCERPTS = [
    {"id": "e1", "source_id": "s1", "title": "The purpose of respiration", "quote": "Cellular respiration is the controlled release of energy from organic molecules, usually glucose, to make ATP.", "location": "Page 3", "topic": "Cellular respiration"},
    {"id": "e2", "source_id": "s2", "title": "The proton gradient", "quote": "As electrons move through the electron transport chain, protons are pumped into the intermembrane space.", "location": "Slide 12", "topic": "Electron transport chain"},
    {"id": "e3", "source_id": "s3", "title": "A useful distinction", "quote": "Glycolysis does not require oxygen; oxygen becomes important when the electron carriers are re-oxidized later.", "location": "14:32", "topic": "Glycolysis"},
]

class ChatInput(BaseModel):
    message: str
    history: List[dict] = []

class QuizSubmit(BaseModel):
    question_id: str
    answer: str

class AuthSession(BaseModel):
    session_id: str

def now():
    return datetime.now(timezone.utc).isoformat()

async def llm_answer(prompt: str, session: str) -> str:
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        raise HTTPException(500, "LLM key is not configured")
    chat = LlmChat(api_key=key, session_id=session, system_message="You are Lumina, a careful course tutor. Only make source-backed claims from the provided excerpts. If the excerpts do not answer the question, say MATERIAL NOT COVERED. Keep answers concise and cite [source, location].")
    chat = chat.with_model("gemini", "gemini-3.1-pro-preview")
    chunks = []
    async for event in chat.stream_message(UserMessage(text=prompt)):
        if isinstance(event, TextDelta):
            chunks.append(event.content)
        elif isinstance(event, StreamDone):
            break
    return "".join(chunks).strip()

def init_storage(force=False):
    global STORAGE_KEY
    if STORAGE_KEY and not force:
        return STORAGE_KEY
    response = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": os.environ["EMERGENT_LLM_KEY"]}, timeout=30)
    response.raise_for_status()
    STORAGE_KEY = response.json()["storage_key"]
    return STORAGE_KEY

def put_object(path, data, content_type):
    key = init_storage()
    response = requests.put(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key, "Content-Type": content_type}, data=data, timeout=120)
    if response.status_code == 404:
        key = init_storage(force=True)
        response = requests.put(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key, "Content-Type": content_type}, data=data, timeout=120)
    response.raise_for_status()
    return response.json()

@api.get("/")
async def root():
    return {"message": "Lumina Academic API"}

async def current_user(request: Request):
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
async def create_session(input: AuthSession, response: Response):
    try:
        result = requests.get("https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data", headers={"X-Session-ID": input.session_id}, timeout=30)
        result.raise_for_status()
        identity = result.json()
    except requests.RequestException:
        raise HTTPException(401, "Google session could not be verified")
    user = await db.users.find_one({"email": identity["email"]}, {"_id": 0})
    timestamp = now()
    if user:
        user_id = user["user_id"]
        await db.users.update_one({"user_id": user_id}, {"$set": {"name": identity["name"], "picture": identity.get("picture", ""), "last_sign_in_at": timestamp}})
    else:
        user_id = "user_" + uuid.uuid4().hex[:12]
        user = {"user_id": user_id, "google_id": identity["id"], "email": identity["email"], "name": identity["name"], "picture": identity.get("picture", ""), "created_at": timestamp, "first_sign_in_at": timestamp, "last_sign_in_at": timestamp, "learner_profile": {"level": "new", "preferred_language": "English"}, "course_progress": {}, "mastery": {}, "chat_history": []}
        await db.users.insert_one(user)
    expires = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    expires_at = (datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=7)).isoformat()
    await db.user_sessions.insert_one({"user_id": user_id, "session_token": identity["session_token"], "created_at": expires, "expires_at": expires_at})
    response.set_cookie("session_token", identity["session_token"], max_age=604800, httponly=True, secure=True, samesite="none", path="/")
    saved = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    return saved

@api.get("/auth/me")
async def me(request: Request):
    return await current_user(request)

@api.post("/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token:
        await db.user_sessions.delete_many({"session_token": token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}

@api.get("/dashboard")
async def dashboard():
    return {"topics": TOPICS, "sources": SOURCES, "excerpts": EXCERPTS, "streak": 6, "minutes": 184, "questions": 28, "confidence": 72}

@api.get("/sources")
async def sources():
    return SOURCES

@api.post("/sources/upload")
async def upload_source(file: UploadFile = File(...)):
    allowed = {".pdf", ".pptx", ".mp4", ".mov", ".mpg", ".avi", ".ppt"}
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(400, "Upload a PDF, PowerPoint, or video file")
    source_id = "s" + uuid.uuid4().hex[:8]
    file_bytes = await file.read()
    storage_path = f"{APP_NAME}/uploads/course/{source_id}{suffix}"
    try:
        storage_result = put_object(storage_path, file_bytes, file.content_type or "application/octet-stream")
    except requests.RequestException as exc:
        logging.exception("Object storage upload failed")
        raise HTTPException(502, f"Source storage is unavailable: {exc}")
    source = {"id": source_id, "name": file.filename, "type": suffix.replace(".", "").upper(), "meta": "Queued · multimodal extraction", "status": "Processing", "accent": "terracotta", "topics": 0}
    await db.sources.insert_one({**source, "storage_path": storage_result["path"], "size": storage_result["size"], "is_deleted": False, "created_at": now()})
    return source

@api.post("/chat")
async def chat(input: ChatInput):
    context = "\n".join(f"- {x['quote']} [{x['title']}, {x['location']}]" for x in EXCERPTS)
    prompt = f"Course excerpts:\n{context}\n\nStudent question: {input.message}\nAnswer with a clear explanation, then a short 'Evidence' line with the exact citations. Separate any unsupported claim as outside course material."
    answer = await llm_answer(prompt, "lumina-chat-" + uuid.uuid4().hex)
    record = {"id": uuid.uuid4().hex, "role": "assistant", "message": answer, "question": input.message, "created_at": now()}
    await db.chat_messages.insert_one(record)
    return {"answer": answer, "citations": EXCERPTS, "grounded": "MATERIAL NOT COVERED" not in answer}

@api.get("/quiz")
async def quiz():
    return {"title": "Cellular respiration · Checkpoint", "scope": "Week 04 sources", "question_number": 3, "total": 8, "question": {"id": "q3", "prompt": "Why does the electron transport chain create a gradient?", "type": "MCQ", "topic": "Electron transport chain", "difficulty": "Stretch", "options": ["To split glucose", "To store energy as a proton difference", "To make oxygen", "To produce carbon dioxide"]}, "prior_feedback": "Your last answer showed a strong grasp of glycolysis."}

@api.post("/quiz/submit")
async def submit_quiz(input: QuizSubmit):
    correct = input.answer == "To store energy as a proton difference"
    topic = next(x for x in TOPICS if x["name"] == "Electron transport chain")
    updated = {**topic, "mastery": min(100, topic["mastery"] + (8 if correct else -4))}
    feedback = "Exactly — the gradient stores potential energy that ATP synthase can use." if correct else "Not quite. The gradient stores energy as a proton difference; ATP synthase uses it to make ATP."
    return {"correct": correct, "feedback": feedback, "citation": {"title": "Mitochondria & ATP · Lecture 04", "location": "Slide 12"}, "topic": updated, "report": {"score": 76, "weakest": "Electron transport chain", "misconception": "Confusing electron flow with ATP formation"}}

@api.get("/evaluation")
async def evaluation():
    return {"faithfulness": 94, "relevancy": 89, "precision": 87, "recall": 82, "repetition": 4, "profiles": [{"name": "New learner", "gain": "+18 pts", "sessions": 4}, {"name": "Visual learner", "gain": "+24 pts", "sessions": 6}, {"name": "Exam crammer", "gain": "+11 pts", "sessions": 3}]}

@api.get("/study-plan")
async def study_plan():
    return [{"day": "Today", "title": "Repair the gradient", "detail": "12 min · concept map + 3 questions", "topic": "Electron transport chain", "color": "terracotta"}, {"day": "Tomorrow", "title": "Connect the cycles", "detail": "18 min · retrieval practice", "topic": "Krebs cycle", "color": "forest"}, {"day": "Friday", "title": "Full checkpoint", "detail": "25 min · mixed mock exam", "topic": "All Week 04", "color": "ochre"}]

app.include_router(api)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origin_regex=r".*", allow_methods=["*"], allow_headers=["*"])
logging.basicConfig(level=logging.INFO)

@app.on_event("shutdown")
async def shutdown():
    client.close()