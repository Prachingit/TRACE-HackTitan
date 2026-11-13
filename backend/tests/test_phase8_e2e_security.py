"""Phase 8a tests: Full non-Atlas E2E flow, role-based access matrix, error handling, and security headers."""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.engine.handover import SECTION_DEFS
from app.main import app
from app.models import Membership


def _signup_login(client: TestClient, name: str, email: str, password: str = "SecurePass2026!") -> dict:
    r = client.post(
        "/api/auth/signup",
        json={"name": name, "email": email, "password": password, "confirm_password": password},
    )
    assert r.status_code in (200, 201), r.text
    r2 = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r2.status_code == 200, r2.text
    return r2.json()


def test_full_non_atlas_end_to_end_journey(client: TestClient):
    tag = uuid.uuid4().hex[:6]
    admin = _signup_login(client, f"Clara Lead {tag}", f"clara_{tag}@acme.example.com")

    ws = client.post("/api/workspaces", json={"name": f"Acme Payments {tag}"}).json()
    ws_id = ws["id"]

    proj = client.post(
        "/api/projects",
        json={"workspace_id": ws_id, "name": f"Ledger Rewrite {tag}", "description": "Non-Atlas project"},
    ).json()
    pid = proj["id"]

    # 1. Upload CSV, Markdown, Chat JSON, Manual entry, and Mocked GitHub
    csv_bytes = (
        "task_id,title,status,owner,module,notes\n"
        "T-10,Implement ledger worker,Done,Samira,worker,Needs integration test\n"
        "T-11,Migrate webhook retries,In Progress,Samira,webhooks,Pending backoff tuning\n"
    ).encode("utf-8")
    r_csv = client.post(
        f"/api/projects/{pid}/sources/upload",
        files={"file": ("sprint_tasks.csv", csv_bytes, "text/csv")},
        data={"clearance_level": "team"},
    )
    assert r_csv.status_code == 201, r_csv.text

    md_bytes = (
        "# Architecture Notes\n"
        "We decided to use Postgres advisory locks for idempotency in worker/locks.py.\n"
        "Task Implement ledger worker is blocked by missing staging Redis credentials.\n"
        "Samira will handle webhooks.\n"
    ).encode("utf-8")
    r_md = client.post(
        f"/api/projects/{pid}/sources/upload",
        files={"file": ("arch.md", md_bytes, "text/markdown")},
        data={"clearance_level": "team"},
    )
    assert r_md.status_code == 201, r_md.text

    chat_json = json.dumps(
        [
            {"author": "Samira", "timestamp": "2026-10-12T10:00:00Z", "text": "Agreed to cap retry attempts at 5 in webhooks."},
            {"author": "Clara", "timestamp": "2026-10-12T10:05:00Z", "text": "Migrate webhook retries depends on Implement ledger worker."},
        ]
    ).encode("utf-8")
    r_chat = client.post(
        f"/api/projects/{pid}/sources/upload",
        files={"file": ("slack_webhooks.json", chat_json, "application/json")},
        data={"clearance_level": "team"},
    )
    assert r_chat.status_code == 201, r_chat.text

    r_man = client.post(
        f"/api/projects/{pid}/sources/manual",
        json={
            "title": "Restricted Compensation Note",
            "content": "PRIVATE_COMPENSATION_991: Retention bonus for Q4.",
            "clearance_level": "restricted",
        },
    )
    assert r_man.status_code == 201, r_man.text

    with (
        patch("app.routers.sources.fetch_commits", return_value=[{"sha": "abc1234", "author": "Samira", "message": "worker/locks.py: add lock", "date": "2026-10-14T12:00:00Z", "files": ["worker/locks.py"]}]),
        patch("app.routers.sources.fetch_pull_requests", return_value=[]),
        patch("app.routers.sources.fetch_issues", return_value=[]),
    ):
        r_gh = client.post(
            f"/api/projects/{pid}/sources/github",
            json={"repo_url": "https://github.com/acme/ledger-rewrite", "clearance_level": "team"},
        )
        assert r_gh.status_code == 201, r_gh.text

    # 2. Analyze -> Claims, Timeline, Modules, 0 invalid citations
    r_an = client.post(f"/api/projects/{pid}/analyze")
    assert r_an.status_code in (200, 201, 202), r_an.text

    r_claims = client.get(f"/api/projects/{pid}/claims")
    assert r_claims.status_code == 200
    claims = r_claims.json()
    assert len(claims) >= 3

    r_tl = client.get(f"/api/projects/{pid}/timeline")
    assert r_tl.status_code == 200
    assert len(r_tl.json()) >= 1

    r_mod = client.get(f"/api/projects/{pid}/modules")
    assert r_mod.status_code == 200
    assert len(r_mod.json()) >= 1

    r_val = client.get(f"/api/projects/{pid}/ledger/validation")
    assert r_val.status_code == 200
    assert r_val.json()["invalid_citation_count"] == 0

    # 3. Evidence drawer detail shows highlighted excerpt
    first_claim_id = claims[0]["id"]
    r_det = client.get(f"/api/claims/{first_claim_id}")
    assert r_det.status_code == 200
    assert len(r_det.json()["evidence"]) >= 1

    # 4. Contradiction radar
    r_ctr = client.get(f"/api/projects/{pid}/contradictions")
    assert r_ctr.status_code == 200
    ctrs = r_ctr.json()
    for ctr in ctrs:
        if ctr["status"] == "open":
            r_res = client.post(f"/api/contradictions/{ctr['id']}/resolve", json={"note": "Verified in E2E review"})
            assert r_res.status_code == 200

    # 5. Exit Interview: generate & answer -> becomes evidence
    r_iq = client.post(f"/api/projects/{pid}/interview/generate")
    assert r_iq.status_code in (200, 201)
    q_list = client.get(f"/api/projects/{pid}/interview").json()["questions"]
    if q_list:
        r_ans = client.post(
            f"/api/interview/questions/{q_list[0]['id']}/answer",
            json={"answer": "Confirmed: advisory locks stay enabled in production."},
        )
        assert r_ans.status_code == 200

    # 6. Review Workbench: approve non-restricted team claims & verify history
    for c in claims:
        if c["clearance_level"] != "restricted":
            r_rev = client.post(
                f"/api/claims/{c['id']}/review",
                json={"action": "accept", "note": "Verified for handover"},
            )
            assert r_rev.status_code == 200, r_rev.text

    r_hist = client.get(f"/api/claims/{first_claim_id}/history")
    assert r_hist.status_code == 200
    assert len(r_hist.json()) >= 1

    # 7. Create invite & incoming user accepts invite
    r_inv = client.post(f"/api/workspaces/{ws_id}/invites", json={"role": "incoming"})
    assert r_inv.status_code == 201, r_inv.text
    inv_token = r_inv.json()["token"]

    c_inc = TestClient(app, raise_server_exceptions=False)
    inc_user = _signup_login(c_inc, f"Leo Incoming {tag}", f"leo_{tag}@acme.example.com")
    r_join = c_inc.post("/api/workspaces/join", json={"token": inv_token})
    assert r_join.status_code in (200, 201), r_join.text

    # 8. Generate Handover, approve all 10 sections, approve handover, share with Leo
    r_h = client.post(
        f"/api/projects/{pid}/handovers",
        json={"target_user_id": inc_user["id"], "period_label": "Q4 2026"},
    )
    assert r_h.status_code == 201, r_h.text
    hid = r_h.json()["id"]

    for sec_key, _ in SECTION_DEFS:
        assert client.patch(f"/api/handovers/{hid}/sections/{sec_key}", json={"review_status": "approved"}).status_code == 200

    assert client.post(f"/api/handovers/{hid}/approve").status_code == 200
    assert client.post(f"/api/handovers/{hid}/share", json={"target_user_id": inc_user["id"]}).status_code == 200

    # 9. Incoming user views handover, marks progress, acknowledges, and sees no restricted text
    r_inc_h = c_inc.get(f"/api/handovers/{hid}")
    assert r_inc_h.status_code == 200
    assert "PRIVATE_COMPENSATION_991" not in json.dumps(r_inc_h.json())

    assert c_inc.post(f"/api/handovers/{hid}/onboarding", json={"item_key": "step-1", "completed": True}).status_code == 200
    assert c_inc.post(f"/api/handovers/{hid}/acknowledge").status_code == 200

    # 10. Admin sees acknowledgement & PDF export succeeds without restricted leak
    r_adm_h = client.get(f"/api/handovers/{hid}")
    assert r_adm_h.json()["status"] == "acknowledged"
    r_pdf = c_inc.get(f"/api/handovers/{hid}/export.pdf")
    assert r_pdf.status_code == 200
    assert r_pdf.content.startswith(b"%PDF")
    assert b"PRIVATE_COMPENSATION_991" not in r_pdf.content


