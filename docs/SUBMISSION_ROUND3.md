# TRACE — Round 3 Submission Summary

- **Public URL**: https://trace-app-7qmx.onrender.com
- **Repository URL**: https://github.com/Prachingit/TRACE-HackTitan

---

## Round 3 Improvements Completed After Round 2

### 1. Living Handover (Commit `9a31f0c`)
- **What it does**: Tracks source revisions (`SourceVersion` + `SourceVersionChunk`), deterministically detects `added` / `removed` / `modified` chunks (`SourceChange`) on re-upload, GitHub re-sync, or manual edit (returning `409` on identical content), flags affected claims as **Stale** (prioritised first in the Review Workbench with old vs new source excerpts), keeps approved handovers immutable (`409` on edit/re-approve), surfaces an **Out of date** banner, and creates `v2+` handovers with itemized diffs and cause attribution (`review_action` or `source_change`).
- **Where to find it**:
  - **Changes** page (`/projects/:id/changes` or `/changes` in the sidebar)
  - **Evidence Ledger** (`/evidence`) and **Review Workbench** (`/review`) — Stale badges & old-vs-new excerpt diff
  - **Handover Center** (`/handovers`) — Out-of-date banner, **Create v2**, version selector, and **Compare versions** diff table
  - **Incoming Member Portal** (`/portal`) — Banner when a newer approved version is available

### 2. Readiness Verification (Commit `ac1c807`)
- **What it does**: Generates evidence-based scenario questions (MCQ + short-answer) strictly from approved, incoming-visible claims; withholds answer keys from the incoming role across all endpoints; scores MCQ deterministically and short-answer via key-term coverage heuristics (`needs_reviewer_check` flag on partial coverage); aggregates weighted per-area scores (`AreaScore`); tracks baseline vs re-assessment delta; and lets admins send weak-area missed claims into the Exit Interview workflow.
- **Where to find it**:
  - **Handover Center** (`/handovers`) — **Readiness verification** panel (Generate assessment, per-area baseline/latest/delta table, who needs help, **Send weak areas to Exit Interview**)
  - **Incoming Member Portal** (`/portal`) — **Check my understanding** (one question per screen, progress bar, source-cited explanations, per-area readiness table, retake)

### 3. Continuity Graph & Custody Checklist (Commit `ede3b7e`)
- **What it does**: Builds an evidence-backed graph (`GraphNode`, `GraphEdge`) of people, modules, tasks, documents, and services; flags single points of failure, unowned/undocumented modules, and circular dependencies; computes ranked **"What breaks if X leaves?"** impact; adds Section **11. Continuity and custody** to handovers; and manages a secret-free **Custody Checklist** (`CustodyItem` + append-only `CustodyEvent`) with backend rejection (`400`) of private keys, token prefixes, `password=`/`secret=` assignments, credentialed URLs, and high-entropy strings.
- **Where to find it**:
  - **Continuity** page (`/projects/:id/continuity` or `/continuity` in the sidebar) — Interactive SVG graph + 360px-friendly table fallback, node-type filters, click-to-open Evidence Drawer, risks, departure impact selector, and Custody Checklist
  - **Handover Center** (`/handovers`) — Section **11. Continuity and custody** & ranked plan items for unconfirmed custody / unowned modules

### 4. Stability, Usability & End-to-End Hardening (Commits `d45472c`, `c6dd312`, `71036dd`)
- Optimistic concurrency (`expected_version` → `409`) on claim reviews to prevent silent overwrites.
- Startup Alembic retry loop on Postgres cold starts with full stdout traceback logging.
- Cold-start slow-request banner (`"Waking up the server, this can take up to a minute..."` after 3.5s), 65s request timeout, `401` session-expiry redirect (`/login?expired=1`), and friendly `403` role messages.
- 5-step **Getting started** progress panel on **Continuity Overview** (`/`) backed by real project/handover state, keyboard `:focus-visible` outlines, tooltips on Stale badges, and 360px layout polish.
- Full end-to-end Round 3 regression suite (`91 passed` across all backend suites).
