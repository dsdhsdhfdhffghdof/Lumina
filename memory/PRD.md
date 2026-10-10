# Lumina — Personalized Tutoring & Adaptive Learning

## Original problem statement
Build an AI study companion that unifies lecture videos, textbooks, and slides into a source-cited knowledge base, and uses it to run adaptive assessments and personalized tutoring. The requirements include a multimodal knowledge base, source grounding, adaptive assessment, learner model, and system evaluation.

## This iteration focus (upload-only grounded tutoring)
A full student-isolated, upload-grounded tutor:

1. Google OAuth sign-in via Emergent-managed social login.
2. First-login onboarding: user must successfully upload & process at least one text document before entering the workspace.
3. Managed private object storage per user; all downloads require the session.
4. PDF / DOCX / TXT / MD extraction with page-level metadata.
5. Keyword retrieval + Gemini 3.1 Pro answer generation **strictly from the user's own pages**.
6. Exact fallback phrase when evidence is missing: `I couldn't find this information in your uploaded materials. Please upload the relevant page or document.`
7. Citations rendered as `[filename, p.N]` with the exact excerpt shown.
8. Ownership check on every student-scoped endpoint (list, retry, delete, download, pages, chat, history, dashboard).
9. Cross-user access blocked (verified by smoke test).
10. Mobile-first drawer navigation; logout clears session and cookie.

## Architecture
- Backend: FastAPI + Motor (MongoDB)
- Frontend: React 19 + lucide-react + sonner (warm-paper "Lumina Academic Workspace" visual system)
- Storage: Emergent managed object storage (private, server-mediated)
- LLM: Gemini 3.1 Pro via Emergent LLM key with strict grounded system prompt + citation guardrail
- Extraction: pypdf, python-docx (no OCR — scanned/image PDFs flagged as unsupported)

## MongoDB collections
- `users` — Google identity, `onboarded` flag
- `user_sessions` — session_token, expiry
- `materials` — per-user documents (status: processing | ready | failed, page_count, storage_path, is_deleted)
- `material_pages` — extracted text + tokens for keyword retrieval, with page numbers
- `chat_messages` — grounded answers + citations

## Key endpoints (all `/api/*`)
- `POST /auth/session`, `GET /auth/me`, `POST /auth/logout`
- `GET /onboarding/status`
- `POST /materials/upload`, `GET /materials`, `DELETE /materials/{id}`, `POST /materials/{id}/retry`
- `GET /materials/{id}/download` (streamed, auth required)
- `GET /materials/{id}/pages/{n}` (owner-only)
- `POST /tutor/chat`, `GET /tutor/history`
- `GET /dashboard`

## Implemented (Feb 2026)
- Google-only sign-in with onboarding gate
- Private upload + text extraction (PDF/DOCX/TXT/MD, 25 MB cap)
- Keyword retrieval + grounded Gemini tutor with exact fallback
- Material manager (list, retry failed, delete)
- Full cross-user isolation (verified by `backend/tests/smoke_tutor.py`)
- Warm-paper responsive UI with mobile drawer nav
- Storage retry logic for transient 5xx

## Backlog
- P1: Adaptive quiz generation grounded in user's own pages (currently a placeholder view)
- P1: Mastery tracking via Bayesian/IRT updated from quiz + chat correctness
- P2: RAGAS-style evaluation on team-built test set
- P2: Flashcards, study schedule with forgetting curves
- P2: Audio tutor via TTS
- P2: Mixed-language / Hindi explanation mode
- P2: Optional pgvector/embedding retrieval if accuracy on large corpora regresses

## Verified by
- `/app/backend/tests/smoke_tutor.py` — end-to-end: upload, isolation, grounded chat, fallback, download, delete
- UI screenshots: login, onboarding gate, workspace, grounded tutor answer with evidence card, fallback card, mobile drawer