def test_role_matrix_security_headers_and_error_handling(client: TestClient):
    tag = uuid.uuid4().hex[:6]
    _signup_login(client, f"Admin {tag}", f"adm_{tag}@sec.example.com")
    ws_id = client.post("/api/workspaces", json={"name": f"Sec WS {tag}"}).json()["id"]
    pid = client.post("/api/projects", json={"workspace_id": ws_id, "name": f"Sec Proj {tag}"}).json()["id"]

    # Unauthenticated -> 401
    c_anon = TestClient(app, raise_server_exceptions=False)
    assert c_anon.get(f"/api/projects/{pid}/sources").status_code == 401
    assert c_anon.get("/api/handovers").status_code == 401

    # Security headers & health endpoint
    r_health = c_anon.get("/api/health")
    assert r_health.status_code == 200
    assert r_health.json()["db"] == "ok"
    assert r_health.json()["storage"] == "ok"
    assert r_health.headers.get("x-content-type-options") == "nosniff"
    assert r_health.headers.get("x-frame-options") == "DENY"
    assert r_health.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    # Malformed JSON & missing fields -> 422; unknown IDs -> 404
    r_bad_json = client.post("/api/projects", content=b"{not-json", headers={"content-type": "application/json"})
    assert r_bad_json.status_code == 422
    assert client.post("/api/projects", json={"workspace_id": ws_id}).status_code == 422
    assert client.get("/api/projects/does-not-exist").status_code == 404
    assert client.get("/api/handovers/does-not-exist").status_code == 404
    assert client.get("/api/unknown-endpoint-check").status_code == 404

    # Cross-workspace outsider -> 404
    c_other = TestClient(app, raise_server_exceptions=False)
    _signup_login(c_other, f"Outsider {tag}", f"out_{tag}@sec.example.com")
    assert c_other.get(f"/api/projects/{pid}/sources").status_code == 404
    assert c_other.get(f"/api/projects/{pid}/claims").status_code == 404
    assert c_other.get(f"/api/projects/{pid}/contradictions").status_code == 404

    # Incoming/departing cannot call admin-only endpoints (403)
    c_inc = TestClient(app, raise_server_exceptions=False)
    inc = _signup_login(c_inc, f"Inc {tag}", f"inc_{tag}@sec.example.com")
    from tests.conftest import TestingSession
    with TestingSession() as db:
        db.add(Membership(workspace_id=ws_id, user_id=inc["id"], role="incoming"))
        db.commit()

    assert c_inc.post(f"/api/projects/{pid}/analyze").status_code == 403
    assert c_inc.post(f"/api/projects/{pid}/handovers", json={}).status_code == 403
    assert c_inc.get(f"/api/projects/{pid}/review/queue").status_code == 403


