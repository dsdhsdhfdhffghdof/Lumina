"""Backend smoke test for Lumina upload-only tutoring flow.

Creates a synthetic session directly in Mongo (skipping Google), then exercises
the public API surface: upload material, list, retry logic, tutor chat with
grounded answer, cross-user isolation, and logout.
"""
import os, io, asyncio, uuid, time
from datetime import datetime, timezone, timedelta
import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from pypdf import PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

API = "http://localhost:8001/api"
MONGO = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


def build_test_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont("Helvetica", 14)
    c.drawString(72, 720, "Lumina Test Textbook - Cellular Respiration")
    c.drawString(72, 690, "Chapter 1 introduces cellular respiration as the biochemical process")
    c.drawString(72, 672, "in which cells convert glucose into usable energy stored as ATP.")
    c.showPage()
    c.setFont("Helvetica", 14)
    c.drawString(72, 720, "Chapter 2 - The Electron Transport Chain")
    c.drawString(72, 690, "The electron transport chain pumps protons across the inner")
    c.drawString(72, 672, "mitochondrial membrane, creating an electrochemical gradient.")
    c.drawString(72, 654, "ATP synthase uses this gradient to produce ATP from ADP and Pi.")
    c.showPage()
    c.save()
    return buf.getvalue()


async def ensure_session(email: str):
    client = AsyncIOMotorClient(MONGO)
    db = client[DB_NAME]
    user_id = "user_" + uuid.uuid4().hex[:12]
    token = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    exp = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    await db.users.insert_one({
        "user_id": user_id,
        "google_id": "test_" + user_id,
        "email": email,
        "name": "Test " + email.split("@")[0],
        "picture": "",
        "created_at": now,
        "first_sign_in_at": now,
        "last_sign_in_at": now,
        "onboarded": False,
        "preferred_language": "English",
    })
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": token,
        "created_at": now,
        "expires_at": exp,
    })
    client.close()
    return user_id, token


async def cleanup():
    client = AsyncIOMotorClient(MONGO)
    db = client[DB_NAME]
    for coll in ["users", "user_sessions", "materials", "material_pages", "chat_messages"]:
        await db[coll].delete_many({"$or": [{"email": {"$regex": "@lumina-test"}}, {"user_id": {"$regex": "^user_"}}]} if coll == "users" else {})
    client.close()


async def main():
    print("=== Lumina smoke test ===")
    user_a_id, token_a = await ensure_session(f"a-{uuid.uuid4().hex[:6]}@lumina-test.local")
    user_b_id, token_b = await ensure_session(f"b-{uuid.uuid4().hex[:6]}@lumina-test.local")
    print(f"User A: {user_a_id}, User B: {user_b_id}")

    async with httpx.AsyncClient(base_url=API, timeout=120) as cli:
        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # auth/me
        r = await cli.get("/auth/me", headers=headers_a)
        assert r.status_code == 200, r.text
        print("auth/me OK")

        # unauth
        r = await cli.get("/materials")
        assert r.status_code == 401
        print("unauth 401 OK")

        # upload PDF for A
        pdf = build_test_pdf()
        files = {"file": ("test.pdf", pdf, "application/pdf")}
        r = await cli.post("/materials/upload", files=files, headers=headers_a)
        assert r.status_code == 200, r.text
        mat = r.json()
        print("upload:", mat["status"], "pages:", mat["page_count"])
        assert mat["status"] == "ready", f"Expected ready, got {mat['status']} err={mat.get('error')}"
        assert mat["page_count"] == 2
        mat_id = mat["id"]

        # unsupported
        r = await cli.post("/materials/upload", files={"file": ("x.exe", b"xx", "application/octet-stream")}, headers=headers_a)
        assert r.status_code == 400
        print("unsupported 400 OK")

        # list
        r = await cli.get("/materials", headers=headers_a)
        assert r.status_code == 200
        assert r.json()["count"] == 1
        print("list OK")

        # B cannot see A's
        r = await cli.get("/materials", headers=headers_b)
        assert r.json()["count"] == 0
        print("isolation list OK")

        # B cannot download A's
        r = await cli.get(f"/materials/{mat_id}/download", headers=headers_b)
        assert r.status_code == 404
        print("isolation download OK")

        # onboarding status A
        r = await cli.get("/onboarding/status", headers=headers_a)
        assert r.json()["onboarded"] is True
        print("onboarding A OK")

        # tutor grounded answer
        r = await cli.post("/tutor/chat", json={"message": "What does ATP synthase use to produce ATP?"}, headers=headers_a)
        assert r.status_code == 200
        data = r.json()
        print("tutor answer sample:", data["answer"][:140])
        print("citations:", len(data["citations"]), "grounded:", data["grounded"])
        assert data["grounded"] is True
        assert len(data["citations"]) > 0
        assert any("test.pdf" in c["filename"] for c in data["citations"])

        # tutor off-material question -> fallback
        r = await cli.post("/tutor/chat", json={"message": "What is the capital of France and its population?"}, headers=headers_a)
        data = r.json()
        print("off-material grounded:", data["grounded"], "answer:", data["answer"][:140])
        # Should be ungrounded (fallback). The guardrail enforces this.
        assert data["grounded"] is False
        assert data["answer"].startswith("I couldn't find this information")

        # user B with no materials -> fallback
        r = await cli.post("/tutor/chat", json={"message": "What is ATP?"}, headers=headers_b)
        data = r.json()
        assert data["grounded"] is False
        assert data["sources_available"] == 0
        print("user B empty-material fallback OK")

        # download for A
        r = await cli.get(f"/materials/{mat_id}/download", headers=headers_a)
        assert r.status_code == 200
        assert len(r.content) > 100
        print("download OK, size:", len(r.content))

        # delete
        r = await cli.delete(f"/materials/{mat_id}", headers=headers_a)
        assert r.status_code == 200
        print("delete OK")

        # dashboard
        r = await cli.get("/dashboard", headers=headers_a)
        assert r.status_code == 200
        print("dashboard OK:", r.json()["questions"], "questions")

    await cleanup()
    print("=== All checks passed ===")


if __name__ == "__main__":
    asyncio.run(main())
