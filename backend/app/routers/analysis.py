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
)

router = APIRouter(tags=["Analysis & Ledger"])


# ── Schemas ───────────────────────────────────────────────────────────────────

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
    source_id: str
    source_filename: str
    source_type: str
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


class ClaimReviewRequest(BaseModel):
    action: str  # approve | edit | reject
    new_text: Optional[str] = None


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


def _origin_label(clm: Claim) -> str:
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


def _serialize_claim(clm: Claim, db: Session, include_evidence: bool = False) -> ClaimResponse | ClaimDetailResponse:
    attrs = {}
    if clm.attrs_json:
        try:
            attrs = json.loads(clm.attrs_json)
        except json.JSONDecodeError:
            attrs = {}

    ev_rows = db.query(ClaimEvidence).filter(ClaimEvidence.claim_id == clm.id).all()
    primary_source_id = None
    primary_source_name = None
    primary_locator = None

    if ev_rows:
        first_ev = ev_rows[0]
        primary_source_id = first_ev.source_id
        src = db.get(Source, first_ev.source_id)
        primary_source_name = src.filename if src else first_ev.source_id
        if first_ev.chunk_id:
            ch = db.get(Chunk, first_ev.chunk_id)
            primary_locator = ch.locator if ch else None

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
    )

    if not include_evidence:
        return ClaimResponse(**base_kwargs)

    evidence_items: List[EvidenceItemResponse] = []
    for ev in ev_rows:
        src = db.get(Source, ev.source_id)
        ch = db.get(Chunk, ev.chunk_id) if ev.chunk_id else None
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
                source_id=ev.source_id,
                source_filename=src.filename if src else ev.source_id,
                source_type=src.type if src else "unknown",
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


# ── Analysis Run Endpoints ────────────────────────────────────────────────────

@router.post("/api/projects/{project_id}/analyze", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED)
def start_project_analysis(
    project_id: str,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start an analysis run on the project's parsed sources."""
    project, _ = _get_scoped_project(project_id, current_user.id, db)
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


# ── Timeline Endpoints ────────────────────────────────────────────────────────

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


# ── Modules Endpoints ─────────────────────────────────────────────────────────

def _list_project_modules(project_id: str, role: str, db: Session) -> List[ModuleSummaryResponse]:
    q = db.query(Claim).filter(Claim.project_id == project_id)
    if role in HIDDEN_ROLES:
        q = q.filter(Claim.clearance_level != "restricted")
    claims = q.all()

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
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _, membership = _get_scoped_project(project_id, current_user.id, db)
    return _list_project_modules(project_id, membership.role, db)


@router.get("/api/modules", response_model=List[ModuleSummaryResponse])
def get_modules_query(
    project_id: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _, membership = _get_scoped_project(project_id, current_user.id, db)
    return _list_project_modules(project_id, membership.role, db)


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
    return _list_project_modules(project_id, membership.role, db)


# ── Claims & Evidence Ledger Endpoints ────────────────────────────────────────

def _query_project_claims(
    project_id: str,
    role: str,
    db: Session,
    claim_type: Optional[str] = None,
    module: Optional[str] = None,
    verification_status: Optional[str] = None,
    owner: Optional[str] = None,
    review_status: Optional[str] = None,
    q: Optional[str] = None,
) -> List[ClaimResponse]:
    query = db.query(Claim).filter(Claim.project_id == project_id)
    if role in HIDDEN_ROLES:
        query = query.filter(Claim.clearance_level != "restricted")
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
    return [_serialize_claim(c, db, include_evidence=False) for c in rows]


@router.get("/api/projects/{project_id}/claims", response_model=List[ClaimResponse])
def list_project_claims(
    project_id: str,
    type: Optional[str] = Query(default=None),
    module: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    owner: Optional[str] = Query(default=None),
    review_status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _, membership = _get_scoped_project(project_id, current_user.id, db)
    return _query_project_claims(
        project_id, membership.role, db,
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
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _, membership = _get_scoped_project(project_id, current_user.id, db)
    return _query_project_claims(
        project_id, membership.role, db,
        claim_type=type, module=module, verification_status=status,
        owner=owner, review_status=review_status, q=q,
    )


@router.get("/api/claims/{claim_id}", response_model=ClaimDetailResponse)
def get_claim_detail(
    claim_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return claim detail with evidence excerpts and full surrounding chunk text for drawer."""
    clm = db.get(Claim, claim_id)
    if not clm:
        raise HTTPException(status_code=404, detail="Claim not found.")
    _, membership = _get_scoped_project(clm.project_id, current_user.id, db)
    if membership.role in HIDDEN_ROLES and clm.clearance_level == "restricted":
        raise HTTPException(status_code=404, detail="Claim not found.")
    return _serialize_claim(clm, db, include_evidence=True)


@router.patch("/api/claims/{claim_id}/review", response_model=ClaimDetailResponse)
def review_claim(
    claim_id: str,
    body: ClaimReviewRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record a human review action (approve / edit / reject) on a claim."""
    clm = db.get(Claim, claim_id)
    if not clm:
        raise HTTPException(status_code=404, detail="Claim not found.")
    _, membership = _get_scoped_project(clm.project_id, current_user.id, db)
    if membership.role in HIDDEN_ROLES and clm.clearance_level == "restricted":
        raise HTTPException(status_code=404, detail="Claim not found.")

    action_map = {"approve": "approved", "edit": "edited", "reject": "rejected"}
    if body.action not in action_map:
        raise HTTPException(status_code=400, detail="Invalid review action. Use approve, edit, or reject.")

    old_text = clm.text
    if body.action == "edit":
        if not body.new_text or not body.new_text.strip():
            raise HTTPException(status_code=400, detail="new_text is required when editing a claim.")
        clm.text = body.new_text.strip()

    clm.review_status = action_map[body.action]
    db.add(
        ReviewEvent(
            claim_id=clm.id,
            reviewer_id=current_user.id,
            action=body.action,
            old_text=old_text,
            new_text=clm.text,
        )
    )
    db.commit()
    db.refresh(clm)
    return _serialize_claim(clm, db, include_evidence=True)


@router.get("/api/projects/{project_id}/ledger/validation")
def get_ledger_validation(
    project_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Validate every claim's evidence citations against stored chunks and return the report."""
    _, membership = _get_scoped_project(project_id, current_user.id, db)
    return validate_project_citations(db, project_id, role=membership.role, enforce=True)