def test_demo_workspace_and_role_isolation():
    c_anon = TestClient(app, raise_server_exceptions=False)
    info = c_anon.get("/api/auth/demo")
    assert info.status_code == 200
    assert info.json()["synthetic"] is True
    assert len(info.json()["accounts"]) == 3

    # Admin demo login
    c_adm = TestClient(app, raise_server_exceptions=False)
    r_adm = c_adm.post("/api/auth/demo", json={"role": "admin"})
    assert r_adm.status_code == 200
    projs = c_adm.get("/api/projects").json()
    demo_proj = next(p for p in projs if p["id"] == "demo-atlas-project")
    assert demo_proj["is_synthetic"] is True

    # Non-destructive: cannot delete demo project
    assert c_adm.delete(f"/api/projects/{demo_proj['id']}").status_code == 403

    # Incoming demo login: sees shared handover, zero restricted sources
    c_inc = TestClient(app, raise_server_exceptions=False)
    assert c_inc.post("/api/auth/demo", json={"role": "incoming"}).status_code == 200
    inc_srcs = c_inc.get(f"/api/projects/{demo_proj['id']}/sources").json()
    assert all(s["clearance_level"] != "restricted" for s in inc_srcs)
    inc_hs = c_inc.get("/api/handovers").json()
    assert len(inc_hs) >= 1
    assert c_inc.get(f"/api/handovers/{inc_hs[0]['id']}").status_code == 200

    # Departing demo login: cannot access full handovers
    c_dep = TestClient(app, raise_server_exceptions=False)
    assert c_dep.post("/api/auth/demo", json={"role": "departing"}).status_code == 200
    assert c_dep.get("/api/handovers").json() == []


