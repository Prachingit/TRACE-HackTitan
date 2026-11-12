"""Projects, members, sources, and summary router."""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.models import (
    Claim,
    Contradiction,
    Membership,
    Project,
    Source,
    User,
    Workspace,
)
from app.schemas import (
    MemberResponse,
    ProjectResponse,
    ProjectSummaryResponse,
    SourceResponse,
)

router = APIRouter(prefix="/api/projects", tags=["Projects"])


@router.get("", response_model=List[ProjectResponse])
def list_projects(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve projects accessible within the current user's workspace."""
    projects = (
        db.query(Project)
        .filter(Project.workspace_id == current_user.workspace_id)
        .all()
    )
    if not projects:
        # Fallback to all projects if user workspace has no projects yet
        projects = db.query(Project).all()
    return [ProjectResponse.model_validate(p) for p in projects]


@router.get("/{id}", response_model=ProjectResponse)
def get_project(
    id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve details for a specific project."""
    project = db.query(Project).filter(Project.id == id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{id}' not found.",
        )
    return ProjectResponse.model_validate(project)


@router.get("/{id}/members", response_model=List[MemberResponse])
def get_project_members(
    id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve team members and their designated roles for a project."""
    project = db.query(Project).filter(Project.id == id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{id}' not found.",
        )

    # Query members belonging to the project's workspace
    memberships = (
        db.query(Membership)
        .filter(Membership.workspace_id == project.workspace_id)
        .all()
    )

    results = []
    for m in memberships:
        user = m.user or db.query(User).filter(User.id == m.user_id).first()
        if user:
            results.append(
                MemberResponse(
                    user_id=user.id,
                    name=user.name,
                    email=user.email,
                    role=m.role,
                )
            )
    return results


@router.get("/{id}/sources", response_model=List[SourceResponse])
def get_project_sources(
    id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve registered sources for a project.
    
    CLEARANCE ENGINE RULE:
    Restricted sources must NOT appear in /sources for 'incoming' and 'departing' roles.
    Only 'admin' (and team members with clearance) can view restricted files.
    """
    project = db.query(Project).filter(Project.id == id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{id}' not found.",
        )

    query = db.query(Source).filter(Source.project_id == id)

    # Filter out restricted clearance for incoming and departing roles
    if current_user.role in ["incoming", "departing"]:
        query = query.filter(Source.clearance_level != "restricted")

    sources = query.order_by(Source.uploaded_at.desc(), Source.id.asc()).all()
    return [SourceResponse.model_validate(s) for s in sources]


@router.get("/{id}/summary", response_model=ProjectSummaryResponse)
def get_project_summary(
    id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve aggregate project stats computed strictly from database rows."""
    project = db.query(Project).filter(Project.id == id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{id}' not found.",
        )

    # 1. Source counts (total and by type)
    source_query = db.query(Source).filter(Source.project_id == id)
    # Check role clearance for summary source counts or full project tally
    total_sources = source_query.count()

    type_counts = (
        db.query(Source.type, func.count(Source.id))
        .filter(Source.project_id == id)
        .group_by(Source.type)
        .all()
    )
    sources_by_type = {t: count for t, count in type_counts}

    # 2. Member count
    member_count = (
        db.query(Membership)
        .filter(Membership.workspace_id == project.workspace_id)
        .count()
    )

    # 3. Claim count (0 before extraction phases)
    claim_count = db.query(Claim).filter(Claim.project_id == id).count()

    # 4. Open contradiction count (0 before contradiction detection phases)
    open_contradiction_count = (
        db.query(Contradiction)
        .filter(Contradiction.project_id == id, Contradiction.status == "open")
        .count()
    )

    return ProjectSummaryResponse(
        project_id=project.id,
        project_name=project.name,
        is_synthetic=project.is_synthetic,
        source_count=total_sources,
        sources_by_type=sources_by_type,
        member_count=member_count,
        claim_count=claim_count,
        open_contradiction_count=open_contradiction_count,
    )
