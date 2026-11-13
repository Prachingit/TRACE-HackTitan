# TRACE — Round 2 Submission

- **Public URL**: `TODO — deploy via render.yaml or Dockerfile and insert live URL here`
- **Repository URL**: `https://github.com/Prachingit/TRACE-HackTitan`
- **Tag**: `submission-round2`

## Feature Status

### Working
- Real authentication (`httpOnly` JWT cookies, bcrypt password hashing, rate limiting, invite links, workspace multi-tenancy).
- Multi-format source ingestion (PDF text, DOCX, CSV, Markdown, Chat JSON, Manual entries, public GitHub commits/PRs/issues) with upload security checks (MIME/magic sniffing, size limits, duplicate SHA-256 detection, path traversal protection).
- Deterministic reconstruction engine (`ingest-normalise -> extract -> correlate -> timeline`) with optional schema-validated LLM extraction + exact-excerpt verification and automatic rule fallback.
- Evidence Ledger with highlighted chunk excerpts in the source drawer and automated citation validation.
- Deterministic Contradiction Radar (5 conflict/gap rules with manual resolution + required note).
- Exit Interview gap identification, question generation, and human-authored `interview_answer` evidence creation.
- Human Review Workbench (accept/edit/reject/flag, contradiction-aware accept guard, append-only `ReviewEvent` history).
- Central Clearance Engine (`app/engine/clearance.py`) enforcing `team_lead`, `incoming`, and `departing` visibility across all endpoints, PDF exports, and admin `?view_as` read-only preview.
- 10-section Handover Center with explainable Readiness Score, ranked dependency-aware Continuation Plan, section-level approval, sharing/revocation, Incoming Member Portal, persistent `OnboardingProgress`, acknowledgement, and `fpdf2` PDF export.
- Secondary clearance-filtered "Ask project knowledge" assistant.
- Idempotent synthetic **Atlas Workspace** demo with 3 role-based one-click demo accounts.

### Partially Working
- Public cloud deployment: `Dockerfile` and `render.yaml` (with persistent `/data` disk) are ready, but live cloud deployment requires the owner's Render/Railway/Fly account and `SECRET_KEY` / `ALLOWED_ORIGINS` dashboard setup.

### Not Built (Planned for Round 3)
- **Readiness Verification** (automated pre-handover sign-off gates)
- **Living Handover** (continuous post-handover sync)
- **Continuity Graph** (cross-project interactive knowledge graph)
- OAuth integrations (Google Drive, Slack, Jira, Notion, private GitHub) and OCR for scanned PDFs.

## Changes from Original Round 1 Plan
- Implemented full real authentication, workspace multi-tenancy, and RBAC earlier than originally scheduled so clearance filtering is backed by real database roles and tenant isolation.
- Chose SQLite + persistent volume (`DATA_DIR` / `DATABASE_URL`) and server-side `fpdf2` PDF generation for zero-external-binary single-container deployment, with Postgres supported via `DATABASE_URL`.

## 5-Minute Judge Demo Script
1. Open the app and click **Enter as admin** (`alex.lead@demo.example.com`) on the **Try the demo** card (labelled `SYNTHETIC`).
2. Inspect **Continuity Overview** and **Projects -> Atlas Core Platform -> Evidence Ledger**; click a claim to view the exact highlighted source chunk excerpt.
3. Open **Contradiction Radar** and **Exit Interview** to see planted conflicts and targeted gap questions.
4. Open **Handover Center** to inspect the 10-section draft, explainable Readiness Score, and toggle **Preview as: Incoming** to see restricted/unapproved content disappear immediately.
5. Sign out and click **Enter as incoming** (`priya.incoming@demo.example.com`) to view the **Incoming Member Portal**, **"Where should I start?"** ranked plan, persistent checklist, and **Export PDF**.

## Known Limitations & Honest Risks
- Scanned PDFs without extractable text fail cleanly with an explicit message (no OCR).
- Unauthenticated public GitHub imports are subject to GitHub API rate limits unless `GITHUB_TOKEN` is set.
- Demo workspace uses a fixed synthetic seed; resetting demo data requires clearing the demo rows or database volume.

---

## One-Page Project Summary (For Submission PDF)

**Problem**: When engineers or project leads leave a team, critical context—why decisions were made, what is actually finished vs. only started, hidden blockers, and undocumented ownership—is scattered across commits, task trackers, docs, and chat logs. Incoming members spend weeks piecing together half-truths.

**Solution**: **TRACE** (*Team Records, Activity & Context Engine*) reconstructs project reality from raw artifacts, verifies every claim against exact source excerpts, surfaces contradictions and knowledge gaps for human resolution, and delivers a **permission-aware, human-approved handover** with a ranked continuation plan.

**Architecture**: A FastAPI + SQLAlchemy backend (`ingest -> extract -> correlate -> timeline -> contradiction radar -> exit interview -> review workbench -> handover center`) paired with a React + Vite frontend served from a single origin. A central `clearance.py` module enforces `public`, `team`, and `restricted` access across every query, API response, PDF export, and secondary Q&A query.

**What Works Now**: End-to-end multi-format ingestion, deterministic + citation-verified extraction, Evidence Ledger with chunk highlighting, 5-rule Contradiction Radar, Exit Interview evidence capture, append-only Review Workbench, 10-section Handover Center with explainable Readiness Score, dependency-ordered Continuation Plan, Incoming Member Portal with acknowledgement and PDF export, and a 3-role synthetic demo workspace backed by 84 passing automated tests.

**What Is Next (Round 3)**: Readiness Verification gates, Living Handover continuous sync, Continuity Graph visualization, and OAuth connectors (Slack, Jira, Google Drive, Notion, private GitHub).
