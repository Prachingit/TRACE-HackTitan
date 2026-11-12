"""Projects router — full CRUD with workspace-scoped tenant isolation."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.models import (
    Chunk,
    Claim,
    Contradiction,
    Membership,
    Project,
    Source,
    User,
)

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


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    team_size: Optional[int] = None
    technologies: Optional[str] = None
    start_date: Optional[datetime] = None


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
    source_count: int
    sources_by_type: dict
    member_count: int
    claim_count: int
    open_contradiction_count: int
    chunk_count: int


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
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _ = _get_scoped_project(project_id, current_user.id, db)

    total_sources = db.query(Source).filter(Source.project_id == project_id).count()
    type_counts = (
        db.query(Source.type, func.count(Source.id))
        .filter(Source.project_id == project_id)
        .group_by(Source.type)
        .all()
    )
    member_count = (
        db.query(Membership)
        .filter(Membership.workspace_id == project.workspace_id)
        .count()
    )
    claim_count = db.query(Claim).filter(Claim.project_id == project_id).count()
    open_contradiction_count = (
        db.query(Contradiction)
        .filter(Contradiction.project_id == project_id, Contradiction.status == "open")
        .count()
    )
    source_ids = [s.id for s in db.query(Source.id).filter(Source.project_id == project_id)]
    chunk_count = (
        db.query(Chunk).filter(Chunk.source_id.in_(source_ids)).count()
        if source_ids else 0
    )

    return ProjectSummaryResponse(
        project_id=project.id,
        project_name=project.name,
        is_synthetic=project.is_synthetic,
        source_count=total_sources,
        sources_by_type={t: cnt for t, cnt in type_counts},
        member_count=member_count,
        claim_count=claim_count,
        open_contradiction_count=open_contradiction_count,
        chunk_count=chunk_count,
    )
