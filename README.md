# TRACE — Team Records, Activity & Context Engine

> **Tagline**: *"When People Leave, Knowledge Shouldn't."*  
> **Built by**: Team HackTitan for Round 2 of the CodePuneThinkers Hackathon  
> **Phase**: Phase 1 — Foundation & Data Architecture  

TRACE reconstructs project history from scattered sources (GitHub commits, markdown docs, meeting notes, task CSVs, engineering chat exports), builds an evidence-backed knowledge base, flags contradictions and gaps, and produces an approved handover for an incoming team member.

The **Handover Center** is the hero feature of the platform.

---

## 1. Repository Layout

```text
TRACE/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, CORS, router registration, auto-seed
│   │   ├── config.py          # Settings from env (PORT, DATABASE_URL, origins)
│   │   ├── db.py              # SQLite engine, session factory, init_db()
│   │   ├── models.py          # Complete SQLAlchemy 2.x models (all 15 tables)
│   │   ├── schemas.py         # Pydantic v2 schemas mirroring the API contract
│   │   ├── deps.py            # Current-user / role dependency (X-Demo-User)
│   │   ├── routers/
│   │   │   ├── health.py      # GET /api/health
│   │   │   ├── demo.py        # POST /api/demo/load, GET /api/me
│   │   │   └── projects.py    # GET /api/projects, /members, /sources, /summary
│   │   └── services/
│   │       └── seed.py        # Loads Atlas Workspace into SQLite (idempotent)
│   ├── data/
│   │   └── atlas/             # Synthetic "Atlas Workspace" dataset
│   │       ├── commits.json   # 30 commits with feature streams
│   │       ├── tasks.csv      # 18 tasks with assignees, status, modules
│   │       ├── meeting_notes.md # 3 sprint & handover kickoff meetings
│   │       ├── chat.json      # 45 engineering messages across 3 channels
│   │       ├── docs/          # architecture.md and api_notes.md
│   │       └── restricted_internal.md # Confidential operational notes (restricted)
│   ├── tests/
│   │   ├── test_api.py        # Health, auth, demo load, summary, clearance
│   │   └── test_seed.py       # Seeder idempotency & source clearance levels
│   └── requirements.txt       # Pinned dependencies
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   └── client.js      # Fetch wrapper with VITE_API_URL & X-Demo-User
│   │   ├── components/
│   │   │   ├── Sidebar.jsx    # Navigation with Handover Center featured as HERO
│   │   │   ├── Layout.jsx     # Header with tagline & Demo Role Switcher
│   │   │   ├── StatusBadge.jsx # Clearance & status visual badges
│   │   │   ├── StatCard.jsx   # Metrics card component
│   │   │   ├── EmptyState.jsx # Honest "Coming in a later phase" placeholder
│   │   │   └── Loading.jsx    # Minimal spinner
│   │   ├── pages/
│   │   │   ├── Overview.jsx   # Hero overview, seed button, stats, sources table
│   │   │   └── PlaceholderPages.jsx # Honest placeholders for roadmap tabs
│   │   ├── styles/
│   │   │   └── tokens.css     # Restrained enterprise palette & CSS variables
│   │   ├── App.jsx            # React Router tree
│   │   └── main.jsx           # Entrypoint
│   ├── package.json
│   ├── vite.config.js
│   └── index.html
├── docs/
│   └── API_CONTRACT.md        # Comprehensive contract with mock JSON examples
├── .env.example
├── .gitignore
└── README.md
```

---

## 2. Complete Database Schema (Phase 1 Defined)

All tables and foreign key relationships are defined upfront to prevent migrations in future phases:
- `User`: Identity, name, email, nullable password hash, default role.
- `Workspace`: Workspace container (`Atlas Workspace`).
- `Membership`: User role within workspace (`admin`, `team_member`, `incoming`, `departing`).
- `Project`: Project metadata, category, team size, `is_synthetic` boolean flag.
- `Source`: Ingested artifacts with clearance levels (`public`, `team`, `restricted`) and status.
- `Chunk`: Atomic source segments (lines/commits/paragraphs) for Phase 3 ingestion.
- `Claim`: Evidence-backed factual assertions with verification status.
- `ClaimEvidence`: Citations linking claims to chunks and sources.
- `Contradiction`: Flagged rule violations, severity, and suggested resolutions.
- `ContradictionClaim`: Many-to-many relationship linking contradictions to claims.
- `InterviewQuestion`: Targeted exit questions for outgoing team members.
- `ReviewEvent`: Human review decisions (`approve`, `edit`, `reject`, `flag`).
- `Handover`: Core handover record connecting departing and incoming engineers.
- `HandoverSection`: Structured modular sections within a handover.
- `OnboardingProgress`: Checklist tracking incoming engineer's comprehension.