def test_postgres_url_normalization_and_ephemeral_upload_resilience(tmp_path):
    """Verify postgres:// URLs normalize to postgresql+psycopg:// and missing upload files never 500."""
    from pathlib import Path
    from app.config import Settings
    from app.db import SessionLocal
    from app.models import Source

    s1 = Settings(DATABASE_URL="postgres://u:p@host:5432/db", SECRET_KEY="x" * 32)
    s2 = Settings(DATABASE_URL="postgresql://u:p@host:5432/db", SECRET_KEY="x" * 32)
    assert s1.DATABASE_URL == "postgresql+psycopg://u:p@host:5432/db"
    assert s2.DATABASE_URL == "postgresql+psycopg://u:p@host:5432/db"

    c_adm = TestClient(app, raise_server_exceptions=False)
    assert c_adm.post("/api/auth/demo", json={"role": "admin"}).status_code == 200
    srcs = c_adm.get("/api/projects/demo-atlas-project/sources").json()
    file_src = next(s for s in srcs if s["type"] in ("markdown", "csv", "chat_json"))

    # Simulate ephemeral disk wipe: remove the stored file and set source status to failed
    db = SessionLocal()
    try:
        db_src = db.get(Source, file_src["id"])
        assert db_src is not None
        if db_src.file_path:
            Path(db_src.file_path).unlink(missing_ok=True)
        db_src.status = "failed"
        db.commit()
    finally:
        db.close()

    # Listing sources and reading parsed chunks from DB still work without 500
    assert c_adm.get("/api/projects/demo-atlas-project/sources").status_code == 200
    assert c_adm.get(f"/api/projects/demo-atlas-project/sources/{file_src['id']}/chunks").status_code == 200

    # Retrying a source whose file was wiped returns 409 with clear message (not 500)
    r_retry = c_adm.post(f"/api/projects/demo-atlas-project/sources/{file_src['id']}/retry")
    assert r_retry.status_code == 409
    assert "ephemeral" in r_retry.json()["detail"].lower() or "re-upload" in r_retry.json()["detail"].lower()


def test_alembic_models_in_sync_and_postgres_ddl_safe(monkeypatch, tmp_path):
    """Fail if SQLAlchemy models and Alembic migrations diverge, or if Postgres DDL has unsafe DROP CONSTRAINT."""
    import io
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    import app.config as app_config

    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))

    # 1. Verify models and migrations do not diverge on a freshly migrated DB
    db_file = tmp_path / "alembic_check.db"
    monkeypatch.setattr(app_config.settings, "DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    command.upgrade(cfg, "head")
    command.check(cfg)

    # 2. Verify PostgreSQL offline SQL generation succeeds and uses IF EXISTS for all DROP CONSTRAINTs
    import contextlib
    buf = io.StringIO()
    pg_cfg = Config(str(backend_dir / "alembic.ini"))
    pg_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    monkeypatch.setattr(app_config.settings, "DATABASE_URL", "postgresql+psycopg://user:pass@localhost/db")
    with contextlib.redirect_stdout(buf):
        command.upgrade(pg_cfg, "head", sql=True)
    ddl = buf.getvalue()
    assert "ALTER TABLE handover_sections ADD COLUMN approved_with_gaps BOOLEAN DEFAULT false NOT NULL" in ddl
    for line in ddl.splitlines():
        if "DROP CONSTRAINT" in line.upper():
            assert "IF EXISTS" in line.upper(), f"Unsafe DROP CONSTRAINT in Postgres DDL: {line}"
