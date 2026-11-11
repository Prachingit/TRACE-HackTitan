"""Tests for TRACE API endpoints and mock contract validation."""

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app import schemas
from app.config import settings
from app.db import SessionLocal
from app.main import app
from scripts.seed import seed


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """Seed the database once for API tests."""
    seed(reset=True)


@pytest.fixture
def client():
    return TestClient(app)


def test_health_check(client):
    """GET /health returns status: ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_roles(client):
    """GET /api/roles returns all 3 seeded roles with clearance."""
    response = client.get("/api/roles")
    assert response.status_code == 200
    roles = response.json()
    assert len(roles) == 3

    clearance_map = {r["id"]: r["clearance"] for r in roles}
    assert clearance_map.get("team_lead") == "restricted"
    assert clearance_map.get("incoming_developer") == "internal"
    assert clearance_map.get("external_reviewer") == "public"


def test_sources_external_reviewer_excludes_internal_and_restricted(client):
    """external_reviewer (public) sees ONLY public sources."""
    response = client.get("/api/demo/sources", params={"role": "external_reviewer"})
    assert response.status_code == 200
    sources = response.json()

    assert len(sources) > 0
    for src in sources:
        assert src["access_label"] == "public", f"Public role saw non-public source: {src}"

    # Specifically verify internal git log and restricted notes are excluded
    source_ids = {s["id"] for s in sources}
    assert "src-readme" in source_ids
    assert "src-git-log" not in source_ids
    assert "src-restricted-budget" not in source_ids


def test_sources_incoming_developer_sees_public_and_internal(client):
    """incoming_developer (internal) sees public and internal, but NOT restricted."""
    response = client.get("/api/demo/sources", params={"role": "incoming_developer"})
    assert response.status_code == 200
    sources = response.json()

    labels = {s["access_label"] for s in sources}
    assert "public" in labels
    assert "internal" in labels
    assert "restricted" not in labels

    source_ids = {s["id"] for s in sources}
    assert "src-restricted-budget" not in source_ids
    assert "src-git-log" in source_ids
    assert "src-readme" in source_ids


def test_sources_team_lead_sees_all(client):
    """team_lead (restricted) sees public, internal, and restricted sources."""
    response = client.get("/api/demo/sources", params={"role": "team_lead"})
    assert response.status_code == 200
    sources = response.json()

    labels = {s["access_label"] for s in sources}
    assert "public" in labels
    assert "internal" in labels
    assert "restricted" in labels

    source_ids = {s["id"] for s in sources}
    assert "src-restricted-budget" in source_ids
    assert "src-git-log" in source_ids
    assert "src-readme" in source_ids


def test_sources_unknown_role_returns_400(client):
    """Unknown role returns HTTP 400."""
    response = client.get("/api/demo/sources", params={"role": "super_admin_invalid"})
    assert response.status_code == 400
    assert "Unknown role" in response.json()["detail"]


def test_contract_endpoint(client):
    """GET /api/contract returns complete contract schema documentation."""
    response = client.get("/api/contract")
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == "1.0.0"
    assert "Source" in data["models"]
    assert "Claim" in data["models"]
    assert len(data["current_endpoints"]) >= 4
    assert len(data["planned_endpoints"]) >= 8


# --------------------------------------------------------------------------
# Contract Examples Validation against Pydantic Models in schemas.py
# --------------------------------------------------------------------------

def test_validate_handover_mock_against_schema():
    """Validate contract/examples/handover.json against schemas.Handover."""
    example_path = Path(settings.CONTRACT_DIR) / "examples" / "handover.json"
    assert example_path.exists(), f"Missing {example_path}"

    with open(example_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Validate with Pydantic model
    handover = schemas.Handover.model_validate(data)
    assert handover.id == "ho-campusconnect-01"
    assert len(handover.claims) >= 10

    # Verify all four statuses exist
    statuses = {c.status for c in handover.claims}
    assert "verified" in statuses
    assert "inferred" in statuses
    assert "conflicting" in statuses
    assert "missing" in statuses

    # Verify planted cases are represented
    claim_ids = {c.id for c in handover.claims}
    for expected_case in ["claim-c1", "claim-c2", "claim-c3", "claim-g1", "claim-d1", "claim-d2", "claim-o1", "claim-r1"]:
        assert expected_case in claim_ids, f"Planted case {expected_case} missing from handover.json"

    # Verify evidence constraints
    for claim in handover.claims:
        assert len(claim.evidence) >= 1, f"Claim {claim.id} missing evidence"
        for ev in claim.evidence:
            assert len(ev.quote) <= 200, f"Quote exceeds 200 chars in {claim.id}: {ev.quote}"
            assert ev.locator, f"Missing locator in {claim.id}"


def test_validate_role_views_mock_against_schema():
    """Validate contract/examples/role_views.json against schemas.RoleViewsMap."""
    example_path = Path(settings.CONTRACT_DIR) / "examples" / "role_views.json"
    assert example_path.exists(), f"Missing {example_path}"

    with open(example_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    role_views = schemas.RoleViewsMap.model_validate(data).root
    assert "team_lead" in role_views
    assert "incoming_developer" in role_views
    assert "external_reviewer" in role_views

    # Check team_lead sees all and hidden_count == 0
    assert role_views["team_lead"].hidden_count == 0
    assert len(role_views["team_lead"].handover.claims) == 10

    # Check incoming_developer has restricted items hidden
    assert role_views["incoming_developer"].hidden_count == 1
    incoming_labels = {c.access_label for c in role_views["incoming_developer"].handover.claims}
    assert "restricted" not in incoming_labels

    # Check external_reviewer has internal/restricted hidden
    assert role_views["external_reviewer"].hidden_count == 9
    for c in role_views["external_reviewer"].handover.claims:
        assert c.access_label == "public"


def test_validate_plan_mock_against_schema():
    """Validate contract/examples/plan.json against schemas.PlanStepList."""
    example_path = Path(settings.CONTRACT_DIR) / "examples" / "plan.json"
    assert example_path.exists(), f"Missing {example_path}"

    with open(example_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    plan = schemas.PlanStepList.model_validate(data).root
    assert len(plan) == 5
    ranks = [p.rank for p in plan]
    assert ranks == [1, 2, 3, 4, 5]
    for step in plan:
        assert step.action
        assert step.reason
        assert len(step.claim_ids) >= 1


def test_validate_gap_questions_mock_against_schema():
    """Validate contract/examples/gap_questions.json against schemas.GapQuestionList."""
    example_path = Path(settings.CONTRACT_DIR) / "examples" / "gap_questions.json"
    assert example_path.exists(), f"Missing {example_path}"

    with open(example_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    questions = schemas.GapQuestionList.model_validate(data).root
    assert len(questions) == 3
    claim_targets = {q.claim_id for q in questions}
    assert "claim-d2" in claim_targets  # D2
    assert "claim-o1" in claim_targets  # O1
