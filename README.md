# TRACE (Team Records, Activity & Context Engine)

TRACE ingests scattered project activity (git history, PR reviews, task boards, meeting notes, team chat) and compiles an evidence-backed handover package for developers stepping into a project.

Every claim cites verifiable evidence, indicates a confidence status (`verified`, `inferred`, `conflicting`, or `missing`), and enforces role-based access clearance before sharing.

---

## 1. Project Architecture & Repo Structure

```text
TRACE/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py          # FastAPI application, CORS, and role endpoints
│   │   ├── config.py        # Settings loaded from environment with defaults
│   │   ├── db.py            # SQLite engine, session factory, and init_db()
│   │   ├── models.py        # SQLAlchemy 2.0 models & CHECK constraints
│   │   └── schemas.py       # Pydantic v2 schemas mirroring the contract
│   ├── scripts/
│   │   └── seed.py          # Idempotent DB seeder (--reset flag supported)
│   ├── tests/
│   │   ├── test_seed.py     # Seeder idempotency, sources, and access tests
│   │   └── test_api.py      # Health, roles, clearance filter, & mock validation
│   ├── requirements.txt     # Pinned Python dependencies
│   └── .env.example         # Example environment configuration
├── contract/
│   ├── README.md            # Human-readable contract & planned endpoints
│   └── examples/            # Ready-to-use mock JSON for Phase 2 frontend
│       ├── handover.json    # Complete demo handover with ~10 claims
│       ├── role_views.json  # Role-specific clearance views (with hidden_count)
│       ├── plan.json        # 5 ranked next steps with reasons & claim IDs
│       └── gap_questions.json # 3 generated questions for missing claims
├── data/
│   └── demo/                # Synthetic "CampusConnect" demo dataset
│       ├── git_log.json     # ~25 git commits with feature branches
│       ├── pull_requests.json # 4 PRs with review comments
│       ├── tasks.csv        # 15 tasks with assignees, status, & PR links
│       ├── chat.json        # 40 engineering chat messages
│       ├── README_project.md # Project documentation (with planted contradiction)
│       ├── PLANTED_CASES.md # Documentation of planted test cases (C1-C3, G1, D1-D2, O1, R1)
│       ├── notes/           # Standup and sprint meeting notes
│       └── restricted/      # Confidential vendor budget notes (restricted access)
├── docs/                    # Architectural notes & guides
├── frontend/
│   └── .gitkeep             # Reserved for Phase 2 React client
├── .gitignore
└── README.md
```

---

## 2. Quickstart & Setup

### Prerequisites
- Python 3.11+
- Virtual environment (recommended)

### Installation
From the repository root:
```bash
# 1. Navigate to backend directory
cd backend

# 2. (Optional) Create and activate virtual environment
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
# source venv/bin/activate

# 3. Install pinned dependencies
pip install -r requirements.txt
```

---

## 3. Database Seeding

Run the idempotent database seed script to initialize SQLite tables and register all demo sources:

```bash
# From backend directory:
python scripts/seed.py

# To reset and recreate tables from scratch:
python scripts/seed.py --reset
```

The seeder initializes:
- **Project**: `CampusConnect` (`proj-campusconnect`)
- **Roles**: `team_lead` (clearance: `restricted`), `incoming_developer` (clearance: `internal`), `external_reviewer` (clearance: `public`)
- **Sources**: 9 demo source artifacts tagged with their appropriate access label.

---

## 4. Running the API Server

Start the FastAPI development server:
```bash
# From backend directory:
uvicorn app.main:app --reload --port 8000
```

The interactive API documentation is accessible at:
- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- Contract Spec: [http://localhost:8000/api/contract](http://localhost:8000/api/contract)
- Health Check: [http://localhost:8000/health](http://localhost:8000/health)

### Testing Role Clearance Filtering
- `GET /api/demo/sources?role=external_reviewer` (returns public sources only)
- `GET /api/demo/sources?role=incoming_developer` (returns public and internal sources)
- `GET /api/demo/sources?role=team_lead` (returns public, internal, and restricted sources)
- `GET /api/demo/sources?role=invalid` (returns HTTP 400 Bad Request)

---

## 5. Running the Tests

Execute the full test suite with `pytest`:
```bash
# From backend directory:
pytest -v
```

The test suite validates:
1. **Seed Idempotency & Sources**: Re-seeding doesn't duplicate rows; all demo files are registered; restricted files carry `restricted` label.
2. **API Filtering & Clearance**: Clearance hierarchy (`public < internal < restricted`) properly gates visibility; unknown roles return 400.
3. **Contract Schema Validation**: Every mock JSON file in `contract/examples/` (`handover.json`, `role_views.json`, `plan.json`, `gap_questions.json`) validates against Pydantic models in `backend/app/schemas.py`.

---

## 6. Access Control Design Rule
> **Evidence Inheritance Rule**: A claim's `access_label` must equal the **strictest** label among its cited evidence sources (`public < internal < restricted`). If any evidence is from a `restricted` source, the claim is `restricted`. If no evidence is `restricted` but at least one is `internal`, the claim is `internal`.
