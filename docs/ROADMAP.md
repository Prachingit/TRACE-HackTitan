# TRACE Roadmap

## Completed (Phases 1–8 + Round 3)

- **Phases 1–8**: Auth & multi-tenant workspaces, multi-format ingestion, reconstruction engine, Evidence Ledger & citation validation, Contradiction Radar, Exit Interview & Review Workbench, Clearance Engine, 10-section Handover Center, Incoming Member Portal, PDF export, and synthetic Atlas demo.
- **Round 3 Improvements (A, B, C + Hardening)**:
  - **Living Handover**: Source versioning, chunk-level change detection, stale-claim flagging, immutable approved handovers, `v2+` lineage, and version diffs.
  - **Readiness Verification**: Approved-only scenario questions, deterministic MCQ + heuristic short-answer scoring, weighted per-area readiness, baseline/retake delta, and weak-area Exit Interview follow-ups.
  - **Continuity Graph & Custody Checklist**: Evidence-backed dependency graph, SPOFs, cycle detection, departure impact ranking, and secret-free custody checklist with append-only audit history.

---

## Future Plan (Not Yet Implemented)

1. **Private GitHub via OAuth**: OAuth app flow to import private repositories, PR reviews, and branch protection metadata.
2. **Scheduled & Webhook Source Sync for Living Handover**: Automatic periodic or webhook-driven re-sync of GitHub repos and external docs to trigger change detection without manual re-upload.
3. **Google Drive, Slack, Jira & Notion Connectors**: Direct read-only OAuth integrations to ingest docs, threads, tickets, and wiki pages with source-level clearance mapping.
4. **OCR for Scanned PDFs**: Text extraction fallback for image-based PDFs.
5. **Persistent Object Storage for Uploaded Files**: S3/R2-compatible storage so raw uploaded files survive ephemeral container restarts.
6. **Email Notifications & Invites**: Automated transactional emails (beyond optional SMTP password reset) for handover sharing, stale-claim alerts, and invite delivery.
7. **LLM-Assisted Scoring for Short-Answer Readiness**: Optional rubric-guided LLM grading alongside deterministic key-term coverage (currently only a deterministic heuristic is active).
8. **SSO & Audit Export**: SAML/OIDC enterprise SSO and signed CSV/JSON compliance exports of `ReviewEvent`, `HandoverEvent`, and `CustodyEvent` logs.
9. **Multi-Project Analytics**: Cross-project continuity health dashboards, recurring bottleneck trends, and workspace-wide bus-factor heatmaps.
