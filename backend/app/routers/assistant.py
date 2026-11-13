"""Phase 7 router: Secondary 'Ask project knowledge' assistant."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.engine.assistant import ask_project_knowledge
from app.engine.clearance import ClearanceError, resolve_viewer_profile
from app.models import Membership, Project

router = APIRouter(tags=["Assistant"])


class AskRequest(BaseModel):
    question: str


@router.post("/api/projects/{project_id}/ask")
def ask_project(
    project_id: str,
    body: AskRequest,
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found.")
    membership = (
        db.query(Membership)
        .filter(Membership.workspace_id == project.workspace_id, Membership.user_id == current_user.id)
        .first()
    )
    if not membership:
        raise HTTPException(404, "Project not found.")
    try:
        viewer = resolve_viewer_profile(current_user.id, current_user.name, membership.role, view_as)
    except ClearanceError as exc:
        raise HTTPException(exc.status_code, str(exc))

    return ask_project_knowledge(db, project_id, viewer, body.question)
