"""Projects router — full CRUD with workspace-scoped tenant isolation."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.engine.clearance import (
    ClearanceError,
    can_view_contradiction,
    filter_claims,
    filter_sources,
    resolve_viewer_profile,
)
from app.models import (
    Chunk,
    Claim,
    Contradiction,
    InterviewQuestion,
    Membership,
    Project,
    Run,
    Source,
    User,
)
from app.engine.types import HIDDEN_ROLES

router = APIRouter(prefix="/api/projects", tags=["Projects"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    workspace_id: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    team_size: int = 1
    technologies: Optional[str] = None
    start_date: Optional[datetime] = None
    stale_days: int = 28


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    team_size: Optional[int] = None
    technologies: Optional[str] = None
    start_date: Optional[datetime] = None
    stale_days: Optional[int] = None


class ProjectResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    description: Optional[str]
    category: Optional[str]
    team_size: int
    technologies: Optional[str]
    start_date: Optional[datetime]
    is_synthetic: bool
    stale_days: int = 28
    created_at: datetime

    model_config = {"from_attributes": True}


class MemberResponse(BaseModel):
    user_id: str
    name: str
    email: str
    role: str

    model_config = {"from_attributes": True}


class SourceSummary(BaseModel):
    id: str
    type: str
    filename: str
    status: str
    clearance_level: str
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class ProjectSummaryResponse(BaseModel):
    project_id: str
    project_name: str
    is_synthetic: bool
    analysed: bool = False
    source_count: int
    sources_by_type: dict
    member_count: int
    claim_count: int
    claims_by_status: dict = {}
    claims_by_type: dict = {}
    open_contradiction_count: int
    chunk_count: int
    # Phase 6: review and interview progress, all counted from the database
    reviewed_claim_count: int = 0
    claims_needing_review_count: int = 0
    total_question_count: int = 0
    answered_question_count: int = 0
    open_question_count: int = 0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_scoped_project(project_id: str, user_id: str, db: Session) -> tuple[Project, Membership]:
    """Return (Project, Membership) scoped to user's workspace, or 404."""
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found.")
    membership = (
        db.query(Membership)
        .filter(
            Membership.workspace_id == project.workspace_id,
            Membership.user_id == user_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(404, "Project not found.")
    return project, membership


# ── List projects ─────────────────────────────────────────────────────────────

@router.get("", response_model=List[ProjectResponse])
def list_projects(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List projects accessible to the current user (across all their workspaces)."""
    workspace_ids = [
        m.workspace_id
        for m in db.query(Membership).filter(Membership.user_id == current_user.id).all()
    ]
    if not workspace_ids:
        return []
    projects = (
        db.query(Project)
        .filter(Project.workspace_id.in_(workspace_ids))
        .order_by(Project.created_at.desc())
        .all()
    )
    return [ProjectResponse.model_validate(p) for p in projects]


# ── Create project ────────────────────────────────────────────────────────────

@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(
    body: ProjectCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a project inside a workspace. Caller must be an admin of that workspace."""
    membership = (
        db.query(Membership)
        .filter(
            Membership.workspace_id == body.workspace_id,
            Membership.user_id == current_user.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(404, "Workspace not found.")
    if membership.role != "admin":
        raise HTTPException(403, "Only workspace admins can create projects.")

    if not body.name.strip():
        raise HTTPException(400, "Project name cannot be blank.")

    project = Project(
        workspace_id=body.workspace_id,
        name=body.name.strip(),
        description=body.description,
        category=body.category,
        team_size=max(1, body.team_size),
        technologies=body.technologies,
        start_date=body.start_date,
        is_synthetic=False,
        stale_days=max(1, body.stale_days),
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectResponse.model_validate(project)


# ── Get project ───────────────────────────────────────────────────────────────

@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _ = _get_scoped_project(project_id, current_user.id, db)
    return ProjectResponse.model_validate(project)


# ── Update project ────────────────────────────────────────────────────────────

@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: str,
    body: ProjectUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, membership = _get_scoped_project(project_id, current_user.id, db)
    if membership.role != "admin":
        raise HTTPException(403, "Only admins can update projects.")

    if body.name is not None:
        project.name = body.name.strip() or project.name
    if body.description is not None:
        project.description = body.description
    if body.category is not None:
        project.category = body.category
    if body.team_size is not None:
        project.team_size = max(1, body.team_size)
    if body.technologies is not None:
        project.technologies = body.technologies
    if body.start_date is not None:
        project.start_date = body.start_date
    if body.stale_days is not None:
        project.stale_days = max(1, body.stale_days)

    db.commit()
    db.refresh(project)
    return ProjectResponse.model_validate(project)


# ── Delete project ────────────────────────────────────────────────────────────

@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, membership = _get_scoped_project(project_id, current_user.id, db)
    if membership.role != "admin":
        raise HTTPException(403, "Only admins can delete projects.")
    from app.services.demo import DEMO_PROJECT_ID
    if project.id == DEMO_PROJECT_ID:
        raise HTTPException(403, "The synthetic demo project cannot be deleted.")
    db.delete(project)
    db.commit()


# ── Members ───────────────────────────────────────────────────────────────────

@router.get("/{project_id}/members", response_model=List[MemberResponse])
def get_project_members(
    project_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _ = _get_scoped_project(project_id, current_user.id, db)
    memberships = (
        db.query(Membership)
        .filter(Membership.workspace_id == project.workspace_id)
        .all()
    )
    return [
        MemberResponse(
            user_id=m.user_id,
            name=m.user.name if m.user else "Unknown",
            email=m.user.email if m.user else "",
            role=m.role,
        )
        for m in memberships
        if m.user
    ]


# ── Summary ───────────────────────────────────────────────────────────────────

@router.get("/{project_id}/summary", response_model=ProjectSummaryResponse)
def get_project_summary(
    project_id: str,
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, membership = _get_scoped_project(project_id, current_user.id, db)
    try:
        viewer = resolve_viewer_profile(current_user.id, current_user.name, membership.role, view_as)
    except ClearanceError as exc:
        raise HTTPException(exc.status_code, str(exc))

    all_sources = db.query(Source).filter(Source.project_id == project_id).all()
    vis_sources = filter_sources(viewer, all_sources)
    total_sources = len(vis_sources)
    sources_by_type: dict = {}
    for s in vis_sources:
        sources_by_type[s.type] = sources_by_type.get(s.type, 0) + 1

    member_count = (
        db.query(Membership)
        .filter(Membership.workspace_id == project.workspace_id)
        .count()
    )

    all_claims = db.query(Claim).filter(Claim.project_id == project_id).all()
    vis_claims = filter_claims(db, viewer, all_claims)
    claim_count = len(vis_claims)
    claims_by_status: dict = {}
    claims_by_type: dict = {}
    reviewed_claim_count = 0
    claims_needing_review_count = 0
    for c in vis_claims:
        claims_by_status[c.verification_status] = claims_by_status.get(c.verification_status, 0) + 1
        claims_by_type[c.claim_type] = claims_by_type.get(c.claim_type, 0) + 1
        if c.review_status in ("approved", "edited", "rejected"):
            reviewed_claim_count += 1
        if c.review_status in ("unreviewed", "needs_review", "edited"):
            claims_needing_review_count += 1

    all_ctrs = db.query(Contradiction).filter(Contradiction.project_id == project_id, Contradiction.status == "open").all()
    open_contradiction_count = sum(1 for ctr in all_ctrs if can_view_contradiction(viewer, ctr))

    source_ids = [s.id for s in vis_sources]
    chunk_count = (
        db.query(Chunk).filter(Chunk.source_id.in_(source_ids)).count()
        if source_ids else 0
    )

    analysed = (
        db.query(Run)
        .filter(Run.project_id == project_id, Run.status == "completed")
        .first()
        is not None
    )

    qn_q = db.query(InterviewQuestion).filter(InterviewQuestion.project_id == project_id)
    if viewer.profile != "team_lead":
        qn_q = qn_q.filter(InterviewQuestion.clearance_level != "restricted")
    total_question_count = qn_q.count()
    answered_question_count = qn_q.filter(InterviewQuestion.status == "answered").count()
    open_question_count = qn_q.filter(InterviewQuestion.status == "open").count()

    return ProjectSummaryResponse(
        project_id=project.id,
        project_name=project.name,
        is_synthetic=project.is_synthetic,
        analysed=analysed,
        source_count=total_sources,
        sources_by_type=sources_by_type,
        member_count=member_count,
        claim_count=claim_count,
        claims_by_status=claims_by_status,
        claims_by_type=claims_by_type,
        open_contradiction_count=open_contradiction_count,
        chunk_count=chunk_count,
        reviewed_claim_count=reviewed_claim_count,
        claims_needing_review_count=claims_needing_review_count,
        total_question_count=total_question_count,
        answered_question_count=answered_question_count,
        open_question_count=open_question_count,
    )
