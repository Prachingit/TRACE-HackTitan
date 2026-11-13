"""Phase 7 router: Handover Center, sections review, sharing, acknowledgement, PDF export, and onboarding checklist."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.engine.clearance import (
    ClearanceError,
    ViewerContext,
    can_view_handover,
    filter_handover_sections,
    resolve_viewer_profile,
)
from app.engine.handover import (
    acknowledge_handover,
    approve_handover,
    generate_handover,
    render_handover_pdf,
    review_handover_section,
    revoke_handover_share,
    share_handover,
)
from app.models import (
    Handover,
    HandoverEvent,
    HandoverSection,
    Membership,
    OnboardingProgress,
    Project,
    User,
)

router = APIRouter(tags=["Handovers"])


def _get_scoped_project(project_id: str, user_id: str, db: Session) -> tuple[Project, Membership]:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found.")
    membership = (
        db.query(Membership)
        .filter(Membership.workspace_id == project.workspace_id, Membership.user_id == user_id)
        .first()
    )
    if not membership:
        raise HTTPException(404, "Project not found.")
    return project, membership


def _get_scoped_handover(handover_id: str, user_id: str, db: Session) -> tuple[Handover, Project, Membership]:
    handover = db.get(Handover, handover_id)
    if not handover:
        raise HTTPException(404, "Handover not found.")
    project, membership = _get_scoped_project(handover.project_id, user_id, db)
    return handover, project, membership


def _resolve_viewer(user: CurrentUser, role: str, view_as: Optional[str]) -> ViewerContext:
    try:
        return resolve_viewer_profile(user.id, user.name, role, view_as)
    except ClearanceError as exc:
        raise HTTPException(exc.status_code, str(exc))


def _parse_json_obj(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {}
        except Exception:
            return {}
    return {}


def _serialize_handover(
    db: Session,
    h: Handover,
    viewer: ViewerContext,
    include_sections: bool = False,
) -> Dict[str, Any]:
    target_user = db.get(User, h.incoming_user_id) if h.incoming_user_id else None
    departing_user = db.get(User, h.departing_user_id) if h.departing_user_id else None
    approved_user = db.get(User, h.approved_by) if h.approved_by else None
    ack_user = db.get(User, h.acknowledged_by) if h.acknowledged_by else None
    proj = db.get(Project, h.project_id)
    readiness_obj = _parse_json_obj(h.readiness_json)
    snap_obj = _parse_json_obj(h.snapshot_json)

    payload: Dict[str, Any] = {
        "id": h.id,
        "project_id": h.project_id,
        "project_name": proj.name if proj else None,
        "title": snap_obj.get("title") or (f"{proj.name} Handover" if proj else "Handover"),
        "period_label": snap_obj.get("period_label"),
        "status": h.status,
        "readiness_score": h.readiness_score,
        "readiness_json": readiness_obj,
        "departing_user_id": h.departing_user_id,
        "departing_user_name": departing_user.name if departing_user else None,
        "target_user_id": h.incoming_user_id,
        "target_user_name": target_user.name if target_user else None,
        "incoming_user_id": h.incoming_user_id,
        "incoming_user_name": target_user.name if target_user else None,
        "approved_by": h.approved_by,
        "approved_by_name": approved_user.name if approved_user else None,
        "approved_at": h.approved_at.isoformat() if h.approved_at else None,
        "shared_at": h.shared_at.isoformat() if h.shared_at else None,
        "share_revoked_at": h.share_revoked_at.isoformat() if h.share_revoked_at else None,
        "acknowledged_by": h.acknowledged_by,
        "acknowledged_by_name": ack_user.name if ack_user else None,
        "acknowledged_at": h.acknowledged_at.isoformat() if h.acknowledged_at else None,
        "created_at": h.created_at.isoformat() if h.created_at else None,
        "updated_at": h.updated_at.isoformat() if h.updated_at else None,
        "viewer_profile": viewer.profile,
        "is_preview": viewer.is_preview,
    }
    if viewer.profile == "team_lead" and snap_obj:
        payload["snapshot_json"] = snap_obj

    if include_sections:
        sections = (
            db.query(HandoverSection)
            .filter(HandoverSection.handover_id == h.id)
            .order_by(HandoverSection.ordinal.asc())
            .all()
        )
        filtered_secs = filter_handover_sections(viewer, h, sections)
        # Expose both content and body_json keys for UI/API convenience
        for s in filtered_secs:
            s["body_json"] = s.get("content") or {}
            s["content_md"] = s["body_json"].get("summary") or s["body_json"].get("summary_md") or ""
        payload["sections"] = filtered_secs
    return payload


class GenerateHandoverRequest(BaseModel):
    departing_user_id: Optional[str] = None
    target_user_id: Optional[str] = None
    title: Optional[str] = None
    period_label: Optional[str] = None


class SectionPatchRequest(BaseModel):
    review_status: Optional[str] = None
    content_md: Optional[str] = None
    body_json: Optional[Dict[str, Any]] = None
    approved_with_gaps: Optional[bool] = None
    gap_note: Optional[str] = None


class ShareHandoverRequest(BaseModel):
    target_user_id: str


class OnboardingUpdateRequest(BaseModel):
    item_key: str
    completed: bool = True
    note: Optional[str] = None


@router.post("/api/projects/{project_id}/handovers", status_code=201)
def create_project_handover(
    project_id: str,
    body: GenerateHandoverRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, membership = _get_scoped_project(project_id, current_user.id, db)
    if membership.role != "admin":
        raise HTTPException(403, "Only workspace admins can generate handovers.")
    user_row = db.get(User, current_user.id)
    handover = generate_handover(
        db,
        project,
        user_row,
        departing_user_id=body.departing_user_id,
        target_user_id=body.target_user_id,
        title=body.title,
        period_label=body.period_label,
    )
    viewer = _resolve_viewer(current_user, membership.role, None)
    return _serialize_handover(db, handover, viewer, include_sections=True)


@router.get("/api/projects/{project_id}/handovers")
def list_project_handovers(
    project_id: str,
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _, membership = _get_scoped_project(project_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, membership.role, view_as)
    rows = (
        db.query(Handover)
        .filter(Handover.project_id == project_id)
        .order_by(Handover.created_at.desc())
        .all()
    )
    visible = [h for h in rows if can_view_handover(viewer, h)]
    return [_serialize_handover(db, h, viewer, include_sections=False) for h in visible]


@router.get("/api/handovers")
def list_visible_handovers(
    project_id: Optional[str] = Query(default=None),
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    memberships = db.query(Membership).filter(Membership.user_id == current_user.id).all()
    role_by_ws = {m.workspace_id: m.role for m in memberships}
    if not role_by_ws:
        return []
    projects = db.query(Project).filter(Project.workspace_id.in_(list(role_by_ws.keys()))).all()
    ws_by_proj = {p.id: p.workspace_id for p in projects}
    if project_id:
        if project_id not in ws_by_proj:
            raise HTTPException(404, "Project not found.")
        proj_ids = [project_id]
    else:
        proj_ids = list(ws_by_proj.keys())
    if not proj_ids:
        return []

    rows = (
        db.query(Handover)
        .filter(Handover.project_id.in_(proj_ids))
        .order_by(Handover.created_at.desc())
        .all()
    )
    out = []
    for h in rows:
        ws_id = ws_by_proj.get(h.project_id)
        role = role_by_ws.get(ws_id, "incoming")
        viewer = _resolve_viewer(current_user, role, view_as)
        if can_view_handover(viewer, h):
            out.append(_serialize_handover(db, h, viewer, include_sections=False))
    return out


@router.get("/api/handovers/{handover_id}")
def get_handover_detail(
    handover_id: str,
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    handover, _, membership = _get_scoped_handover(handover_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, membership.role, view_as)
    if not can_view_handover(viewer, handover):
        raise HTTPException(403, "You do not have access to this handover.")
    return _serialize_handover(db, handover, viewer, include_sections=True)


@router.patch("/api/handovers/{handover_id}/sections/{section_key}")
def patch_handover_section(
    handover_id: str,
    section_key: str,
    body: SectionPatchRequest,
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if view_as:
        raise HTTPException(403, "Preview mode is read-only.")
    handover, _, membership = _get_scoped_handover(handover_id, current_user.id, db)
    if membership.role != "admin":
        raise HTTPException(403, "Only workspace admins can review or edit handover sections.")
    reviewer = db.get(User, current_user.id)
    try:
        sec = review_handover_section(
            db,
            handover,
            section_key,
            reviewer,
            review_status=body.review_status,
            content_md=body.content_md,
            body_json=body.body_json,
            approved_with_gaps=body.approved_with_gaps,
            gap_note=body.gap_note,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    sec_body = _parse_json_obj(sec.content_json)
    return {
        "id": sec.id,
        "section_key": sec.section_key,
        "title": sec.title,
        "review_status": sec.review_status,
        "approved_with_gaps": sec.approved_with_gaps,
        "gap_note": sec.gap_note,
        "content_md": sec_body.get("summary") or sec_body.get("summary_md") or "",
        "body_json": sec_body,
        "reviewed_by": sec.reviewed_by,
        "reviewed_at": sec.reviewed_at.isoformat() if sec.reviewed_at else None,
    }


@router.post("/api/handovers/{handover_id}/approve")
def approve_handover_endpoint(
    handover_id: str,
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if view_as:
        raise HTTPException(403, "Preview mode is read-only.")
    handover, _, membership = _get_scoped_handover(handover_id, current_user.id, db)
    if membership.role != "admin":
        raise HTTPException(403, "Only workspace admins can approve handovers.")
    approver = db.get(User, current_user.id)
    try:
        updated = approve_handover(db, handover, approver)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    viewer = _resolve_viewer(current_user, membership.role, None)
    return _serialize_handover(db, updated, viewer, include_sections=True)


@router.post("/api/handovers/{handover_id}/share")
def share_handover_endpoint(
    handover_id: str,
    body: ShareHandoverRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    handover, project, membership = _get_scoped_handover(handover_id, current_user.id, db)
    if membership.role != "admin":
        raise HTTPException(403, "Only workspace admins can share handovers.")
    target_mem = (
        db.query(Membership)
        .filter(Membership.workspace_id == project.workspace_id, Membership.user_id == body.target_user_id)
        .first()
    )
    if not target_mem:
        raise HTTPException(400, "Target user must belong to the same workspace.")
    actor = db.get(User, current_user.id)
    try:
        updated = share_handover(db, handover, actor, body.target_user_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    viewer = _resolve_viewer(current_user, membership.role, None)
    return _serialize_handover(db, updated, viewer, include_sections=False)


@router.post("/api/handovers/{handover_id}/revoke")
def revoke_handover_endpoint(
    handover_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    handover, _, membership = _get_scoped_handover(handover_id, current_user.id, db)
    if membership.role != "admin":
        raise HTTPException(403, "Only workspace admins can revoke handover sharing.")
    actor = db.get(User, current_user.id)
    updated = revoke_handover_share(db, handover, actor)
    viewer = _resolve_viewer(current_user, membership.role, None)
    return _serialize_handover(db, updated, viewer, include_sections=False)


@router.post("/api/handovers/{handover_id}/acknowledge")
def acknowledge_handover_endpoint(
    handover_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    handover, _, _ = _get_scoped_handover(handover_id, current_user.id, db)
    incoming_user = db.get(User, current_user.id)
    try:
        updated = acknowledge_handover(db, handover, incoming_user)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    viewer = _resolve_viewer(current_user, "incoming", None)
    return _serialize_handover(db, updated, viewer, include_sections=False)


@router.get("/api/handovers/{handover_id}/export.pdf")
def export_handover_pdf(
    handover_id: str,
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    handover, _, membership = _get_scoped_handover(handover_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, membership.role, view_as)
    if not can_view_handover(viewer, handover):
        raise HTTPException(403, "You do not have access to export this handover.")
    pdf_bytes = render_handover_pdf(db, handover, viewer)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="handover-{handover.id}.pdf"'},
    )


@router.get("/api/handovers/{handover_id}/history")
def get_handover_history(
    handover_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    handover, _, membership = _get_scoped_handover(handover_id, current_user.id, db)
    if membership.role not in ("admin", "team_member"):
        raise HTTPException(403, "Handover audit history is restricted to team leads and members.")
    events = (
        db.query(HandoverEvent)
        .filter(HandoverEvent.handover_id == handover.id)
        .order_by(HandoverEvent.timestamp.desc())
        .all()
    )
    out = []
    for ev in events:
        actor = db.get(User, ev.actor_id) if ev.actor_id else None
        out.append(
            {
                "id": ev.id,
                "handover_id": ev.handover_id,
                "actor_user_id": ev.actor_id,
                "actor_name": actor.name if actor else "system",
                "action": ev.action,
                "section_key": ev.section_key,
                "detail_json": _parse_json_obj(ev.detail),
                "created_at": ev.timestamp.isoformat() if ev.timestamp else None,
            }
        )
    return out


@router.get("/api/handovers/{handover_id}/onboarding")
def get_onboarding_progress(
    handover_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    handover, _, membership = _get_scoped_handover(handover_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, membership.role, None)
    if not can_view_handover(viewer, handover):
        raise HTTPException(403, "You do not have access to this handover.")
    rows = (
        db.query(OnboardingProgress)
        .filter(OnboardingProgress.handover_id == handover.id, OnboardingProgress.user_id == current_user.id)
        .all()
    )
    return [
        {
            "id": r.id,
            "section_key": r.section_key,
            "item_key": r.item_key,
            "completed": r.understood,
            "understood": r.understood,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            "note": r.note,
        }
        for r in rows
    ]


@router.post("/api/handovers/{handover_id}/onboarding")
def upsert_onboarding_progress(
    handover_id: str,
    body: OnboardingUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    handover, _, membership = _get_scoped_handover(handover_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, membership.role, None)
    if not can_view_handover(viewer, handover):
        raise HTTPException(403, "You do not have access to this handover.")

    row = (
        db.query(OnboardingProgress)
        .filter(
            OnboardingProgress.handover_id == handover.id,
            OnboardingProgress.user_id == current_user.id,
            OnboardingProgress.item_key == body.item_key,
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if row is None:
        row = OnboardingProgress(
            handover_id=handover.id,
            user_id=current_user.id,
            section_key="recommended_next_steps",
            item_key=body.item_key,
            understood=body.completed,
            note=body.note,
        )
        db.add(row)
    else:
        row.understood = body.completed
        row.updated_at = now
        if body.note is not None:
            row.note = body.note
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "section_key": row.section_key,
        "item_key": row.item_key,
        "completed": row.understood,
        "understood": row.understood,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "note": row.note,
    }
