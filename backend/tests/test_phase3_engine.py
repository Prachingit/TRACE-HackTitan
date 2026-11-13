"""Phase 3 tests: Reconstruction Engine (normalise, extract, correlate, timeline, runs)."""

import json
import pytest

from app.engine.extract import (
    extract_all,
    extract_deterministic_for_chunks,
    extract_with_llm_for_source,
    normalise_task_status,
)
from app.engine.pipeline import run_analysis_sync
from app.engine.types import NChunk
from app.models import Claim
from tests.conftest import TestingSession, join_as, make_project, make_user


def _upload(client, pid: str, filename: str, content: bytes, clearance: str = "team"):
    r = client.post(
        f"/api/projects/{pid}/sources/upload",
        files={"file": (filename, content)},
        data={"clearance_level": clearance},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── 1. Deterministic extractor patterns & status synonyms ────────────────────

def test_status_normalisation_synonyms():
    assert normalise_task_status("Done") == "completed"
    assert normalise_task_status("shipped") == "completed"
    assert normalise_task_status("In Progress") == "in_progress"
    assert normalise_task_status("WIP") == "in_progress"
    assert normalise_task_status("To Do") == "pending"
    assert normalise_task_status("Backlog") == "pending"
    assert normalise_task_status("Blocked") == "blocked"
    assert normalise_task_status("On Hold") == "blocked"
    assert normalise_task_status("mystery_state") == "unknown"
    assert normalise_task_status("") == "unknown"


def test_commit_alone_never_marks_feature_completed():
    """A commit existing never means a feature is completed; missing status stays unknown."""
    commit_chunk = NChunk(
        id="chk-commit-1",
        source_id="SRC-C1",
        source_type="github_commits",
        filename="commits.json",
        clearance="team",
        text="feat(billing): implement invoice PDF export\nFiles: backend/app/billing/invoice.py",
        author="Asha Patel",
        timestamp=None,
        locator="sha:abc123456789",
        ordinal=1,
    )
    claims = extract_deterministic_for_chunks([commit_chunk])
    assert len(claims) >= 1
    assert all(c.type != "task_status" or c.attrs.get("status") != "completed" for c in claims)
    contrib = [c for c in claims if c.type == "contribution"]
    assert len(contrib) == 1
    assert contrib[0].module == "billing"
    assert contrib[0].author == "Asha Patel"
    assert contrib[0].extractor == "rule"

    # CSV row with missing/unrecognized status stays unknown and verification='missing'
    csv_chunk = NChunk(
        id="chk-csv-1",
        source_id="SRC-CSV1",
        source_type="csv",
        filename="tasks.csv",
        clearance="team",
        text="id: T-99 | title: Invoice export | assignee: Asha Patel | status: ??? | module: billing",
        author="Asha Patel",
        timestamp=None,
        locator="row:2",
        ordinal=1,
    )
    csv_claims = extract_deterministic_for_chunks([csv_chunk])
    t_claims = [c for c in csv_claims if c.type == "task_status"]
    assert len(t_claims) == 1
    assert t_claims[0].attrs["status"] == "unknown"
    assert t_claims[0].verification == "missing"


def test_deterministic_prose_patterns():
    """Verify decision, ownership, blocker, testing, dependency, and action item patterns."""
    prose = (
        "# Sprint Sync\n"
        "Date: 2026-10-12\n"
        "- We decided to use SQLite for embedded storage in the database module.\n"
        "- Devika Nair will take ownership of the search module.\n"
        "- Checkout release is blocked by gateway sandbox credentials.\n"
        "- Search indexing depends on schema migration completing first.\n"
        "- Auth testing remains strictly pending security validation.\n"
        "-Vikram: Prepare benchmark suite for search queries.\n"
        "- Viktor: Prepare benchmark suite for search queries.\n"
    )
    ch = NChunk(
        id="chk-prose-1",
        source_id="SRC-P1",
        source_type="markdown",
        filename="notes.md",
        clearance="team",
        text=prose,
        author="Lead",
        timestamp=None,
        locator="L1-L9",
        ordinal=1,
    )
    claims = extract_deterministic_for_chunks([ch])
    types = {c.type for c in claims}
    assert "decision" in types
    assert "ownership" in types
    assert "blocker" in types
    assert "dependency" in types
    assert "testing" in types
    assert "task_status" in types
    # Every extracted excerpt must be a literal substring of the chunk text
    for c in claims:
        assert c.evidence
        for ev in c.evidence:
            assert ev.excerpt in ch.text


# ── 2. LLM extractor: valid, hallucinated excerpt dropped, invalid JSON fallback ─

def test_llm_extractor_drops_hallucinated_excerpts_and_validates():
    ch = NChunk(
        id="chk-llm-1",
        source_id="SRC-L1",
        source_type="markdown",
        filename="arch.md",
        clearance="team",
        text="We decided to adopt Redis streams for the notifications module.",
        author="Rohan",
        timestamp=None,
        locator="L1-L2",
        ordinal=1,
    )

    def mock_llm(_chunks):
        return json.dumps({
            "claims": [
                {
                    "claim_type": "decision",
                    "title": "Use Redis streams",
                    "text": "Adopted Redis streams for notifications.",
                    "module": "notifications",
                    "owner": "Rohan",
                    "verification_status": "verified",
                    "confidence": 0.92,
                    "evidence": [
                        {"chunk_id": "chk-llm-1", "excerpt": "decided to adopt Redis streams"}
                    ],
                },
                {
                    "claim_type": "decision",
                    "title": "Hallucinated Kafka migration",
                    "text": "Switched to Kafka.",
                    "module": "notifications",
                    "owner": "Rohan",
                    "verification_status": "verified",
                    "confidence": 0.99,
                    "evidence": [
                        {"chunk_id": "chk-llm-1", "excerpt": "This sentence does not exist anywhere in the chunk"}
                    ],
                },
            ]
        })

    claims, fb_reason, dropped = extract_with_llm_for_source("SRC-L1", [ch], llm_caller=mock_llm)
    assert fb_reason is None
    assert dropped == 1
    assert len(claims) == 1
    assert claims[0].title == "Use Redis streams"
    assert claims[0].extractor == "llm"
    assert claims[0].confidence == 0.92
    assert claims[0].evidence[0].excerpt in ch.text


def test_llm_invalid_json_falls_back_to_rules_honestly():
    ch = NChunk(
        id="chk-llm-2",
        source_id="SRC-L2",
        source_type="markdown",
        filename="notes.md",
        clearance="team",
        text="We agreed to freeze schema changes during the release window.",
        author="Rohan",
        timestamp=None,
        locator="L1-L1",
        ordinal=1,
    )

    def broken_llm(_chunks):
        return "{not valid json at all!!!"

    claims, meta = extract_all([ch], llm_caller=broken_llm)
    assert len(meta["llm_fallbacks"]) == 1
    assert "SRC-L2" in meta["llm_fallbacks"][0]
    assert len(claims) >= 1
    # Never present fallback output as AI output
    assert all(c.extractor == "rule" for c in claims)


# ── 3. End-to-end analysis run, stages, idempotency, reviewed survival & clearance ─

def test_analyze_stages_idempotency_and_reviewed_claim_survival(client):
    admin = make_user("p3_admin@example.com", "Admin")
    _, pid = make_project(admin, "Orbit Service")

    _upload(
        admin,
        pid,
        "tasks.csv",
        b"id,title,assignee,status,module,updated,depends_on\n"
        b"ORB-1,Setup ingestion API,Neha Gupta,Done,ingestion,2026-10-05,\n"
        b"ORB-2,Add worker retry queue,Neha Gupta,In Progress,ingestion,2026-10-12,ORB-1\n",
    )
    _upload(
        admin,
        pid,
        "notes.md",
        b"# Architecture Note\nDate: 2026-10-10\n"
        b"- We decided to store raw payloads in local disk under ingestion module.\n"
        b"- Worker retry queue is blocked by rate-limit configuration.\n",
    )

    r = admin.post(f"/api/projects/{pid}/analyze")
    assert r.status_code == 202
    latest = admin.get(f"/api/projects/{pid}/runs/latest").json()
    assert latest["status"] == "completed"
    stage_keys = [s["key"] for s in latest["stages"]]
    assert stage_keys == [
        "reading_sources",
        "extracting",
        "correlating",
        "detecting_gaps",
        "preparing",
    ]
    assert all(s["status"] == "done" and s["count"] is not None for s in latest["stages"])

    claims_1 = admin.get(f"/api/projects/{pid}/claims").json()
    assert len(claims_1) >= 4

    # Human reviews one claim (edits text and approves)
    target_id = claims_1[0]["id"]
    rev = admin.post(
        f"/api/claims/{target_id}/review",
        json={"action": "edit", "text": "Human-verified statement for handover."},
    )
    assert rev.status_code == 200
    assert rev.json()["review_status"] == "edited"
    assert rev.json()["origin_label"] == "human-reviewed"

    # Re-run analysis: idempotent count & reviewed claim survives untouched
    admin.post(f"/api/projects/{pid}/analyze")
    claims_2 = admin.get(f"/api/projects/{pid}/claims").json()
    assert len(claims_2) == len(claims_1)
    survived = [c for c in claims_2 if c["id"] == target_id]
    assert len(survived) == 1
    assert survived[0]["text"] == "Human-verified statement for handover."
    assert survived[0]["review_status"] == "edited"

    # Timeline & modules endpoints work
    tl = admin.get(f"/api/projects/{pid}/timeline").json()
    assert len(tl) >= 2
    assert tl[0]["timestamp"] <= tl[-1]["timestamp"]

    mods = admin.get(f"/api/projects/{pid}/modules").json()
    assert any(m["name"] == "ingestion" for m in mods)

    # Rename module and verify claims update
    renamed = admin.post(
        f"/api/projects/{pid}/modules/rename",
        json={"from_module": "ingestion", "to_module": "data-pipeline"},
    ).json()
    assert any(m["name"] == "data-pipeline" for m in renamed)
    assert not any(m["name"] == "ingestion" for m in renamed)


def test_clearance_and_isolation_on_claims_and_runs(client):
    admin = make_user("p3_sec_admin@example.com", "Admin")
    ws_id, pid = make_project(admin, "Clearance Project")
    incoming = join_as(admin, ws_id, "p3_incoming@example.com", "incoming")
    outsider = make_user("p3_outsider@example.com", "Outsider")

    _upload(admin, pid, "public_notes.md", b"# Sync\nDate: 2026-10-01\n- We decided to use FastAPI.\n", clearance="team")
    _upload(
        admin,
        pid,
        "exec_only.md",
        b"# Restricted\nDate: 2026-10-02\n- We decided to cap vendor severance budget at 50k.\n",
        clearance="restricted",
    )

    admin.post(f"/api/projects/{pid}/analyze")

    admin_claims = admin.get(f"/api/projects/{pid}/claims").json()
    inc_claims = incoming.get(f"/api/projects/{pid}/claims").json()
    restricted_ids = [c["id"] for c in admin_claims if c["clearance_level"] == "restricted"]
    assert len(restricted_ids) >= 1
    assert all(c["clearance_level"] != "restricted" for c in inc_claims)

    # Incoming cannot fetch a restricted claim by ID
    for rid in restricted_ids:
        assert incoming.get(f"/api/claims/{rid}").status_code == 404

    # Outsider gets 404 on everything
    assert outsider.get(f"/api/projects/{pid}/claims").status_code == 404
    assert outsider.get(f"/api/projects/{pid}/runs/latest").status_code == 404
    assert outsider.get(f"/api/projects/{pid}/timeline").status_code == 404
    assert outsider.get(f"/api/projects/{pid}/modules").status_code == 404
