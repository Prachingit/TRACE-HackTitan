# TRACE — Round 2 Submission

- **Public URL**: https://trace-app-7qmx.onrender.com
- **Repository URL**: https://github.com/Prachingit/TRACE-HackTitan
- **Tag**: `submission-round2`

## Feature Status

### Working
- Real authentication (`httpOnly` JWT cookies, argon2/bcrypt password hashing, rate limiting, invite links, workspace multi-tenancy).
- Public cloud deployment live on Render free tier (`https://trace-app-7qmx.onrender.com`) backed by hosted PostgreSQL (Neon).
- Multi-format source ingestion (PDF text, DOCX, CSV, Markdown, Chat JSON, Manual entries, public GitHub commits/PRs/issues) with upload security checks (MIME/magic sniffing, size limits, duplicate SHA-256 detection, path traversal protection).
- Deterministic reconstruction engine (`ingest-normalise -> extract -> correlate -> timeline`) with optional schema-validated LLM extraction + exact-excerpt verification and automatic rule fallback.
- Evidence Ledger with highlighted chunk excerpts in the source drawer and automated citation validation.
- Deterministic Contradiction Radar (5 conflict/gap rules with manual resolution + required note).
- Exit Interview gap identification, question generation, and human-authored `interview_answer` evidence creation.
- Human Review Workbench (accept/edit/reject/flag, contradiction-aware accept guard, append-only `ReviewEvent` history).
- Central Clearance Engine (`app/engine/clearance.py`) enforcing `team_lead`, `incoming`, and `departing` visibility across all endpoints, PDF exports, and admin `?view_as` read-only preview.
- 10-section Handover Center with explainable Readiness Score, ranked dependency-aware Continuation Plan, section-level approval, sharing/revocation, Incoming Member Portal, persistent `OnboardingProgress`, acknowledgement, and `fpdf2` PDF export.
- Secondary clearance-filtered "Ask project knowledge" assistant.
- Idempotent **synthetic** **Atlas Workspace** demo with 3 role-based one-click demo accounts (Alex = team lead, Priya = incoming, Rahul = departing).

### Not Built (Planned for Round 3)
- **Readiness Verification** (automated pre-handover sign-off gates)
- **Living Handover** (continuous post-handover sync)
- **Continuity Graph** (cross-project interactive knowledge graph)
- OAuth integrations (Google Drive, Slack, Jira, Notion, private GitHub) and OCR for scanned PDFs.

## Changes from Original Round 1 Plan
- Implemented full real authentication, workspace multi-tenancy, and RBAC earlier than originally scheduled so clearance filtering is backed by real database roles and tenant isolation.
- Switched production persistence from SQLite (named in the original Round 1 plan) to hosted PostgreSQL (Neon) via `DATABASE_URL` + `psycopg`, so users, projects, claims, and reviews persist across free-tier container restarts; server-side `fpdf2` PDF generation remains zero-external-binary inside the single container.

## 5-Minute Judge Demo Script (Synthetic Demo Workspace)
The **Try the demo** panel on the login page opens a **synthetic** Atlas Workspace (`is_synthetic: true`) with three one-click demo logins:
- **Alex** (`alex.lead@demo.example.com`) — **Team Lead** (full workspace, restricted records, Review Workbench, Handover Center)
- **Priya** (`priya.incoming@demo.example.com`) — **Incoming** (Incoming Member Portal, ranked continuation plan, approved handover; zero restricted data)
- **Rahul** (`rahul.departing@demo.example.com`) — **Departing** (own contributions and exit interview questions only)

Suggested walkthrough:
1. Open https://trace-app-7qmx.onrender.com and click **Alex (Team Lead)** on the **Try the demo** card (`SYNTHETIC`).
2. Inspect **Continuity Overview** and **Projects -> Atlas Core Platform -> Evidence Ledger**; click a claim to view the exact highlighted source chunk excerpt.
3. Open **Contradiction Radar** and **Exit Interview** to see planted conflicts and targeted gap questions.
4. Open **Handover Center** to inspect the 10-section draft, explainable Readiness Score, and toggle **Preview as: Incoming** to see restricted/unapproved content disappear immediately.
5. Sign out and click **Priya (Incoming)** to view the **Incoming Member Portal**, **"Where should I start?"** ranked plan, persistent checklist, and **Export PDF** (or **Rahul (Departing)** to see the departing member view).

## Known Limitations & Honest Risks
- **Render free-tier cold starts**: Hosted on Render's free tier, so the first request after inactivity can take about 50 seconds while the instance wakes up.
- **Hosted PostgreSQL (Neon)**: Database is a hosted PostgreSQL (Neon), so users, projects, claims, and reviews persist across restarts (differs from the Round 1 plan, which named SQLite).
- **Ephemeral upload disk**: Original uploaded files are stored on the free instance's ephemeral disk, so they can disappear after a restart. Extracted chunks, claims, and evidence stay in the database, and the app shows a clear message when an original file is gone.
- **Round 3 scope**: The three Round 3 items (**Readiness Verification**, **Living Handover**, **Continuity Graph**) are not implemented.
- Scanned PDFs without extractable text fail cleanly with an explicit message (no OCR).
- Unauthenticated public GitHub imports are subject to GitHub API rate limits unless `GITHUB_TOKEN` is set.

---

## One-Page Project Summary (For Submission PDF)

**Problem**: When engineers or project leads leave a team, critical context—why decisions were made, what is actually finished vs. only started, hidden blockers, and undocumented ownership—is scattered across commits, task trackers, docs, and chat logs. Incoming members spend weeks piecing together half-truths.

**Solution**: **TRACE** (*Team Records, Activity & Context Engine*) reconstructs project reality from raw artifacts, verifies every claim against exact source excerpts, surfaces contradictions and knowledge gaps for human resolution, and delivers a **permission-aware, human-approved handover** with a ranked continuation plan.

**Architecture**: A FastAPI + SQLAlchemy backend (`ingest -> extract -> correlate -> timeline -> contradiction radar -> exit interview -> review workbench -> handover center`) paired with a React + Vite frontend served from a single origin. A central `clearance.py` module enforces `public`, `team`, and `restricted` access across every query, API response, PDF export, and secondary Q&A query.

**What Works Now**: End-to-end multi-format ingestion, deterministic + citation-verified extraction, Evidence Ledger with chunk highlighting, 5-rule Contradiction Radar, Exit Interview evidence capture, append-only Review Workbench, 10-section Handover Center with explainable Readiness Score, dependency-ordered Continuation Plan, Incoming Member Portal with acknowledgement and PDF export, and a 3-role synthetic demo workspace backed by 84 passing automated tests.

**What Is Next (Round 3)**: Readiness Verification gates, Living Handover continuous sync, Continuity Graph visualization, and OAuth connectors (Slack, Jira, Google Drive, Notion, private GitHub).
