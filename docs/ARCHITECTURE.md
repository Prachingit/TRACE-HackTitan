# TRACE Architecture

## High-Level Components

TRACE is a single-origin web application:
- **Backend (`backend/app/`)**: FastAPI + SQLAlchemy 2.0 + Alembic migrations, supporting SQLite (local/tests) and PostgreSQL (`psycopg[binary]`, Neon in production).
- **Frontend (`frontend/src/`)**: React 18 + Vite 6 SPA served statically by FastAPI in production (`/assets` + SPA fallback with `/api/*` 404 guard).

---

## Core Data Flow

1. **Ingestion & Versioning (`routers/sources.py`, `services/background.py`, `engine/living.py`)**
   - Uploaded files (PDF, DOCX, CSV, MD, TXT, JSON), public GitHub imports, and manual entries are stored as `Source` + `Chunk` rows, with an immutable `SourceVersion` + `SourceVersionChunk` snapshot.
   - Re-uploading an updated file with the same filename creates a new `SourceVersion`, compares chunks deterministically (`match_chunks`), records `SourceChange` rows (`added` / `removed` / `modified`), and flags affected claims as `is_stale` (or `possibly_affected`).
2. **Reconstruction (`engine/pipeline.py`, `normalise.py`, `extract.py`, `correlate.py`, `timeline.py`)**
   - Normalises chunks, extracts candidate claims (deterministic rules by default; optional schema-validated LLM with exact-excerpt verification and automatic fallback), correlates modules/aliases, detects documentation gaps, and preserves human-reviewed claims across re-runs.
3. **Validation, Contradictions & Exit Interview (`engine/validation.py`, `engine/rules/`, `engine/interview/`)**
   - Verifies every citation excerpt appears in its cited `Chunk`.
   - Runs Contradiction Radar rules and generates targeted Exit Interview questions; human answers append `ClaimEvidence(evidence_type="interview_answer")` without modifying original source evidence.
4. **Human Review Workbench (`engine/review.py`, `routers/review.py`)**
   - Prioritises stale claims first, enforces `expected_version` optimistic concurrency (`409` on stale writes), enforces evidence/contradiction accept guards, clears stale flags on human decision, and appends immutable `ReviewEvent` rows.
5. **Continuity Graph & Custody Checklist (`engine/continuity.py`, `routers/continuity.py`)**
   - Rebuilds evidence-backed `GraphNode` (`person`, `module`, `task`, `document`, `service`) and `GraphEdge` (`owns`, `contributed_to`, `depends_on`, `blocks`, `documents`, `decided`) rows.
   - Detects single points of failure, unowned/undocumented modules, circular dependencies, and `"what breaks if X leaves"` impact ranking.
   - Manages secret-free `CustodyItem`s (`validate_no_secrets` blocks private keys, token prefixes, `password=`/`secret=`, credentialed connection strings, and high-entropy strings) with append-only `CustodyEvent` history.
6. **Handover Center & Readiness Verification (`engine/handover.py`, `engine/plan.py`, `engine/readiness.py`)**
   - Generates an 11-section handover (including `11. Continuity and custody`), explainable Readiness Score, and dependency-ranked continuation plan.
   - Enforces immutability on approved handovers (`409` on edit/re-approve), supports `v2+` lineage + version diffs (`diff_handovers`), and generates/scores evidence-based Readiness Verification assessments (`Assessment`, `AssessmentQuestion`, `AssessmentAttempt`, `AssessmentAnswer`, `AreaScore`).

---

## Security & Clearance Design

- **Authentication**: JWT stored in `httpOnly` cookies (`core/security.py`), argon2 password hashing, rate limiting via `slowapi`, and workspace-scoped invite tokens.
- **Workspace Isolation**: Every project/source/claim/handover/assessment/custody endpoint verifies `Membership` for the signed-in user's `workspace_id` (`404` for foreign workspaces).
- **Central Clearance Engine (`engine/clearance.py`)**:
  - `team_lead` (`admin`): full workspace visibility (including `restricted`, unreviewed, rejected, and `?view_as=incoming|departing` read-only preview).
  - `team_member`: `public` and `team` items only.
  - `incoming`: ONLY human-approved (`approved`/`edited`), non-stale, `public`/`team` claims, approved sections of actively shared handovers, `confirmed`/`transferred` non-restricted custody items, and assessment questions **without** answer keys.
  - `departing`: own contributions and assigned interview questions at `public`/`team` level only; no handover reports or assessments.
- **HTTP Hardening (`main.py`)**: Security headers (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`) and generic `500` handler (no stack traces leaked to clients).
