"""Phase 3 & 4 router: analysis runs, timeline, modules, claims, evidence drawer & ledger validation."""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.engine.clearance import (
    ClearanceError,
    ViewerContext,
    can_view_claim,
    filter_claims,
    filter_evidence_for_viewer,
    override_claim_clearance,
    resolve_viewer_profile,
)
from app.engine.pipeline import create_run_record, run_analysis_background_job
from app.engine.timeline import build_timeline
from app.engine.types import HIDDEN_ROLES, module_name
from app.engine.validation import validate_project_citations
from app.models import (
    Chunk,
    Claim,
    ClaimEvidence,
    Membership,
    ModuleAlias,
    Project,
    ReviewEvent,
    Run,
    Source,
    User,
)

router = APIRouter(tags=["Analysis & Ledger"])


# â”€â”€ Schemas â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class RunStageResponse(BaseModel):
    ordinal: int
    key: str
    label: str
    status: str
    count: Optional[int] = None
    detail: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class RunResponse(BaseModel):
    id: str
    project_id: str
    status: str
    llm_enabled: bool
    error_message: Optional[str] = None
    summary: Dict[str, Any] = {}
    started_at: datetime
    finished_at: Optional[datetime] = None
    stages: List[RunStageResponse] = []


class EvidenceItemResponse(BaseModel):
    id: str
    evidence_type: str = "document"  # document | interview_answer
    source_id: Optional[str] = None
    source_filename: Optional[str] = None
    source_type: Optional[str] = None
    author_id: Optional[str] = None
    question_id: Optional[str] = None
    label: Optional[str] = None
    chunk_id: Optional[str] = None
    locator: Optional[str] = None
    author: Optional[str] = None
    timestamp: Optional[datetime] = None
    excerpt: str
    chunk_text: Optional[str] = None
    highlight_start: Optional[int] = None
    highlight_end: Optional[int] = None


class ClaimResponse(BaseModel):
    id: str
    project_id: str
    claim_type: str
    title: str
    text: str
    module: str
    owner_id: Optional[str] = None
    owner_name: Optional[str] = None
    author: Optional[str] = None
    verification_status: str
    review_status: str
    extractor: str
    origin_label: str  # human-reviewed | ai-extracted | rule-extracted
    confidence: Optional[float] = None
    clearance_level: str
    event_time: Optional[datetime] = None
    created_at: datetime
    task_key: Optional[str] = None
    attrs: Dict[str, Any] = {}
    primary_source_id: Optional[str] = None
    primary_source_name: Optional[str] = None
    primary_locator: Optional[str] = None
    evidence_count: int = 0
    interview_answer_count: int = 0
    original_text: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_by_name: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None
    version: int = 0


class ClaimDetailResponse(ClaimResponse):
    evidence: List[EvidenceItemResponse] = []


class ModuleSummaryResponse(BaseModel):
    name: str
    claim_count: int
    task_count: int
    decision_count: int
    contribution_count: int
    blocker_count: int
    owners: List[str] = []


class ModuleRenameRequest(BaseModel):
    from_module: str
    to_module: str


# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


def _origin_label(clm: Claim) -> str:
    if clm.extractor == "human":
        return "human-authored"
    if clm.review_status in ("approved", "edited", "rejected"):
        return "human-reviewed"
    if clm.extractor == "llm":
        return "ai-extracted"
    return "rule-extracted"


def _serialize_run(run: Run) -> RunResponse:
    summary = {}
    if run.summary_json:
        try:
            summary = json.loads(run.summary_json)
        except json.JSONDecodeError:
            summary = {}
    return RunResponse(
        id=run.id,
        project_id=run.project_id,
        status=run.status,
        llm_enabled=run.llm_enabled,
        error_message=run.error_message,
        summary=summary,
        started_at=run.started_at,
        finished_at=run.finished_at,
        stages=[RunStageResponse.model_validate(s) for s in run.stages],
    )


