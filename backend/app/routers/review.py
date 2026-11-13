"""Phase 6 router: review workbench (accept / edit / reject / flag), queue, bulk accept, append-only history."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.engine.review import (
    OPEN_REVIEW_STATUSES,
    ReviewError,
    accept_blockers,
    apply_review,
    open_contradictions_for_claim,
    serialize_history,
)
from app.engine.types import HIDDEN_ROLES
from app.models import Claim, Membership, Project
from app.routers.analysis import ClaimDetailResponse, ClaimResponse, _get_scoped_project, _serialize_claim

router = APIRouter(tags=["Review"])

VERIFICATION_RANK = {"conflicting": 0, "missing": 1, "inferred": 2, "verified": 3}
REVIEW_RANK = {"needs_review": 0, "unreviewed": 1, "edited": 2}


# ── Schemas ───────────────────────────────────────────────────────────────────

class ReviewRequest(BaseModel):
    action: str  # accept | edit | reject | flag
    text: Optional[str] = None
    note: Optional[str] = None
    resolve_contradictions: bool = False


class ReviewActionResponse(ClaimDetailResponse):
    resolved_contradiction_ids: List[str] = []


class QueueItem(ClaimResponse):
    open_contradiction_ids: List[str] = []
    accept_blockers: List[str] = []
    can_accept: bool = False


class QueueResponse(BaseModel):
    total: int
    counts_by_verification: Dict[str, int]
    items: List[QueueItem]


class BulkRequest(BaseModel):
    claim_ids: List[str]
    action: str = "accept"
    note: Optional[str] = None


class BulkResponse(BaseModel):
    accepted: List[str]
    skipped: List[Dict[str, str]]


class HistoryEvent(BaseModel):
    id: str
    claim_id: str
    version: int
    action: str
    reviewer_id: str
    reviewer_name: str
    old_text: Optional[str] = None
    new_text: Optional[str] = None
    note: Optional[str] = None
    timestamp: Any
    resulting_review_status: Optional[str] = None
    resulting_verification_status: Optional[str] = None
    diff: List[Dict[str, str]] = []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_claim(db: Session, claim_id: str, user: CurrentUser) -> tuple[Claim, Membership]:
    clm = db.get(Claim, claim_id)
    if not clm:
        raise HTTPException(status_code=404, detail="Claim not found.")
    _, membership = _get_scoped_project(clm.project_id, user.id, db)
    if membership.role in HIDDEN_ROLES and clm.clearance_level == "restricted":
        raise HTTPException(status_code=404, detail="Claim not found.")
    return clm, membership


def _open_ctr_ids(db: Session, claim: Claim, role: str) -> List[str]:
    ctrs = open_contradictions_for_claim(db, claim.id)
    if role != "admin":
        ctrs = [c for c in ctrs if c.clearance_level != "restricted"]
    return [c.id for c in ctrs]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/api/claims/{claim_id}/review", response_model=ReviewActionResponse)
def review_claim(
    claim_id: str,
    body: ReviewRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Apply a human review action. Accept, edit and reject are admin-only; flag is admin or team member."""
    clm, membership = _load_claim(db, claim_id, current_user)
    action = (body.action or "").strip().lower()
    role = membership.role
    if action == "flag":
        allowed = role in ("admin", "team_member")
    else:
        allowed = role == "admin"
    if not allowed:
        raise HTTPException(status_code=403, detail="You do not have permission to perform this review action.")
    if role != "admin" and clm.clearance_level == "restricted":
        raise HTTPException(status_code=404, detail="Claim not found.")

    try:
        result = apply_review(
            db, clm, current_user.user, action, text=body.text, note=body.note,
            resolve_contradictions=body.resolve_contradictions,
        )
        db.commit()
    except ReviewError as e:
        db.rollback()
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    db.refresh(clm)
    detail = _serialize_claim(clm, db, include_evidence=True)
    return ReviewActionResponse(**detail.model_dump(), resolved_contradiction_ids=result.resolved_contradiction_ids)


@router.get("/api/claims/{claim_id}/history", response_model=List[HistoryEvent])
def claim_history(
    claim_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Append-only review history for a claim. Read-only: there is no endpoint that edits or deletes events."""
    clm, _ = _load_claim(db, claim_id, current_user)
    return serialize_history(db, clm.id)


@router.get("/api/projects/{project_id}/review/queue", response_model=QueueResponse)
def review_queue(
    project_id: str,
    scope: str = Query(default="open", pattern="^(open|all)$"),
    module: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Prioritised queue: conflicting first, then missing, inferred, unreviewed."""
    _, membership = _get_scoped_project(project_id, current_user.id, db)
    role = membership.role
    if role not in ("admin", "team_member"):
        raise HTTPException(status_code=403, detail="Only the team lead and team members can use the review workbench.")

    q = db.query(Claim).filter(Claim.project_id == project_id)
    if role != "admin":
        q = q.filter(Claim.clearance_level != "restricted")
    if scope == "open":
        q = q.filter(Claim.review_status.in_(OPEN_REVIEW_STATUSES))
    if module:
        q = q.filter(Claim.module == module)
    rows = q.all()
    rows.sort(
        key=lambda c: (
            VERIFICATION_RANK.get(c.verification_status, 9),
            REVIEW_RANK.get(c.review_status, 5),
            c.module,
            c.id,
        )
    )

    items: List[QueueItem] = []
    counts: Dict[str, int] = {}
    for c in rows:
        base = _serialize_claim(c, db, include_evidence=False)
        reasons = accept_blockers(db, c) if c.review_status not in ("approved",) else []
        items.append(
            QueueItem(
                **base.model_dump(),
                open_contradiction_ids=_open_ctr_ids(db, c, role),
                accept_blockers=reasons,
                can_accept=(role == "admin" and not reasons and c.review_status != "approved"),
            )
        )
        counts[c.verification_status] = counts.get(c.verification_status, 0) + 1
    return QueueResponse(total=len(items), counts_by_verification=counts, items=items)


@router.post("/api/projects/{project_id}/review/bulk", response_model=BulkResponse)
def bulk_review(
    project_id: str,
    body: BulkRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Accept every selected claim that qualifies; report the rest as skipped with reasons."""
    _, membership = _get_scoped_project(project_id, current_user.id, db)
    if membership.role != "admin":
        raise HTTPException(status_code=403, detail="Only the team lead (admin) can accept claims.")
    if (body.action or "").strip().lower() not in ("accept", "approve"):
        raise HTTPException(status_code=400, detail="Bulk review supports the accept action only.")
    if not body.claim_ids:
        raise HTTPException(status_code=400, detail="Select at least one claim.")

    accepted: List[str] = []
    skipped: List[Dict[str, str]] = []
    for cid in dict.fromkeys(body.claim_ids):
        c = db.get(Claim, cid)
        if c is None or c.project_id != project_id:
            skipped.append({"claim_id": cid, "reason": "Claim not found in this project."})
            continue
        if c.review_status == "approved":
            skipped.append({"claim_id": cid, "reason": "Already accepted."})
            continue
        reasons = accept_blockers(db, c)
        if reasons:
            skipped.append({"claim_id": cid, "reason": " ".join(reasons)})
            continue
        apply_review(db, c, current_user.user, "accept", note=body.note)
        accepted.append(cid)
    db.commit()
    return BulkResponse(accepted=accepted, skipped=skipped)
