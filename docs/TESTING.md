# TRACE Testing & Verification

## Running All Tests

```bash
cd backend
python -m pytest -q
```

Frontend production bundle check:
```bash
cd frontend
npm ci
npm run build
```

Alembic schema & PostgreSQL DDL check:
```bash
cd backend
python -m alembic upgrade head
python -m alembic check
```

---

## Test Suites & Real Counts

Collected from `backend/tests/` (`python -m pytest --collect-only -q`): **91 tests total** across 13 suites.

| Suite | Count | What It Covers |
| --- | --- | --- |
| `tests/test_auth.py` | 11 | Signup, login, logout, `httpOnly` cookie auth, password hashing, validation, reset flow |
| `tests/test_ingestion.py` | 25 | PDF, DOCX, CSV, Markdown, Chat JSON, manual entry, GitHub import, MIME sniffing, size/count caps, duplicate hash `409`, path traversal protection |
| `tests/test_isolation.py` | 3 | Cross-workspace tenant isolation (`404` on foreign workspaces/projects/sources) |
| `tests/test_phase3_engine.py` | 7 | Normalisation, deterministic extraction, optional LLM schema + excerpt verification + fallback, correlation, timeline |
| `tests/test_phase4_ledger.py` | 3 | Evidence Ledger querying, source chunk drawer offsets, citation validation (`invalid_citation_count == 0`) |
| `tests/test_phase5_contradictions.py` | 10 | Contradiction Radar rules, non-Atlas conflicts, manual resolution + required note, clearance filtering |
| `tests/test_phase6_review.py` | 19 | Exit interview gap generation, idempotent regeneration, `interview_answer` evidence, Review Workbench accept/edit/reject/flag, accept guards, append-only `ReviewEvent` |
| `tests/test_phase7_handover.py` | 3 | Clearance Engine (`team_lead`, `incoming`, `departing`, `?view_as`), 10+ section handover workflow, sharing/revocation, Incoming Portal, acknowledgement, `fpdf2` PDF export |
| `tests/test_phase8_e2e_security.py` | 5 | Non-Atlas E2E journey, role matrix, security headers, demo workspace isolation, `postgres://` URL normalization, ephemeral disk missing-file `409`, `alembic check` + PostgreSQL offline DDL (`sql=True`) |
| `tests/test_round3_living_handover.py` | 1 | Source re-upload versioning, identical `409`, chunk diffing, stale claims, review queue priority, handover `v1` immutability, `v2` diff + clearance + isolation |
| `tests/test_round3_readiness_verification.py` | 1 | Approved-only question generation, idempotency, answer-key hiding from `incoming`, MCQ + short-answer partial credit, per-area scores, baseline/retake delta, weak areas -> Exit Interview |
| `tests/test_round3_continuity_graph.py` | 2 | Evidence-backed edges, SPOF/cycle/unowned detection, `"what breaks if X leaves"`, all 7 secret-rejection patterns, append-only `CustodyEvent`, handover Continuity section |
| `tests/test_round3_hardening_e2e.py` | 1 | Complete Round 3 E2E journey, `/api/health` DB+storage probe, bad-input `400`s, and optimistic concurrency `409` (`expected_version`) |

---

## Latest Observed Results

- **Backend (`python -m pytest -q` at `71036dd`):** **91 passed, 10 warnings in 57.93s**.
- **Frontend (`npm.cmd run build` at `c6dd312`):** **built in 1.91s** (`vite v6.4.6`, 2116 modules transformed).
- **Alembic:** `alembic check` passes (`No new upgrade operations detected`) and offline PostgreSQL DDL (`command.upgrade(cfg, "head", sql=True)`) verifies all 7 migrations cleanly.

---

## Manual Checks & Limitations

- **Live Render + Neon Deploy**: Deployed at `https://trace-app-7qmx.onrender.com` with Neon Postgres.
- **Accuracy Scope**: Extraction, contradiction, readiness, and continuity accuracy have been verified on the synthetic Atlas dataset and custom non-Atlas test fixtures created in `tests/`, not on external production repositories or live multi-user load tests.
- **Local Postgres & Headless Browser**: Docker Desktop's Linux engine and local `psql` were unavailable in the dev environment, so Postgres DDL was verified via Alembic's PostgreSQL offline SQL generator (`sql=True`) locally and executed against Neon on Render; 360px layout and live UI click-through are covered by CSS/Vite build checks and manual verification checklist rather than an automated Playwright suite.
