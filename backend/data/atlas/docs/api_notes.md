# Atlas API Documentation Notes (Synthetic)

---

## Endpoint Specifications

### Health & Monitoring
- `GET /api/health`
  - Returns service status and database operational readiness.
  - Response: `{"status": "ok", "version": "1.0.0", "db": "ok"}`

### Project & Resource Summary
- `GET /api/projects/{id}/summary`
  - Returns real-time aggregate counts calculated strictly from database rows.
  - Fields: `source_count`, `sources_by_type`, `member_count`, `claim_count`, `open_contradiction_count`.

### Authentication Headers
- Phase 1 Demo Header: `X-Demo-User: <user_id_or_role>`
- In later phases, this will be replaced seamlessly with standard `Authorization: Bearer <JWT>` without modifying business router logic.
