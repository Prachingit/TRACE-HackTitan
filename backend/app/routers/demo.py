"""Demo seed and current user endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.schemas import CurrentUserResponse, DemoLoadResponse
from app.services.seed import seed_atlas

router = APIRouter(prefix="/api", tags=["Demo & Auth"])


@router.post("/demo/load", response_model=DemoLoadResponse)
def load_demo_workspace(db: Session = Depends(get_db)):
    """Seed or re-seed Atlas Workspace into the database (idempotent)."""
    result = seed_atlas(db=db)
    return DemoLoadResponse(
        project_id=result["project_id"],
        workspace_id=result["workspace_id"],
        sources_registered=result["sources_registered"],
    )


@router.get("/me", response_model=CurrentUserResponse)
def get_current_user_profile(
    current_user: CurrentUser = Depends(get_current_user),
):
    """Retrieve identity and workspace role of the active demo user."""
    return CurrentUserResponse(
        id=current_user.id,
        name=current_user.name,
        email=current_user.email,
        role=current_user.role,
        workspace_id=current_user.workspace_id,
        workspace_name=current_user.workspace_name,
    )
