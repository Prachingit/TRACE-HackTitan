"""Comprehensive pytest test suite for TRACE Phase 1.

Verifies:
- Health endpoint status and DB check
- Demo load idempotency
- Registered sources count
- Restricted sources hidden for incoming/departing roles, visible for admin
- Summary counts computed from database rows
- 401 on unknown or missing demo user
"""

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.main import app
from app.models import Membership, Project, Source
from app.services.seed import seed_atlas

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    """Ensure clean schema and seeded Atlas Workspace before tests."""
    init_db()
    seed_atlas()
    yield


def test_health_endpoint():
    """GET /api/health returns status, version, and db: ok."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "1.0.0"
    assert data["db"] == "ok"


def test_demo_load_idempotency():
    """POST /api/demo/load seeds Atlas Workspace without duplicating rows."""
    db = SessionLocal()
    try:
        initial_projects = db.query(Project).count()
        initial_sources = db.query(Source).count()
        initial_memberships = db.query(Membership).count()

        # Run demo load via API
        response = client.post("/api/demo/load")
        assert response.status_code == 200
        data = response.json()
        assert data["project_id"] == "prj-atlas-core"
        assert data["workspace_id"] == "ws-atlas"
        assert data["sources_registered"] == 7

        # Verify no duplicate records were created
        assert db.query(Project).count() == initial_projects
        assert db.query(Source).count() == initial_sources
        assert db.query(Membership).count() == initial_memberships
    finally:
        db.close()


def test_current_user_me_endpoint():
    """GET /api/me returns active demo identity and workspace."""
    response = client.get("/api/me", headers={"X-Demo-User": "usr-meera"})
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "usr-meera"
    assert data["role"] == "admin"
    assert data["workspace_id"] == "ws-atlas"


def test_unauthorized_on_missing_or_unknown_user():
    """Unknown or missing X-Demo-User returns HTTP 401."""
    # Missing header
    res_missing = client.get("/api/me")
    assert res_missing.status_code == 401
    assert "Missing demo authentication header" in res_missing.json()["detail"]

    # Unknown user id
    res_unknown = client.get("/api/projects", headers={"X-Demo-User": "invalid_ghost_user"})
    assert res_unknown.status_code == 401
    assert "Unknown demo user" in res_unknown.json()["detail"]


def test_sources_count_and_clearance_filtering():
    """Admin sees all 7 sources; incoming and departing roles have restricted hidden."""
    project_id = "prj-atlas-core"

    # 1. Admin view (usr-meera) -> 7 sources, including restricted
    res_admin = client.get(
        f"/api/projects/{project_id}/sources",
        headers={"X-Demo-User": "usr-meera"},
    )
    assert res_admin.status_code == 200
    admin_sources = res_admin.json()
    assert len(admin_sources) == 7

    admin_source_ids = {s["id"] for s in admin_sources}
    assert "SRC-007" in admin_source_ids
    restricted_item = next(s for s in admin_sources if s["id"] == "SRC-007")
    assert restricted_item["clearance_level"] == "restricted"
    assert restricted_item["filename"] == "restricted_internal.md"

    # 2. Incoming view (usr-priya) -> 6 sources, restricted file excluded
    res_incoming = client.get(
        f"/api/projects/{project_id}/sources",
        headers={"X-Demo-User": "usr-priya"},
    )
    assert res_incoming.status_code == 200
    incoming_sources = res_incoming.json()
    assert len(incoming_sources) == 6
    incoming_source_ids = {s["id"] for s in incoming_sources}
    assert "SRC-007" not in incoming_source_ids
    assert all(s["clearance_level"] != "restricted" for s in incoming_sources)

    # 3. Departing view (usr-rahul) -> 6 sources, restricted file excluded
    res_departing = client.get(
        f"/api/projects/{project_id}/sources",
        headers={"X-Demo-User": "usr-rahul"},
    )
    assert res_departing.status_code == 200
    departing_sources = res_departing.json()
    assert len(departing_sources) == 6
    assert "SRC-007" not in {s["id"] for s in departing_sources}


def test_project_summary_matches_database_rows():
    """Summary counts match live DB row counts; claims and contradictions are 0."""
    project_id = "prj-atlas-core"
    db = SessionLocal()
    try:
        db_source_count = db.query(Source).filter(Source.project_id == project_id).count()
        db_member_count = db.query(Membership).filter(Membership.workspace_id == "ws-atlas").count()

        response = client.get(
            f"/api/projects/{project_id}/summary",
            headers={"X-Demo-User": "usr-meera"},
        )
        assert response.status_code == 200
        summary = response.json()

        assert summary["project_id"] == project_id
        assert summary["is_synthetic"] is True
        assert summary["source_count"] == db_source_count
        assert summary["member_count"] == db_member_count
        assert summary["claim_count"] == 0
        assert summary["open_contradiction_count"] == 0

        # Verify source breakdown
        assert summary["sources_by_type"]["github_commits"] == 1
        assert summary["sources_by_type"]["csv"] == 1
        assert summary["sources_by_type"]["markdown"] == 4
        assert summary["sources_by_type"]["chat_json"] == 1
    finally:
        db.close()


def test_project_members_endpoint():
    """GET /api/projects/{id}/members returns all team members."""
    response = client.get(
        "/api/projects/prj-atlas-core/members",
        headers={"X-Demo-User": "usr-meera"},
    )
    assert response.status_code == 200
    members = response.json()
    assert len(members) == 4

    role_by_user = {m["user_id"]: m["role"] for m in members}
    assert role_by_user["usr-meera"] == "admin"
    assert role_by_user["usr-priya"] == "incoming"
    assert role_by_user["usr-rahul"] == "departing"
    assert role_by_user["usr-ankit"] == "team_member"
