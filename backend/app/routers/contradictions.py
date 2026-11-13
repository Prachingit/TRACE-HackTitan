"""Phase 5 router: Contradiction Radar list, detail, and manual resolution."""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.engine.clearance import (
    ClearanceError,
    can_view_contradiction,
    resolve_viewer_profile,
)
from app.engine.types import HIDDEN_ROLES
from app.models import (
    Claim,
    Contradiction,
    ContradictionClaim,
    Membership,
    Project,
    Source,
    User,
)
from app.routers.analysis import ClaimDetailResponse, _serialize_claim

router = APIRouter(tags=["Contradictions"])

SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


# ── Schemas ───────────────────────────────────────────────────────────────────

class ContradictionResponse(BaseModel):
    id: str
    project_id: str
    rule_code: str
    severity: str
    reason: str
    suggested_action: str
    status: str
    clearance_level: str
    claim_ids: List[str] = []
    conflicting_source_ids: List[str] = []
    conflicting_sources: List[Dict[str, str]] = []
    created_at: datetime
    resolved_by: Optional[str] = None
    resolved_by_name: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolution_note: Optional[str] = None


class ContradictionDetailResponse(ContradictionResponse):
    claims: List[ClaimDetailResponse] = []


class ResolveContradictionRequest(BaseModel):
    note: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_scoped_project(project_id: str, user_id: str, db: Session) -> tuple[Project, Membership]:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    membership = (
        db.query(Membership)
        .filter(Membership.workspace_id == project.workspace_id, Membership.user_id == user_id)
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project, membership


def _serialize_contradiction(
    ctr: Contradiction,
    role: str,
    db: Session,
    include_claims: bool = False,
) -> ContradictionResponse | ContradictionDetailResponse:
    src_ids: List[str] = []
    if ctr.conflicting_source_ids:
        try:
            src_ids = json.loads(ctr.conflicting_source_ids)
        except json.JSONDecodeError:
            src_ids = []

    hide_restricted = role in HIDDEN_ROLES
    conflicting_sources: List[Dict[str, str]] = []
    filtered_src_ids: List[str] = []
    for sid in src_ids:
        src = db.get(Source, sid)
        if src:
            if hide_restricted and src.clearance_level == "restricted":
                continue
            filtered_src_ids.append(sid)
            conflicting_sources.append({
                "id": src.id,
                "filename": src.filename,
                "type": src.type,
                "clearance_level": src.clearance_level,
            })

    cc_rows = (
        db.query(ContradictionClaim)
        .filter(ContradictionClaim.contradiction_id == ctr.id)
        .all()
    )
    claim_objs: List[Claim] = []
    for cc in cc_rows:
        clm = db.get(Claim, cc.claim_id)
        if clm:
            if hide_restricted and clm.clearance_level == "restricted":
                continue
            claim_objs.append(clm)

    resolver_name = None
    if ctr.resolved_by:
        u = db.get(User, ctr.resolved_by)
        resolver_name = u.name if u else ctr.resolved_by

    base_kwargs = dict(
        id=ctr.id,
        project_id=ctr.project_id,
        rule_code=ctr.rule_code,
        severity=ctr.severity,
        reason=ctr.reason,
        suggested_action=ctr.suggested_action,
        status=ctr.status,
        clearance_level=ctr.clearance_level,
        claim_ids=[c.id for c in claim_objs],
        conflicting_source_ids=filtered_src_ids,
        conflicting_sources=conflicting_sources,
        created_at=ctr.created_at,
        resolved_by=ctr.resolved_by,
        resolved_by_name=resolver_name,
        resolved_at=ctr.resolved_at,
        resolution_note=ctr.resolution_note,
    )

    if not include_claims:
        return ContradictionResponse(**base_kwargs)

    detailed_claims = [_serialize_claim(c, db, include_evidence=True) for c in claim_objs]
    return ContradictionDetailResponse(**base_kwargs, claims=detailed_claims)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/api/projects/{project_id}/contradictions", response_model=List[ContradictionResponse])
def list_project_contradictions(
    project_id: str,
    rule_code: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _, membership = _get_scoped_project(project_id, current_user.id, db)
    try:
        viewer = resolve_viewer_profile(current_user.id, current_user.name, membership.role, view_as)
    except ClearanceError as exc:
        raise HTTPException(exc.status_code, str(exc))
    q = db.query(Contradiction).filter(Contradiction.project_id == project_id)
    if rule_code:
        q = q.filter(Contradiction.rule_code == rule_code)
    if status:
        q = q.filter(Contradiction.status == status)
    if severity:
        q = q.filter(Contradiction.severity == severity)

    rows = [c for c in q.all() if can_view_contradiction(viewer, c)]
    rows.sort(key=lambda c: (0 if c.status == "open" else 1, SEVERITY_RANK.get(c.severity, 9), c.id))
    effective_role = "incoming" if viewer.profile == "incoming" else ("departing" if viewer.profile == "departing" else membership.role)
    return [_serialize_contradiction(c, effective_role, db, include_claims=False) for c in rows]


@router.get("/api/contradictions/{contradiction_id}", response_model=ContradictionDetailResponse)
def get_contradiction_detail(
    contradiction_id: str,
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ctr = db.get(Contradiction, contradiction_id)
    if not ctr:
        raise HTTPException(status_code=404, detail="Contradiction not found.")
    _, membership = _get_scoped_project(ctr.project_id, current_user.id, db)
    try:
        viewer = resolve_viewer_profile(current_user.id, current_user.name, membership.role, view_as)
    except ClearanceError as exc:
        raise HTTPException(exc.status_code, str(exc))
    if not can_view_contradiction(viewer, ctr):
        raise HTTPException(status_code=404, detail="Contradiction not found.")
    effective_role = "incoming" if viewer.profile == "incoming" else ("departing" if viewer.profile == "departing" else membership.role)
    return _serialize_contradiction(ctr, effective_role, db, include_claims=True)


@router.post("/api/contradictions/{contradiction_id}/resolve", response_model=ContradictionDetailResponse)
def resolve_contradiction(
    contradiction_id: str,
    body: ResolveContradictionRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually mark a contradiction as resolved with a required note.

    Does NOT silently flip involved claims to 'verified'.
    """
    ctr = db.get(Contradiction, contradiction_id)
    if not ctr:
        raise HTTPException(status_code=404, detail="Contradiction not found.")
    _, membership = _get_scoped_project(ctr.project_id, current_user.id, db)
    if membership.role in HIDDEN_ROLES and ctr.clearance_level == "restricted":
        raise HTTPException(status_code=404, detail="Contradiction not found.")
    if membership.role != "admin":
        raise HTTPException(status_code=403, detail="Only the team lead (admin) can resolve contradictions.")

    note = (body.note or "").strip()
    if not note:
        raise HTTPException(status_code=400, detail="A resolution note is required to resolve a contradiction.")

    ctr.status = "resolved"
    ctr.resolved_by = current_user.id
    ctr.resolved_at = datetime.now(timezone.utc)
    ctr.resolution_note = note
    db.commit()
    db.refresh(ctr)
    return _serialize_contradiction(ctr, membership.role, db, include_claims=True)