---

## 3. Authentication in Phase 1

Phase 1 intentionally avoids full JWT / OAuth login infrastructure. Instead, authentication uses a clean demo-identity dependency:
- The frontend sends the user ID or role via the `X-Demo-User` header.
- The backend dependency `get_current_user` in [`backend/app/deps.py`](file:///C:/Users/singh/TRACE/backend/app/deps.py) resolves the User and Membership record.
- If the header is missing or the user does not exist, the API returns `HTTP 401 Unauthorized`.
- In the frontend header, the **Demo Role Switcher** allows toggling in real-time between:
  - **Admin (Meera Shah)**: Full clearance — views all sources including restricted records.
  - **Incoming (Priya Nair)**: Restricted internal records are hidden by the backend.
  - **Departing (Rahul Verma)**: Restricted internal records are hidden by the backend.

---

## 4. Quickstart Guide

### Prerequisites
- Python 3.11+
- Node.js 18+ & npm

### Backend Setup & Execution
From the project root:
```bash
cd backend

# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the FastAPI development server
uvicorn app.main:app --reload --port 8000
```
- Interactive API Docs (Swagger): [http://localhost:8000/docs](http://localhost:8000/docs)
- Health check: [http://localhost:8000/api/health](http://localhost:8000/api/health)

> **Deploy Readiness**: If started against an empty database, the backend automatically seeds the Atlas Workspace on startup so ephemeral containers never come up blank.

### Frontend Setup & Execution
In a separate terminal:
```bash
cd frontend

# 1. Install dependencies
npm install

# 2. Start the Vite development server
npm run dev
```
- Frontend application runs at: [http://localhost:5173](http://localhost:5173)

---

## 5. Running Backend Tests

Run all unit and integration tests using `pytest`:
```bash
cd backend
python -m pytest -v
```

The test suite validates:
1. `GET /api/health` returns status `ok` and database connectivity.
2. `POST /api/demo/load` idempotency (running multiple times creates zero duplicate rows).
3. `GET /api/me` resolves the active demo user and workspace.
4. Missing or unknown `X-Demo-User` returns `HTTP 401`.
5. `GET /api/projects/{id}/sources` returns all 7 sources for `admin`, but excludes restricted sources for `incoming` and `departing` roles.
6. `GET /api/projects/{id}/summary` matches live database counts with claims and contradictions starting at 0.
7. Seeder source registration and metadata checks.

---

## 6. Synthetic Atlas Dataset & Planted Cases

Located in `backend/data/atlas/`, the synthetic Atlas Workspace features:
- **Team**: Rahul Verma (departing backend), Priya Nair (incoming backend), Ankit Rao (frontend/DevOps), Meera Shah (admin/lead).
- **Planted Test Cases**:
  1. *Conflicting Ownership*: `tasks.csv` assigns payments to Rahul; `meeting_notes.md` assigns it to Ankit.
  2. *Complete Without Evidence*: Task "Payment gateway integration" is marked Done in `tasks.csv`, but no commit touches payment code.
  3. *Undocumented Decision*: `chat.json` shows switch from in-memory cache to Redis; `architecture.md` still says in-memory LRU.
  4. *Unresolved Dependency & Orphan*: "Payment testing" depends on gateway integration; "Database backup" task has no assignee.
  5. *Stale Update*: Notification retry task in `tasks.csv` has no activity for 5+ weeks.
  6. *Restricted Record*: `restricted_internal.md` carries `clearance_level = "restricted"` and is hidden from non-admin roles.
  7. *Auth Module*: Commit "Added JWT authentication middleware", meeting notes note auth testing is pending, task remains in-progress.
