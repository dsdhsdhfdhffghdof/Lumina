# Lumina — Personalized Tutoring & Adaptive Learning

Lumina is a source-grounded AI study companion. Students sign in with Google, upload their own
lecture notes / textbooks / slides, and ask questions. Every answer is produced **only** from the
student's own uploads and cites the exact page it came from. Scanned documents and photos are
supported through self-hosted OCR.

> _"The best learning is a conversation with what you already know."_

---

## Features

- **Google OAuth** sign-in (Emergent-managed social login) — no passwords stored.
- **First-login onboarding** gate: a student can only enter the workspace after at least one
  document has been successfully processed.
- **Private per-user material library** backed by managed object storage. Every download, list,
  and delete is authorized against the signed-in user.
- **Self-hosted OCR** (Tesseract + Poppler) for scanned PDFs and image uploads (PNG, JPG, JPEG,
  WEBP, TIFF, BMP). Text-based PDFs, DOCX, TXT, and MD go through a fast native extractor.
- **Grounded tutor** (Gemini 3.1 Pro via Emergent LLM key): answers are produced only from the
  student's own pages. Every claim has an inline `[filename, p.N]` citation, and when evidence
  is missing the tutor replies with the exact phrase:
  > _"I couldn't find this information in your uploaded materials. Please upload the relevant page or document."_
- **Smart retrieval** — filename-aware, page-aware, and intent-aware (summaries, question
  generation, step-by-step math, specific lookups).
- **Practice question generation** — multiple-choice, short answer, and numerical problems with
  cited answers and explanations.
- **Math-aware tutor** — reconstructs equations from noisy OCR and shows step-by-step solutions.
- **Mobile-first UI** with a warm-paper academic workspace aesthetic.

---

## Architecture

```
┌──────────────┐          ┌───────────────┐          ┌────────────────────────┐
│  React 19    │  HTTPS   │  FastAPI      │          │  MongoDB (Motor)       │
│  Tailwind    ├──────────▶  (uvicorn)    ├──────────▶  users, user_sessions, │
│  lucide +    │  cookies │  /api/*       │          │  materials,            │
│  sonner      │          │               │          │  material_pages,       │
└──────┬───────┘          │               │          │  chat_messages         │
       │                  │               │          └────────────────────────┘
       │                  │  pypdf        │          ┌────────────────────────┐
       │                  │  python-docx  ├──────────▶  Managed object        │
       │                  │  tesseract    │          │  storage               │
       │                  │  pdf2image    │          └────────────────────────┘
       │                  │               │          ┌────────────────────────┐
       │                  │  LlmChat      ├──────────▶  Gemini 3.1 Pro        │
       │                  │               │          │  (Emergent LLM key)    │
       └──────────────────┴───────────────┘          └────────────────────────┘
```

- **Backend**: FastAPI, Motor (async MongoDB), pypdf, python-docx, pytesseract, pdf2image,
  emergentintegrations LLM chat.
- **Frontend**: React 19 + CRACO, Tailwind, lucide-react, sonner.
- **AI**: Gemini 3.1 Pro via the Emergent LLM key.
- **Storage**: Managed object storage (private, server-mediated).
- **Database**: MongoDB (user-scoped collections with ownership checks).

---

## Prerequisites

- Node 18+ and Yarn
- Python 3.11+
- MongoDB (local or remote)
- System packages for OCR:
  - `tesseract-ocr`
  - `poppler-utils`

