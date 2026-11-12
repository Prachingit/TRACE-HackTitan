# TRACE

**Team Records, Activity & Context Engine** (Team HackTitan). *When people leave, knowledge shouldn't.*

TRACE ingests scattered project data and, in later phases, builds an evidence-linked handover. **Phase 2 (this state)** is live multi-source ingestion: real accounts, workspaces, invites, tenant isolation, and three ways to add data (file upload, GitHub import, manual entry). There is no LLM, claim extraction, contradiction detection or handover logic yet.

## Run locally

Requires Python 3.11+ and Node 20+.

```powershell
# Backend (terminal 1)
cd backend
pip install -r requirements.txt
copy ..\.env.example .env        # optional; dev defaults work without it
python -m uvicorn app.main:app --reload --port 8000

# Frontend (terminal 2) - Vite proxies /api to :8000
cd frontend
npm.cmd install
npm.cmd run dev                  # http://localhost:5173
```

Migrations run automatically at backend startup (`alembic upgrade head`). To create one after a model change: `cd backend; python -m alembic revision --autogenerate -m "message"`. Never delete the database to apply schema changes.

### Single origin (production style)
```powershell
cd frontend; npm.cmd run build; Copy-Item dist ..\backend\static -Recurse
cd ..\backend; python -m uvicorn app.main:app --port 8000   # app and API at http://localhost:8000
```

### Docker
```bash
docker build -t trace .
docker run -p 8000:8000 -e SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))") -v trace-data:/data trace
```
`ENV=production` refuses to start without a strong `SECRET_KEY`. The `/data` volume holds the SQLite file and uploads; without a volume they are lost on redeploy.

## Test
```powershell
cd backend; python -m pytest -v
```

## Configuration (see `.env.example`)
`SECRET_KEY` (required in production), `DATABASE_URL`, `DATA_DIR`, `GITHUB_TOKEN` (optional), `SMTP_*` (optional; password reset stays disabled without them), `ALLOWED_ORIGINS` (dev only).

## Notes
- API reference: [docs/API_CONTRACT.md](docs/API_CONTRACT.md)
- Atlas sample data (`backend/data/atlas/`) is fictional and loads only when an admin clicks "Load sample project data" on a project.
- Scanned PDFs fail with a clear message; OCR is not supported.
- SQLite and local file storage suit a single instance. Use a persistent disk when hosting.
- Background parsing runs in-process; sources left `parsing` after a crash are reset to `queued` on startup.
