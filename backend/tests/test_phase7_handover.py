"""Phase 7a tests: Clearance engine, Handover Center, Ranked Plan, PDF export, and Assistant."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.engine.assistant import ask_project_knowledge
from app.engine.clearance import resolve_viewer_profile
from app.engine.handover import SECTION_DEFS
from app.engine.plan import build_ranked_plan
from app.main import app
from app.models import (
    Chunk,
    Claim,
    ClaimEvidence,
    Contradiction,
    HandoverEvent,
    Membership,
    Project,
    Source,
    User,
)
from tests.conftest import TestingSession


def _signup_and_login(client: TestClient, name: str, email: str, password: str = "Pass123456!") -> dict:
    r = client.post(
        "/api/auth/signup",
        json={"name": name, "email": email, "password": password, "confirm_password": password},
    )
    assert r.status_code in (200, 201), r.text
    r2 = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r2.status_code == 200, r2.text
    return r2.json()


def _setup_workspace_and_project(client: TestClient, tag: str):
    admin = _signup_and_login(client, f"Maya Admin {tag}", f"maya_{tag}@example.com")
    ws_r = client.post("/api/workspaces", json={"name": f"Beacon WS {tag}"})
    assert ws_r.status_code == 201, ws_r.text
    ws_id = ws_r.json()["id"]

    proj_r = client.post(
        "/api/projects",
        json={"workspace_id": ws_id, "name": f"Beacon Billing {tag}", "description": "Billing rewrite"},
    )
    assert proj_r.status_code == 201, proj_r.text
    proj_id = proj_r.json()["id"]

    # Create incoming, departing, and other_incoming users via signup then add memberships in DB
    c_inc = TestClient(app, raise_server_exceptions=False)
    inc = _signup_and_login(c_inc, f"Devon Incoming {tag}", f"devon_{tag}@example.com")

    c_dep = TestClient(app, raise_server_exceptions=False)
    dep = _signup_and_login(c_dep, f"Rohan Departing {tag}", f"rohan_{tag}@example.com")

    c_other_inc = TestClient(app, raise_server_exceptions=False)
    other_inc = _signup_and_login(c_other_inc, f"Nora Incoming {tag}", f"nora_{tag}@example.com")

    c_outsider = TestClient(app, raise_server_exceptions=False)
    _signup_and_login(c_outsider, f"Zack Outsider {tag}", f"zack_{tag}@example.com")

    with TestingSession() as db:
        db.add(Membership(workspace_id=ws_id, user_id=inc["id"], role="incoming"))
        db.add(Membership(workspace_id=ws_id, user_id=dep["id"], role="departing"))
        db.add(Membership(workspace_id=ws_id, user_id=other_inc["id"], role="incoming"))
        db.commit()

    return {
        "ws_id": ws_id,
        "proj_id": proj_id,
        "admin": admin,
        "c_admin": client,
        "inc": inc,
        "c_inc": c_inc,
        "dep": dep,
        "c_dep": c_dep,
        "other_inc": other_inc,
        "c_other_inc": c_other_inc,
        "c_outsider": c_outsider,
    }


def _seed_project_knowledge(proj_id: str, admin_id: str) -> dict:
    with TestingSession() as db:
        src_team = Source(
            id=f"src-team-{uuid.uuid4().hex[:8]}",
            project_id=proj_id,
            type="markdown",
            filename="billing_architecture.md",
            clearance_level="team",
            status="parsed",
        )
        src_restr = Source(
            id=f"src-rest-{uuid.uuid4().hex[:8]}",
            project_id=proj_id,
            type="txt",
            filename="secret_compensation.txt",
            clearance_level="restricted",
            status="parsed",
        )
        db.add_all([src_team, src_restr])
        db.flush()

        ch_team = Chunk(
            id=f"chk-team-{uuid.uuid4().hex[:8]}",
            source_id=src_team.id,
            ordinal=0,
            text="We decided to use Stripe webhooks for invoice reconciliation in checkout.py. Migration task is pending.",
            locator="line 1",
        )
        ch_restr = Chunk(
            id=f"chk-rest-{uuid.uuid4().hex[:8]}",
            source_id=src_restr.id,
            ordinal=0,
            text="CONFIDENTIAL_SECRET_KEY_SALARY: Executive bonus pool is 18%.",
            locator="line 1",
        )
        db.add_all([ch_team, ch_restr])
        db.flush()

        c_approved_dec = Claim(
            id=f"clm-dec-{uuid.uuid4().hex[:8]}",
            project_id=proj_id,
            claim_type="decision",
            title="Use Stripe webhooks",
            text="Use Stripe webhooks for invoice reconciliation.",
            module="billing",
            owner_name="Rohan Departing",
            verification_status="verified",
            review_status="approved",
            clearance_level="team",
            reviewed_by=admin_id,
        )
        c_approved_pending = Claim(
            id=f"clm-tsk-{uuid.uuid4().hex[:8]}",
            project_id=proj_id,
            claim_type="task_status",
            title="Migrate invoice table",
            text="Migrate invoice table in checkout.py",
            module="billing",
            owner_name="Rohan Departing",
            verification_status="verified",
            review_status="approved",
            clearance_level="team",
            attrs_json=json.dumps({"task_name": "Migrate invoice table", "status": "pending"}),
            reviewed_by=admin_id,
        )
        c_unreviewed = Claim(
            id=f"clm-unrev-{uuid.uuid4().hex[:8]}",
            project_id=proj_id,
            claim_type="task_status",
            title="Unreviewed draft task",
            text="UNREVIEWED_FACT_SHOULD_NOT_SHOW_TO_INCOMING",
            module="billing",
            verification_status="inferred",
            review_status="unreviewed",
            clearance_level="team",
            attrs_json=json.dumps({"task_name": "Unreviewed draft task", "status": "in_progress"}),
        )
        c_restricted = Claim(
            id=f"clm-rest-{uuid.uuid4().hex[:8]}",
            project_id=proj_id,
            claim_type="decision",
            title="Confidential executive bonus rule",
            text="CONFIDENTIAL_SECRET_KEY_SALARY bonus pool is 18%.",
            module="hr",
            verification_status="verified",
            review_status="approved",
            clearance_level="restricted",
            reviewed_by=admin_id,
        )
        db.add_all([c_approved_dec, c_approved_pending, c_unreviewed, c_restricted])
        db.flush()

        db.add_all(
            [
                ClaimEvidence(
                    claim_id=c_approved_dec.id,
                    source_id=src_team.id,
                    chunk_id=ch_team.id,
                    excerpt="We decided to use Stripe webhooks for invoice reconciliation",
                    evidence_type="document",
                ),
                ClaimEvidence(
                    claim_id=c_approved_pending.id,
                    source_id=src_team.id,
                    chunk_id=ch_team.id,
                    excerpt="Migration task is pending.",
                    evidence_type="document",
                ),
                ClaimEvidence(
                    claim_id=c_unreviewed.id,
                    source_id=src_team.id,
                    chunk_id=ch_team.id,
                    excerpt="Migration task is pending.",
                    evidence_type="document",
                ),
                ClaimEvidence(
                    claim_id=c_restricted.id,
                    source_id=src_restr.id,
                    chunk_id=ch_restr.id,
                    excerpt="CONFIDENTIAL_SECRET_KEY_SALARY: Executive bonus pool is 18%.",
                    evidence_type="document",
                ),
            ]
        )
        db.commit()
        return {
            "src_team_id": src_team.id,
            "src_restr_id": src_restr.id,
            "c_approved_dec_id": c_approved_dec.id,
            "c_approved_pending_id": c_approved_pending.id,
            "c_unreviewed_id": c_unreviewed.id,
            "c_restricted_id": c_restricted.id,
        }


def test_clearance_and_handover_lifecycle_and_pdf(client: TestClient):
    env = _setup_workspace_and_project(client, "life1")
    seed = _seed_project_knowledge(env["proj_id"], env["admin"]["id"])

    # 1. Restricted source & claim hidden from incoming & departing; visible to admin
    r_adm_src = env["c_admin"].get(f"/api/projects/{env['proj_id']}/sources")
    assert r_adm_src.status_code == 200
    assert len(r_adm_src.json()) == 2

    r_inc_src = env["c_inc"].get(f"/api/projects/{env['proj_id']}/sources")
    assert r_inc_src.status_code == 200
    assert [s["id"] for s in r_inc_src.json()] == [seed["src_team_id"]]

    r_inc_restr = env["c_inc"].get(f"/api/projects/{env['proj_id']}/sources/{seed['src_restr_id']}")
    assert r_inc_restr.status_code == 404

    # 2. View-as preview is admin-only and read-only
    r_bad_preview = env["c_inc"].get(f"/api/projects/{env['proj_id']}/claims?view_as=incoming")
    assert r_bad_preview.status_code == 403
    r_adm_preview = env["c_admin"].get(f"/api/projects/{env['proj_id']}/sources?view_as=incoming")
    assert r_adm_preview.status_code == 200
    assert [s["id"] for s in r_adm_preview.json()] == [seed["src_team_id"]]

    # 3. Generate Handover
    r_gen = env["c_admin"].post(
        f"/api/projects/{env['proj_id']}/handovers",
        json={"departing_user_id": env["dep"]["id"], "target_user_id": env["inc"]["id"], "period_label": "Q4"},
    )
    assert r_gen.status_code == 201, r_gen.text
    h = r_gen.json()
    hid = h["id"]
    assert h["status"] == "draft"
    assert len(h["sections"]) == len(SECTION_DEFS)
    assert 0 <= h["readiness_score"] <= 100
    assert "formula" in h["readiness_json"]

    # Check rationale fallback ("Rationale not recorded.") on decision without rationale keywords
    sec_dec = next(s for s in h["sections"] if s["section_key"] == "decisions_rationale")
    assert sec_dec["body_json"]["items"][0]["rationale"] == "Rationale not recorded."

    # Check unreviewed item is NOT in approved sections, only in admin knowledge_gaps
    sec_wip = next(s for s in h["sections"] if s["section_key"] == "work_in_progress")
    assert sec_wip["body_json"]["items"] == []
    sec_gaps = next(s for s in h["sections"] if s["section_key"] == "knowledge_gaps")
    assert any(it["claim_id"] == seed["c_unreviewed_id"] for it in sec_gaps["body_json"]["needs_review_items"])

    # 4. Cannot approve handover while sections are unreviewed
    r_premature = env["c_admin"].post(f"/api/handovers/{hid}/approve")
    assert r_premature.status_code == 400

    # Cannot approve_with_gaps without gap_note
    r_no_note = env["c_admin"].patch(
        f"/api/handovers/{hid}/sections/overview",
        json={"review_status": "approved_with_gaps"},
    )
    assert r_no_note.status_code == 400

    # Approve all 10 sections (one with gap_note)
    for sec_key, _ in SECTION_DEFS:
        payload = (
            {"review_status": "approved_with_gaps", "gap_note": "Minor doc gap accepted"}
            if sec_key == "knowledge_gaps"
            else {"review_status": "approved"}
        )
        r_sec = env["c_admin"].patch(f"/api/handovers/{hid}/sections/{sec_key}", json=payload)
        assert r_sec.status_code == 200, r_sec.text

    # View-as preview blocks mutation
    r_prev_patch = env["c_admin"].patch(
        f"/api/handovers/{hid}/sections/overview?view_as=incoming",
        json={"review_status": "approved"},
    )
    assert r_prev_patch.status_code == 403

    r_app = env["c_admin"].post(f"/api/handovers/{hid}/approve")
    assert r_app.status_code == 200, r_app.text
    assert r_app.json()["status"] == "approved"

    # 5. Before sharing, incoming cannot view handover (403) and outsider gets 404
    assert env["c_inc"].get(f"/api/handovers/{hid}").status_code == 403
    assert env["c_outsider"].get(f"/api/handovers/{hid}").status_code == 404

    # 6. Share with Devon (incoming)
    r_share = env["c_admin"].post(f"/api/handovers/{hid}/share", json={"target_user_id": env["inc"]["id"]})
    assert r_share.status_code == 200
    assert r_share.json()["status"] == "shared"

    # Another incoming member in same workspace (Nora) still gets 403
    assert env["c_other_inc"].get(f"/api/handovers/{hid}").status_code == 403
    # Departing member gets 403 on full handover
    assert env["c_dep"].get(f"/api/handovers/{hid}").status_code == 403

    # Devon sees shared handover, without restricted items or unreviewed needs_review_items
    r_devon = env["c_inc"].get(f"/api/handovers/{hid}")
    assert r_devon.status_code == 200, r_devon.text
    devon_text = json.dumps(r_devon.json())
    assert "CONFIDENTIAL_SECRET_KEY_SALARY" not in devon_text
    assert "UNREVIEWED_FACT_SHOULD_NOT_SHOW_TO_INCOMING" not in devon_text

    # 7. Onboarding checklist + Acknowledge
    r_ob = env["c_inc"].post(
        f"/api/handovers/{hid}/onboarding",
        json={"item_key": f"plan-{seed['c_approved_pending_id']}", "completed": True, "note": "Started"},
    )
    assert r_ob.status_code == 200
    assert r_ob.json()["completed"] is True

    r_ack = env["c_inc"].post(f"/api/handovers/{hid}/acknowledge")
    assert r_ack.status_code == 200
    assert r_ack.json()["status"] == "acknowledged"

    # 8. PDF export works and contains no restricted text for incoming
    r_pdf = env["c_inc"].get(f"/api/handovers/{hid}/export.pdf")
    assert r_pdf.status_code == 200
    assert r_pdf.headers["content-type"] == "application/pdf"
    assert r_pdf.content.startswith(b"%PDF")
    assert b"CONFIDENTIAL_SECRET_KEY_SALARY" not in r_pdf.content

    # 9. Revoke share hides handover again from Devon
    r_rev = env["c_admin"].post(f"/api/handovers/{hid}/revoke")
    assert r_rev.status_code == 200
    assert env["c_inc"].get(f"/api/handovers/{hid}").status_code == 403

    # 10. History is append-only and records lifecycle events
    r_hist = env["c_admin"].get(f"/api/handovers/{hid}/history")
    assert r_hist.status_code == 200
    actions = {ev["action"] for ev in r_hist.json()}
    assert {"generated", "section_reviewed", "approved", "shared", "acknowledged", "share_revoked"}.issubset(actions)

    with TestingSession() as db:
        ev = db.query(HandoverEvent).filter(HandoverEvent.handover_id == hid).first()
        ev.action = "tampered"
        with pytest.raises(ValueError):
            db.commit()
        db.rollback()


def test_clearance_override_and_assistant_citation_enforcement(client: TestClient):
    env = _setup_workspace_and_project(client, "asst1")
    seed = _seed_project_knowledge(env["proj_id"], env["admin"]["id"])

    # Share an approved handover so incoming can query approved claims
    r_gen = env["c_admin"].post(f"/api/projects/{env['proj_id']}/handovers", json={})
    hid = r_gen.json()["id"]
    for sec_key, _ in SECTION_DEFS:
        env["c_admin"].patch(f"/api/handovers/{hid}/sections/{sec_key}", json={"review_status": "approved"})
    env["c_admin"].post(f"/api/handovers/{hid}/approve")
    env["c_admin"].post(f"/api/handovers/{hid}/share", json={"target_user_id": env["inc"]["id"]})

    # Incoming asks about restricted topic -> must not leak restricted text
    r_ask_secret = env["c_inc"].post(
        f"/api/projects/{env['proj_id']}/ask",
        json={"question": "What is the executive bonus pool salary?"},
    )
    assert r_ask_secret.status_code == 200
    assert "CONFIDENTIAL_SECRET_KEY_SALARY" not in r_ask_secret.json()["answer"]
    assert r_ask_secret.json()["answer"] == "This isn't recorded in the approved handover."
    assert r_ask_secret.json()["citations"] == []

    # Incoming asks about approved Stripe decision -> gets cited answer
    r_ask_ok = env["c_inc"].post(
        f"/api/projects/{env['proj_id']}/ask",
        json={"question": "How does Stripe reconciliation work?"},
    )
    assert r_ask_ok.status_code == 200
    assert len(r_ask_ok.json()["citations"]) >= 1

    # Fabricated LLM citation drops back to deterministic verified citations
    with TestingSession() as db:
        viewer = resolve_viewer_profile(env["inc"]["id"], "Devon", "incoming")
        res = ask_project_knowledge(
            db,
            env["proj_id"],
            viewer,
            "How does Stripe reconciliation work?",
            llm_caller=lambda _p: "Stripe uses magic [claim:nonexistent-id].",
        )
        assert res["mode"] == "deterministic"
        assert "nonexistent-id" not in res["answer"]

    # Admin overrides restricted claim to team with required reason
    r_bad_ov = env["c_admin"].post(
        f"/api/claims/{seed['c_restricted_id']}/clearance",
        json={"clearance_level": "team", "reason": ""},
    )
    assert r_bad_ov.status_code == 400

    r_ov = env["c_admin"].post(
        f"/api/claims/{seed['c_restricted_id']}/clearance",
        json={"clearance_level": "team", "reason": "Redacted and cleared by HR for team onboarding"},
    )
    assert r_ov.status_code == 200
    assert r_ov.json()["clearance_level"] == "team"


def test_ranked_plan_topological_order_and_cycle_handling():
    src = Source(id="s1", project_id="p1", type="markdown", filename="checkout.py", clearance_level="team", status="parsed")
    c_prereq = Claim(
        id="c1",
        project_id="p1",
        claim_type="task_status",
        title="Build schema",
        text="Build invoice schema",
        module="billing",
        verification_status="verified",
        review_status="approved",
        clearance_level="team",
        attrs_json=json.dumps({"task_name": "Build schema", "status": "pending"}),
    )
    c_dep = Claim(
        id="c2",
        project_id="p1",
        claim_type="blocker",
        title="Deploy billing",
        text="Deploy billing blocked until schema ready",
        module="billing",
        verification_status="verified",
        review_status="approved",
        clearance_level="team",
        attrs_json=json.dumps({"task_name": "Deploy billing", "status": "blocked"}),
    )
    c_link = Claim(
        id="c3",
        project_id="p1",
        claim_type="dependency",
        title="Deploy depends on schema",
        text="Deploy billing depends on Build schema",
        module="billing",
        verification_status="verified",
        review_status="approved",
        clearance_level="team",
        attrs_json=json.dumps({"from_task": "Deploy billing", "depends_on": "Build schema"}),
    )
    # Also add a cycle between node A and node B
    c_cyc1 = Claim(
        id="c4",
        project_id="p1",
        claim_type="dependency",
        title="A depends on B",
        text="Node A depends on Node B",
        module="billing",
        verification_status="verified",
        review_status="approved",
        clearance_level="team",
        attrs_json=json.dumps({"from_task": "Node A", "depends_on": "Node B"}),
    )
    c_cyc2 = Claim(
        id="c5",
        project_id="p1",
        claim_type="dependency",
        title="B depends on A",
        text="Node B depends on Node A",
        module="billing",
        verification_status="verified",
        review_status="approved",
        clearance_level="team",
        attrs_json=json.dumps({"from_task": "Node B", "depends_on": "Node A"}),
    )

    ev = {
        "c1": [ClaimEvidence(id="e1", claim_id="c1", source_id="s1", excerpt="schema pending", evidence_type="document")],
        "c2": [ClaimEvidence(id="e2", claim_id="c2", source_id="s1", excerpt="deploy blocked", evidence_type="document")],
    }
    plan, cycle_gaps = build_ranked_plan([c_prereq, c_dep, c_link, c_cyc1, c_cyc2], [], [], ev, {"s1": src})

    assert len(cycle_gaps) == 1
    assert cycle_gaps[0]["kind"] == "dependency_cycle"

    titles = [p["title"] for p in plan]
    assert titles.index("Build schema") < titles.index("Deploy billing")
    assert "checkout.py" in plan[0]["relevant_files"]
