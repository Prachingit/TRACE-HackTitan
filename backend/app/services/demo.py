"""Idempotent demo workspace seeder for judges (Phase 8).

Seeds an isolated, clearly labelled SYNTHETIC 'Atlas Workspace' using the real
ingestion, reconstruction, contradiction, interview, and handover engines.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.engine.handover import (
    SECTION_DEFS,
    approve_handover,
    generate_handover,
    review_handover_section,
    share_handover,
)
from app.engine.interview.service import generate_questions
from app.engine.pipeline import run_analysis_sync
from app.models import (
    Claim,
    Contradiction,
    Handover,
    Membership,
    Project,
    ReviewEvent,
    User,
    Workspace,
)
from app.core.security import hash_password
from app.services.seed import load_atlas_sample

logger = logging.getLogger("trace.demo")

DEMO_WS_ID = "demo-atlas-workspace"
DEMO_PROJECT_ID = "demo-atlas-project"
DEMO_PASSWORD = "DemoTrace2026!"

DEMO_ACCOUNTS: List[Dict[str, str]] = [
    {
        "role": "admin",
        "label": "Team Lead / Admin (Alex)",
        "name": "Alex Rivera (Demo Lead)",
        "email": "alex.lead@demo.example.com",
        "password": DEMO_PASSWORD,
        "summary": "Full workspace access: sees restricted records, review workbench, contradiction radar, and Handover Center.",
    },
    {
        "role": "incoming",
        "label": "Incoming Member (Priya)",
        "email": "priya.incoming@demo.example.com",
        "name": "Priya Nair (Demo Incoming)",
        "password": DEMO_PASSWORD,
        "summary": "Incoming Portal only: sees approved & shared handover + ranked plan; restricted and unreviewed items are hidden.",
    },
    {
        "role": "departing",
        "label": "Departing Member (Rahul)",
        "name": "Rahul Sharma (Demo Departing)",
        "email": "rahul.departing@demo.example.com",
        "password": DEMO_PASSWORD,
        "summary": "Departing view: sees own contributions & exit interview items; no restricted records or full handovers.",
    },
]


def _get_or_create_demo_user(db: Session, acc: Dict[str, str]) -> User:
    u = db.query(User).filter(User.email == acc["email"]).first()
    if u is None:
        u = User(
            name=acc["name"],
            email=acc["email"],
            password_hash=hash_password(acc["password"]),
        )
        db.add(u)
        db.flush()
    return u


def ensure_demo_seeded(db: Session) -> Dict[str, Any]:
    """Idempotently seed the Atlas Demo Workspace using the real TRACE engines."""
    ws = db.get(Workspace, DEMO_WS_ID)
    users_by_role: Dict[str, User] = {}
    for acc in DEMO_ACCOUNTS:
        users_by_role[acc["role"]] = _get_or_create_demo_user(db, acc)

    admin_user = users_by_role["admin"]
    incoming_user = users_by_role["incoming"]
    departing_user = users_by_role["departing"]

    if ws is None:
        ws = Workspace(
            id=DEMO_WS_ID,
            name="Atlas Workspace (SYNTHETIC DEMO)",
        )
        db.add(ws)
        db.flush()

    for role_key, usr in users_by_role.items():
        mem = (
            db.query(Membership)
            .filter(Membership.workspace_id == ws.id, Membership.user_id == usr.id)
            .first()
        )
        if mem is None:
            db.add(Membership(workspace_id=ws.id, user_id=usr.id, role=role_key))
    db.flush()

    project = db.get(Project, DEMO_PROJECT_ID)
    if project is None:
        project = Project(
            id=DEMO_PROJECT_ID,
            workspace_id=ws.id,
            name="Atlas Core Platform (SYNTHETIC)",
            description="Synthetic multi-source handover demo built from the real TRACE engine.",
            category="Backend Platform",
            team_size=5,
            technologies="Python, FastAPI, PostgreSQL, React",
            is_synthetic=True,
        )
        db.add(project)
        db.commit()
    else:
        db.commit()

    # Check if already seeded with handovers
    existing_handovers = db.query(Handover).filter(Handover.project_id == project.id).count()
    if existing_handovers >= 2:
        return {"seeded": False, "workspace_id": ws.id, "project_id": project.id}

    # 1. Load & parse Atlas sample files via real ingestion
    try:
        load_atlas_sample(db, project.id)
    except Exception as exc:
        logger.warning("Demo Atlas sample load warning: %s", exc)

    # 2. Run real reconstruction & contradiction radar if no claims exist yet
    existing_claims = db.query(Claim).filter(Claim.project_id == project.id).count()
    if existing_claims == 0:
        run_analysis_sync(db, project_id=project.id, user_id=admin_user.id)

    # 3. Generate real exit interview questions
    generate_questions(db, project)

    # 4. Human-approve non-restricted, non-conflicting claims so Handover v1 has real approved facts
    claims = db.query(Claim).filter(Claim.project_id == project.id).all()
    open_ctrs = (
        db.query(Contradiction)
        .filter(Contradiction.project_id == project.id, Contradiction.status == "open")
        .all()
    )
    conflicting_ids = {c.id for ctr in open_ctrs for c in (ctr.claims or [])}

    now = datetime.now(timezone.utc)
    approved_some = False
    for c in claims:
        if c.clearance_level == "restricted":
            continue
        if c.id in conflicting_ids or c.verification_status == "conflicting":
            continue
        if c.review_status == "unreviewed":
            c.review_status = "approved"
            c.reviewed_by = admin_user.id
            c.reviewed_at = now
            c.review_note = "Pre-approved in synthetic demo seed."
            db.add(
                ReviewEvent(
                    claim_id=c.id,
                    reviewer_id=admin_user.id,
                    action="approve",
                    old_text=c.text,
                    new_text=c.text,
                    version=1,
                    note="Pre-approved in synthetic demo seed.",
                    resulting_review_status="approved",
                    resulting_verification_status=c.verification_status,
                )
            )
            approved_some = True
    if approved_some:
        db.commit()

    # 5. Generate v1 (approved + shared with Priya) and v2 (draft ready for Admin review)
    if existing_handovers == 0:
        h1 = generate_handover(
            db,
            project,
            admin_user,
            departing_user_id=departing_user.id,
            target_user_id=incoming_user.id,
            title="Atlas Core Platform — Shared Handover (SYNTHETIC)",
            period_label="Q4 2026",
        )
        for sec_key, _ in SECTION_DEFS:
            if sec_key == "knowledge_gaps":
                review_handover_section(
                    db,
                    h1,
                    sec_key,
                    admin_user,
                    review_status="approved_with_gaps",
                    approved_with_gaps=True,
                    gap_note="Demo project intentionally retains open contradictions for judges to inspect.",
                )
            else:
                review_handover_section(db, h1, sec_key, admin_user, review_status="approved")
        approve_handover(db, h1, admin_user)
        share_handover(db, h1, admin_user, incoming_user.id)

        # Draft handover v2 ready for Alex (Admin) to review in Handover Center
        generate_handover(
            db,
            project,
            admin_user,
            departing_user_id=departing_user.id,
            target_user_id=incoming_user.id,
            title="Atlas Core Platform — Draft Review (SYNTHETIC)",
            period_label="Q4 2026 (Draft)",
        )

    return {"seeded": True, "workspace_id": ws.id, "project_id": project.id}