def _serialize_claim(
    clm: Claim,
    db: Session,
    include_evidence: bool = False,
    viewer: Optional[ViewerContext] = None,
) -> ClaimResponse | ClaimDetailResponse:
    attrs = {}
    if clm.attrs_json:
        try:
            attrs = json.loads(clm.attrs_json)
        except json.JSONDecodeError:
            attrs = {}

    ev_rows = (
        db.query(ClaimEvidence)
        .filter(ClaimEvidence.claim_id == clm.id)
        .order_by(ClaimEvidence.timestamp.asc().nullsfirst(), ClaimEvidence.id.asc())
        .all()
    )
    if viewer is not None:
        ev_rows = filter_evidence_for_viewer(db, viewer, ev_rows)
    primary_source_id = None
    primary_source_name = None
    primary_locator = None

    doc_rows = [e for e in ev_rows if e.evidence_type != "interview_answer" and e.source_id]
    if doc_rows:
        first_ev = doc_rows[0]
        primary_source_id = first_ev.source_id
        src = db.get(Source, first_ev.source_id)
        primary_source_name = src.filename if src else first_ev.source_id
        if first_ev.chunk_id:
            ch = db.get(Chunk, first_ev.chunk_id)
            primary_locator = ch.locator if ch else None

    reviewer = db.get(User, clm.reviewed_by) if clm.reviewed_by else None
    last_ev = (
        db.query(ReviewEvent.version)
        .filter(ReviewEvent.claim_id == clm.id)
        .order_by(ReviewEvent.version.desc())
        .first()
    )

    base_kwargs = dict(
        id=clm.id,
        project_id=clm.project_id,
        claim_type=clm.claim_type,
        title=clm.title or clm.text[:100],
        text=clm.text,
        module=clm.module,
        owner_id=clm.owner_id,
        owner_name=clm.owner_name,
        author=clm.author,
        verification_status=clm.verification_status,
        review_status=clm.review_status,
        extractor=clm.extractor or "rule",
        origin_label=_origin_label(clm),
        confidence=clm.confidence,
        clearance_level=clm.clearance_level,
        event_time=clm.event_time,
        created_at=clm.created_at,
        task_key=clm.task_key,
        attrs=attrs,
        primary_source_id=primary_source_id,
        primary_source_name=primary_source_name,
        primary_locator=primary_locator,
        evidence_count=len(ev_rows),
        interview_answer_count=len([e for e in ev_rows if e.evidence_type == "interview_answer"]),
        original_text=clm.original_text,
        reviewed_by=clm.reviewed_by,
        reviewed_by_name=reviewer.name if reviewer else None,
        reviewed_at=clm.reviewed_at,
        review_note=clm.review_note,
        version=(last_ev[0] if last_ev and last_ev[0] else 0),
    )

    if not include_evidence:
        return ClaimResponse(**base_kwargs)

    evidence_items: List[EvidenceItemResponse] = []
    for ev in ev_rows:
        src = db.get(Source, ev.source_id) if ev.source_id else None
        ch = db.get(Chunk, ev.chunk_id) if ev.chunk_id else None
        is_answer = ev.evidence_type == "interview_answer"
        label = None
        if is_answer:
            when = ev.timestamp.strftime("%Y-%m-%d") if ev.timestamp else "unknown date"
            label = f"Interview answer, by {ev.author or 'unknown'}, {when}"
        chunk_text = ch.text if ch else None
        h_start: Optional[int] = None
        h_end: Optional[int] = None
        if chunk_text and ev.excerpt:
            idx = chunk_text.find(ev.excerpt)
            if idx >= 0:
                h_start = idx
                h_end = idx + len(ev.excerpt)

        evidence_items.append(
            EvidenceItemResponse(
                id=ev.id,
                evidence_type=ev.evidence_type or "document",
                source_id=ev.source_id,
                source_filename=(src.filename if src else ev.source_id) if not is_answer else None,
                source_type=(src.type if src else "unknown") if not is_answer else "interview_answer",
                author_id=ev.author_id,
                question_id=ev.question_id,
                label=label,
                chunk_id=ev.chunk_id,
                locator=ch.locator if ch else None,
                author=ev.author or (ch.author if ch else None),
                timestamp=ev.timestamp or (ch.timestamp if ch else None),
                excerpt=ev.excerpt,
                chunk_text=chunk_text,
                highlight_start=h_start,
                highlight_end=h_end,
            )
        )

    return ClaimDetailResponse(**base_kwargs, evidence=evidence_items)