Install the OS packages (Debian / Ubuntu):

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr poppler-utils
```

Optional language packs (e.g. Hindi, French):

```bash
sudo apt-get install -y tesseract-ocr-hin tesseract-ocr-fra
```

---

## Environment variables

### `/app/backend/.env`
| Variable            | Required | Description                                                                 |
|---------------------|----------|-----------------------------------------------------------------------------|
| `MONGO_URL`         | yes      | MongoDB connection string.                                                  |
| `DB_NAME`           | yes      | MongoDB database name.                                                      |
| `EMERGENT_LLM_KEY`  | yes      | Universal key for Gemini + managed object storage.                          |
| `CORS_ORIGINS`      | no       | Comma-separated extra origins (defaults to `*` regex).                      |
| `OCR_LANG`          | no       | Tesseract language code(s). Default `eng`. Example: `eng+hin`.              |
| `OCR_PDF_DPI`       | no       | DPI used when rendering PDFs for OCR fallback. Default `200`.               |
| `OCR_MAX_PAGES`     | no       | Maximum pages OCR'd per PDF. Default `40`.                                  |

### `/app/frontend/.env`
| Variable               | Required | Description                                               |
|------------------------|----------|-----------------------------------------------------------|
| `REACT_APP_BACKEND_URL`| yes      | Base URL of the FastAPI backend (routed under `/api/*`).  |

> Never commit real values. The provided `.env` files already contain the correct
> development configuration for this environment.

---

## Running locally

Services are supervised in this environment and start automatically. Manual commands:

```bash
# Backend  (hot reload enabled)
cd /app/backend
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001 --reload

# Frontend (hot reload enabled)
cd /app/frontend
yarn install
yarn start
```

Open the frontend URL (e.g. `http://localhost:3000`) and sign in with Google.

### Supervisor control

```bash
sudo supervisorctl status
sudo supervisorctl restart backend
sudo supervisorctl restart frontend
```

---

## Using the app

1. **Sign in with Google** on the login page.
2. **Upload at least one document** on the onboarding screen. Supported:
   - Text PDFs, DOCX, TXT, MD → native extraction.
   - Scanned PDFs, PNG, JPG, JPEG, WEBP, TIFF, BMP → Tesseract OCR.
   - Hard limit: 25 MB per file.
3. Click **Start Learning**.
4. In the **Ask Lumina** tab, ask questions, request summaries, or generate practice questions:
   - "Summarize the main concepts in my uploads"
   - "Generate 5 practice questions from unit 1"
   - "Explain page 3 of my notes"
   - "Solve 2x² − 4x − 6 = 0"
5. Every answer shows the inline `[filename, p.N]` citation plus an **Evidence** card with the
   excerpt. If no evidence is found, the tutor returns the exact not-found phrase.
6. Manage files in **My materials** — retry failed OCR, delete, re-upload.

---

## API reference

All endpoints are under `/api` and require a valid session cookie or `Authorization: Bearer <token>`
header, except where noted.

### Auth
| Method | Path                | Auth | Description                                          |
|--------|---------------------|------|------------------------------------------------------|
| POST   | `/auth/session`     | no   | Exchange `session_id` from Google callback hash.     |
| GET    | `/auth/me`          | yes  | Current user profile.                                |
| POST   | `/auth/logout`      | yes  | Deletes the session and clears the cookie.           |

### Onboarding / Dashboard
| Method | Path                   | Description                                        |
|--------|------------------------|----------------------------------------------------|
| GET    | `/onboarding/status`   | `{ onboarded: bool, ready_materials: int }`.       |
| GET    | `/dashboard`           | User-scoped counts and material list.              |

### Materials
| Method | Path                                    | Description                              |
|--------|-----------------------------------------|------------------------------------------|
| POST   | `/materials/upload` (multipart `file`)  | Upload + extract/OCR a document.         |
| GET    | `/materials`                            | List this user's materials.              |
| DELETE | `/materials/{id}`                       | Soft-delete + remove pages + storage.    |
| POST   | `/materials/{id}/retry`                 | Re-process a failed material.            |
| GET    | `/materials/{id}/download`              | Streamed inline download (owner only).   |
| GET    | `/materials/{id}/pages/{n}`             | Extracted page text (owner only).        |

### Tutor
| Method | Path                   | Body                        | Description                                        |
|--------|------------------------|-----------------------------|----------------------------------------------------|
| POST   | `/tutor/chat`          | `{ "message": "..." }`      | Grounded, cited answer. Returns the exact fallback when no evidence. |
| GET    | `/tutor/history`       | `?limit=50`                 | Chronological chat history (user-scoped).          |

Example:

```bash
curl -X POST "$API/tutor/chat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Summarize unit 1"}'
```

---

## Testing

```bash
cd /app/backend
python tests/smoke_tutor.py                       # end-to-end smoke
pytest tests/test_lumina_backend.py -q            # auth + materials + tutor
pytest tests/test_ocr_backend.py -q               # OCR + scanned PDFs
pytest tests/test_intent_retrieval.py -q          # summaries / questions / math
```

The smoke test mints a synthetic session in Mongo (`users` + `user_sessions`), uploads a text
PDF, exercises grounded chat (both answered and fallback), cross-user isolation, download, and
delete.

---

## Project structure

```
/app
├── backend
│   ├── server.py              # FastAPI app: auth, materials, extraction, OCR, retrieval, tutor
│   ├── requirements.txt
│   └── tests/                 # smoke + pytest regression suites
├── frontend
│   └── src
│       ├── App.js             # auth gate + routing
│       ├── App.css            # warm-paper design system
│       └── components
│           ├── Login.jsx
│           ├── Onboarding.jsx
│           └── Workspace.jsx  # overview, materials, tutor, placeholders
├── memory
│   ├── PRD.md
│   └── test_credentials.md
└── test_reports/              # testing-agent iteration reports
```

---

## Troubleshooting

- **"OCR failed" after uploading a scan** — check that both `tesseract-ocr` and `poppler-utils`
  are installed. Verify with `tesseract --version` and `pdftoppm -v`.
- **Tutor always returns the fallback** — confirm at least one material has `status: ready` via
  `GET /api/materials`. The guardrail enforces evidence-only answers; off-topic questions
  deliberately return the fallback.
- **Session expires too quickly** — sessions last 7 days by default; stored in `user_sessions`
  with `expires_at` as ISO 8601 UTC.
- **Large PDF rejected** — the 25 MB cap is in `MAX_UPLOAD_BYTES` in `server.py`.
- **OCR too slow / too fast** — tune `OCR_PDF_DPI` (lower = faster, less accurate) and
  `OCR_MAX_PAGES`.

---

## Security notes

- Every student-scoped route constrains queries by the authenticated `user_id`.
- Cross-user access to materials, pages, downloads, chat history, and the dashboard is denied
  (verified by the regression suite).
- Object storage paths are prefixed with `lumina-academic/users/<user_id>/materials/...` and
  only reachable via the signed-in session.
- No LLM traffic leaves the student's uploaded excerpts — the tutor never issues web searches
  or receives outside knowledge in its prompts.
- Session cookies are `HttpOnly`, `Secure`, `SameSite=None`, scoped to `/`.

---

## License

Internal demo. Replace with your organization's license before public release.
