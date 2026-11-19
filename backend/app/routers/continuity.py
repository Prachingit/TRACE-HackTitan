"""Round 3, Improvement C router: Continuity Graph & Account/Service Custody Checklist."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.engine.clearance import ClearanceError, ViewerContext, resolve_viewer_profile
from app.engine.continuity import (
    SecretRejectedError,
    analyze_graph_risks,
    confirm_custody_item,
    create_custody_item,
    get_filtered_graph,
    list_custody_for_viewer,
    rebuild_continuity_graph,
    serialize_custody,
    update_custody_item,
    what_if_leaves,
)
from app.models import CustodyEvent, CustodyItem, Membership, Project, User

router = APIRouter(tags=["Continuity"])


def _scoped_project(project_id: str, user_id: str, db: Session) -> tuple[Project, Membership]:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found.")
    mem = (
        db.query(Membership)
        .filter(Membership.workspace_id == project.workspace_id, Membership.user_id == user_id)
        .first()
    )
    if not mem:
        raise HTTPException(404, "Project not found.")
    return project, mem


def _scoped_custody(custody_id: str, user_id: str, db: Session) -> tuple[CustodyItem, Membership]:
    item = db.get(CustodyItem, custody_id)
    if not item:
        raise HTTPException(404, "Custody item not found.")
    _, mem = _scoped_project(item.project_id, user_id, db)
    return item, mem


def _resolve_viewer(user: CurrentUser, role: str, view_as: Optional[str]) -> ViewerContext:
    try:
        return resolve_viewer_profile(user.id, user.name, role, view_as)
    except ClearanceError as exc:
        raise HTTPException(exc.status_code, str(exc))


@router.post("/api/projects/{project_id}/graph/rebuild")
def rebuild_project_graph(
    project_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Idempotently rebuild the evidence-backed Continuity Graph from current claims."""
    _, mem = _scoped_project(project_id, current_user.id, db)
    if mem.role not in ("admin", "team_member"):
        raise HTTPException(403, "Only team leads and team members can rebuild the continuity graph.")
    return rebuild_continuity_graph(db, project_id)


@router.get("/api/projects/{project_id}/graph")
def get_project_graph(
    project_id: str,
    node_type: Optional[str] = Query(default=None),
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return clearance-filtered Continuity Graph nodes and evidence-backed edges."""
    _, mem = _scoped_project(project_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, mem.role, view_as)
    return get_filtered_graph(db, project_id, viewer, node_type=node_type)


@router.get("/api/projects/{project_id}/graph/risks")
def get_project_graph_risks(
    project_id: str,
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return single points of failure, unowned modules, undocumented modules, and circular dependencies."""
    _, mem = _scoped_project(project_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, mem.role, view_as)
    return analyze_graph_risks(db, project_id, viewer)


@router.get("/api/projects/{project_id}/graph/impact")
def get_person_departure_impact(
    project_id: str,
    person_id: str = Query(default=""),
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return 'what breaks if X leaves' ranked by downstream dependents."""
    _, mem = _scoped_project(project_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, mem.role, view_as)
    return what_if_leaves(db, project_id, person_id, viewer)


# ── Custody Checklist (No Secrets) ───────────────────────────────────────────

class CustodyCreateRequest(BaseModel):
    kind: str = "other"
    name: str
    owner_person: Optional[str] = None
    backup_owner: Optional[str] = None
    status: str = "unconfirmed"
    where_to_request_access: Optional[str] = None
    notes: Optional[str] = None
    evidence_claim_ids: List[str] = []
    clearance_level: str = "team"


class CustodyUpdateRequest(BaseModel):
    kind: Optional[str] = None
    name: Optional[str] = None
    owner_person: Optional[str] = None
    backup_owner: Optional[str] = None
    status: Optional[str] = None
    where_to_request_access: Optional[str] = None
    notes: Optional[str] = None


class CustodyConfirmRequest(BaseModel):
    status: str = "confirmed"  # confirmed | transferred
    note: Optional[str] = None


@router.get("/api/projects/{project_id}/custody")
def list_project_custody(
    project_id: str,
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _, mem = _scoped_project(project_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, mem.role, view_as)
    return list_custody_for_viewer(db, project_id, viewer)


@router.post("/api/projects/{project_id}/custody", status_code=201)
def create_project_custody(
    project_id: str,
    body: CustodyCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _, mem = _scoped_project(project_id, current_user.id, db)
    if mem.role != "admin":
        raise HTTPException(403, "Only workspace admins can add custody checklist items.")
    actor = db.get(User, current_user.id)
    try:
        item = create_custody_item(db, project_id, actor, body.model_dump())
    except SecretRejectedError as exc:
        raise HTTPException(400, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return serialize_custody(db, item)


@router.patch("/api/custody/{custody_id}")
def patch_custody_item(
    custody_id: str,
    body: CustodyUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item, mem = _scoped_custody(custody_id, current_user.id, db)
    if mem.role != "admin":
        raise HTTPException(403, "Only workspace admins can edit custody checklist items.")
    actor = db.get(User, current_user.id)
    try:
        updated = update_custody_item(db, item, actor, body.model_dump(exclude_unset=True))
    except SecretRejectedError as exc:
        raise HTTPException(400, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return serialize_custody(db, updated)


@router.delete("/api/custody/{custody_id}", status_code=204)
def delete_custody_item(
    custody_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item, mem = _scoped_custody(custody_id, current_user.id, db)
    if mem.role != "admin":
        raise HTTPException(403, "Only workspace admins can delete custody checklist items.")
    db.delete(item)
    db.commit()


@router.post("/api/custody/{custody_id}/confirm")
def confirm_custody_endpoint(
    custody_id: str,
    body: Optional[CustodyConfirmRequest] = None,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item, mem = _scoped_custody(custody_id, current_user.id, db)
    if mem.role != "admin":
        raise HTTPException(403, "Only workspace admins can confirm or transfer custody items.")
    actor = db.get(User, current_user.id)
    try:
        updated = confirm_custody_item(
            db,
            item,
            actor,
            target_status=body.status if body else "confirmed",
            note=body.note if body else None,
        )
    except SecretRejectedError as exc:
        raise HTTPException(400, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return serialize_custody(db, updated)


@router.get("/api/custody/{custody_id}/history")
def get_custody_history(
    custody_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item, mem = _scoped_custody(custody_id, current_user.id, db)
    if mem.role not in ("admin", "team_member"):
        raise HTTPException(403, "Custody audit history is restricted to team leads and members.")
    if mem.role != "admin" and item.clearance_level == "restricted":
        raise HTTPException(404, "Custody item not found.")
    events = (
        db.query(CustodyEvent)
        .filter(CustodyEvent.custody_item_id == item.id)
        .order_by(CustodyEvent.timestamp.desc())
        .all()
    )
    out = []
    for ev in events:
        actor = db.get(User, ev.actor_id) if ev.actor_id else None
        out.append({
            "id": ev.id,
            "custody_item_id": ev.custody_item_id,
            "actor_id": ev.actor_id,
            "actor_name": actor.name if actor else "system",
            "action": ev.action,
            "detail_json": ev.detail_json,
            "timestamp": ev.timestamp.isoformat() if ev.timestamp else None,
        })
    return out