# â”€â”€ Analysis Run Endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/api/projects/{project_id}/analyze", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED)
def start_project_analysis(
    project_id: str,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start an analysis run on the project's parsed sources."""
    project, membership = _get_scoped_project(project_id, current_user.id, db)
    if membership.role not in ("admin", "team_member"):
        raise HTTPException(403, "Only admins and team members can run analysis.")
    run = create_run_record(db, project_id=project.id, user_id=current_user.id)
    background_tasks.add_task(run_analysis_background_job, run.id)
    db.refresh(run)
    return _serialize_run(run)


@router.get("/api/projects/{project_id}/runs/latest", response_model=Optional[RunResponse])
def get_latest_run(
    project_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the most recent analysis Run and its stages, or null if never analysed."""
    _get_scoped_project(project_id, current_user.id, db)
    run = (
        db.query(Run)
        .filter(Run.project_id == project_id)
        .order_by(Run.started_at.desc(), Run.id.desc())
        .first()
    )
    if not run:
        return None
    return _serialize_run(run)


# â”€â”€ Timeline Endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/api/projects/{project_id}/timeline")
def get_project_timeline(
    project_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _, membership = _get_scoped_project(project_id, current_user.id, db)
    return build_timeline(db, project_id, role=membership.role)


@router.get("/api/timeline")
def get_timeline_query(
    project_id: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _, membership = _get_scoped_project(project_id, current_user.id, db)
    return build_timeline(db, project_id, role=membership.role)


# â”€â”€ Modules Endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _resolve_viewer(user: CurrentUser, role: str, view_as: Optional[str]) -> ViewerContext:
    try:
        return resolve_viewer_profile(user.id, user.name, role, view_as)
    except ClearanceError as exc:
        raise HTTPException(exc.status_code, str(exc))


def _list_project_modules(project_id: str, viewer: ViewerContext, db: Session) -> List[ModuleSummaryResponse]:
    all_claims = db.query(Claim).filter(Claim.project_id == project_id).all()
    claims = filter_claims(db, viewer, all_claims)

    by_mod: Dict[str, List[Claim]] = {}
    for c in claims:
        by_mod.setdefault(c.module or "general", []).append(c)

    out: List[ModuleSummaryResponse] = []
    for mod, mclaims in sorted(by_mod.items()):
        owners = sorted({c.owner_name for c in mclaims if c.owner_name})
        out.append(
            ModuleSummaryResponse(
                name=mod,
                claim_count=len(mclaims),
                task_count=sum(1 for c in mclaims if c.claim_type == "task_status"),
                decision_count=sum(1 for c in mclaims if c.claim_type == "decision"),
                contribution_count=sum(1 for c in mclaims if c.claim_type == "contribution"),
                blocker_count=sum(1 for c in mclaims if c.claim_type == "blocker"),
                owners=owners,
            )
        )
    return out


@router.get("/api/projects/{project_id}/modules", response_model=List[ModuleSummaryResponse])
def get_project_modules(
    project_id: str,
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _, membership = _get_scoped_project(project_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, membership.role, view_as)
    return _list_project_modules(project_id, viewer, db)


@router.get("/api/modules", response_model=List[ModuleSummaryResponse])
def get_modules_query(
    project_id: str = Query(...),
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _, membership = _get_scoped_project(project_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, membership.role, view_as)
    return _list_project_modules(project_id, viewer, db)


@router.post("/api/projects/{project_id}/modules/rename", response_model=List[ModuleSummaryResponse])
def rename_or_merge_module(
    project_id: str,
    body: ModuleRenameRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Rename or merge a module across existing claims and persist a ModuleAlias for future runs."""
    _, membership = _get_scoped_project(project_id, current_user.id, db)
    src_mod = module_name(body.from_module)
    dst_mod = module_name(body.to_module)
    if not src_mod or not dst_mod:
        raise HTTPException(status_code=400, detail="Both source and target module names are required.")

    existing_alias = (
        db.query(ModuleAlias)
        .filter(ModuleAlias.project_id == project_id, ModuleAlias.alias == src_mod)
        .first()
    )
    if existing_alias:
        existing_alias.target = dst_mod
    else:
        db.add(ModuleAlias(project_id=project_id, alias=src_mod, target=dst_mod))

    # Update transitive aliases pointing to src_mod
    for a in db.query(ModuleAlias).filter(ModuleAlias.project_id == project_id, ModuleAlias.target == src_mod).all():
        a.target = dst_mod

    # Update existing claims in place
    for c in db.query(Claim).filter(Claim.project_id == project_id, Claim.module == src_mod).all():
        c.module = dst_mod

    db.commit()
    viewer = _resolve_viewer(current_user, membership.role, None)
    return _list_project_modules(project_id, viewer, db)


# ── Claims & Evidence Ledger Endpoints ────────────────────────────────────────

def _query_project_claims(
    project_id: str,
    viewer: ViewerContext,
    db: Session,
    claim_type: Optional[str] = None,
    module: Optional[str] = None,
    verification_status: Optional[str] = None,
    owner: Optional[str] = None,
    review_status: Optional[str] = None,
    q: Optional[str] = None,
) -> List[ClaimResponse]:
    query = db.query(Claim).filter(Claim.project_id == project_id)
    if claim_type:
        query = query.filter(Claim.claim_type == claim_type)
    if module:
        query = query.filter(Claim.module == module)
    if verification_status:
        query = query.filter(Claim.verification_status == verification_status)
    if owner:
        query = query.filter(Claim.owner_name.ilike(f"%{owner.strip()}%"))
    if review_status:
        query = query.filter(Claim.review_status == review_status)
    if q and q.strip():
        pat = f"%{q.strip()}%"
        query = query.filter(or_(Claim.title.ilike(pat), Claim.text.ilike(pat), Claim.module.ilike(pat)))

    rows = query.order_by(Claim.event_time.desc().nullslast(), Claim.id.asc()).all()
    visible_rows = filter_claims(db, viewer, rows)
    return [_serialize_claim(c, db, include_evidence=False, viewer=viewer) for c in visible_rows]


@router.get("/api/projects/{project_id}/claims", response_model=List[ClaimResponse])
def list_project_claims(
    project_id: str,
    type: Optional[str] = Query(default=None),
    module: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    owner: Optional[str] = Query(default=None),
    review_status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _, membership = _get_scoped_project(project_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, membership.role, view_as)
    return _query_project_claims(
        project_id, viewer, db,
        claim_type=type, module=module, verification_status=status,
        owner=owner, review_status=review_status, q=q,
    )


@router.get("/api/claims", response_model=List[ClaimResponse])
def list_claims_query(
    project_id: str = Query(...),
    type: Optional[str] = Query(default=None),
    module: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    owner: Optional[str] = Query(default=None),
    review_status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _, membership = _get_scoped_project(project_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, membership.role, view_as)
    return _query_project_claims(
        project_id, viewer, db,
        claim_type=type, module=module, verification_status=status,
        owner=owner, review_status=review_status, q=q,
    )


@router.get("/api/claims/{claim_id}", response_model=ClaimDetailResponse)
def get_claim_detail(
    claim_id: str,
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return claim detail with evidence excerpts and full surrounding chunk text for drawer."""
    clm = db.get(Claim, claim_id)
    if not clm:
        raise HTTPException(status_code=404, detail="Claim not found.")
    _, membership = _get_scoped_project(clm.project_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, membership.role, view_as)
    if not can_view_claim(db, viewer, clm):
        raise HTTPException(status_code=404, detail="Claim not found.")
    return _serialize_claim(clm, db, include_evidence=True, viewer=viewer)


class ClearanceOverrideRequest(BaseModel):
    clearance_level: str
    reason: str


@router.post("/api/claims/{claim_id}/clearance", response_model=ClaimResponse)
def set_claim_clearance(
    claim_id: str,
    body: ClearanceOverrideRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin-only: override a claim's effective clearance level with a recorded reason."""
    clm = db.get(Claim, claim_id)
    if not clm:
        raise HTTPException(status_code=404, detail="Claim not found.")
    _, membership = _get_scoped_project(clm.project_id, current_user.id, db)
    if membership.role != "admin":
        raise HTTPException(status_code=403, detail="Only workspace admins can override claim clearance.")
    admin_user = db.get(User, current_user.id)
    try:
        updated = override_claim_clearance(db, clm, admin_user, body.clearance_level, body.reason)
    except ClearanceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return _serialize_claim(updated, db, include_evidence=False)


@router.get("/api/projects/{project_id}/ledger/validation")
def get_ledger_validation(
    project_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Validate every claim's evidence citations against stored chunks and return the report."""
    _, membership = _get_scoped_project(project_id, current_user.id, db)
    return validate_project_citations(db, project_id, role=membership.role, enforce=True)
