"""Workspaces router — create, list, invites, member management."""

import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.models import Invite, Membership, User, Workspace

router = APIRouter(prefix="/api/workspaces", tags=["Workspaces"])

VALID_ROLES = {"admin", "team_member", "incoming", "departing"}


# ── Schemas ───────────────────────────────────────────────────────────────────

class WorkspaceCreate(BaseModel):
    name: str


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    created_at: datetime
    role: str  # caller's role in this workspace

    model_config = {"from_attributes": True}


class InviteCreate(BaseModel):
    role: str
    expires_hours: int = 48


class InviteResponse(BaseModel):
    id: str
    workspace_id: str
    role: str
    token: str
    expires_at: datetime
    is_used: bool
    is_revoked: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class MemberResponse(BaseModel):
    user_id: str
    name: str
    email: str
    role: str
    joined_at: datetime

    model_config = {"from_attributes": True}


class RoleChangeRequest(BaseModel):
    role: str


class JoinRequest(BaseModel):
    token: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_workspace_or_404(workspace_id: str, db: Session) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return ws


def _require_membership(workspace_id: str, user_id: str, db: Session) -> Membership:
    m = (
        db.query(Membership)
        .filter(Membership.workspace_id == workspace_id, Membership.user_id == user_id)
        .first()
    )
    if not m:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return m


def _require_admin(workspace_id: str, user_id: str, db: Session) -> Membership:
    m = _require_membership(workspace_id, user_id, db)
    if m.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    return m


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", response_model=WorkspaceResponse, status_code=201)
def create_workspace(
    body: WorkspaceCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new workspace and make the caller the admin."""
    ws = Workspace(name=body.name.strip())
    db.add(ws)
    db.flush()
    membership = Membership(user_id=current_user.id, workspace_id=ws.id, role="admin")
    db.add(membership)
    # Update user's default role to admin if they have no prior memberships
    db.commit()
    db.refresh(ws)
    return WorkspaceResponse(
        id=ws.id,
        name=ws.name,
        created_at=ws.created_at,
        role="admin",
    )


@router.get("", response_model=List[WorkspaceResponse])
def list_workspaces(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all workspaces the current user belongs to."""
    memberships = (
        db.query(Membership).filter(Membership.user_id == current_user.id).all()
    )
    result = []
    for m in memberships:
        ws = m.workspace
        if ws:
            result.append(
                WorkspaceResponse(id=ws.id, name=ws.name, created_at=ws.created_at, role=m.role)
            )
    return result


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(
    workspace_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_workspace_or_404(workspace_id, db)
    m = _require_membership(workspace_id, current_user.id, db)
    ws = m.workspace
    return WorkspaceResponse(id=ws.id, name=ws.name, created_at=ws.created_at, role=m.role)


# ── Members ────────────────────────────────────────────────────────────────────

@router.get("/{workspace_id}/members", response_model=List[MemberResponse])
def list_members(
    workspace_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_workspace_or_404(workspace_id, db)
    _require_membership(workspace_id, current_user.id, db)
    memberships = (
        db.query(Membership).filter(Membership.workspace_id == workspace_id).all()
    )
    return [
        MemberResponse(
            user_id=m.user_id,
            name=m.user.name,
            email=m.user.email,
            role=m.role,
            joined_at=m.created_at,
        )
        for m in memberships
        if m.user
    ]


@router.patch("/{workspace_id}/members/{user_id}/role", response_model=MemberResponse)
def change_member_role(
    workspace_id: str,
    user_id: str,
    body: RoleChangeRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_workspace_or_404(workspace_id, db)
    _require_admin(workspace_id, current_user.id, db)
    if body.role not in VALID_ROLES:
        raise HTTPException(400, f"Invalid role. Choose from: {', '.join(VALID_ROLES)}")
    target = (
        db.query(Membership)
        .filter(Membership.workspace_id == workspace_id, Membership.user_id == user_id)
        .first()
    )
    if not target:
        raise HTTPException(404, "Member not found.")
    # Prevent demoting the last admin
    if target.role == "admin" and body.role != "admin":
        admin_count = (
            db.query(Membership)
            .filter(Membership.workspace_id == workspace_id, Membership.role == "admin")
            .count()
        )
        if admin_count <= 1:
            raise HTTPException(400, "Cannot remove the last admin from the workspace.")
    target.role = body.role
    db.commit()
    db.refresh(target)
    return MemberResponse(
        user_id=target.user_id,
        name=target.user.name,
        email=target.user.email,
        role=target.role,
        joined_at=target.created_at,
    )


@router.delete("/{workspace_id}/members/{user_id}", status_code=204)
def revoke_member(
    workspace_id: str,
    user_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_workspace_or_404(workspace_id, db)
    _require_admin(workspace_id, current_user.id, db)
    if user_id == current_user.id:
        raise HTTPException(400, "Cannot remove yourself from the workspace.")
    target = (
        db.query(Membership)
        .filter(Membership.workspace_id == workspace_id, Membership.user_id == user_id)
        .first()
    )
    if not target:
        raise HTTPException(404, "Member not found.")
    db.delete(target)
    db.commit()


# ── Invites ────────────────────────────────────────────────────────────────────

@router.post("/{workspace_id}/invites", response_model=InviteResponse, status_code=201)
def create_invite(
    workspace_id: str,
    body: InviteCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_workspace_or_404(workspace_id, db)
    _require_admin(workspace_id, current_user.id, db)
    if body.role not in VALID_ROLES:
        raise HTTPException(400, f"Invalid role. Choose from: {', '.join(VALID_ROLES)}")
    invite = Invite(
        workspace_id=workspace_id,
        role=body.role,
        token=secrets.token_urlsafe(32),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=body.expires_hours),
        created_by=current_user.id,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return InviteResponse.model_validate(invite)


@router.get("/{workspace_id}/invites", response_model=List[InviteResponse])
def list_invites(
    workspace_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_workspace_or_404(workspace_id, db)
    _require_admin(workspace_id, current_user.id, db)
    invites = db.query(Invite).filter(Invite.workspace_id == workspace_id).all()
    return [InviteResponse.model_validate(i) for i in invites]


@router.delete("/{workspace_id}/invites/{invite_id}", status_code=204)
def revoke_invite(
    workspace_id: str,
    invite_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_workspace_or_404(workspace_id, db)
    _require_admin(workspace_id, current_user.id, db)
    invite = db.query(Invite).filter(Invite.id == invite_id, Invite.workspace_id == workspace_id).first()
    if not invite:
        raise HTTPException(404, "Invite not found.")
    invite.is_revoked = True
    db.commit()


# ── Join by invite token ───────────────────────────────────────────────────────

@router.post("/join", response_model=WorkspaceResponse, status_code=201)
def join_workspace(
    body: JoinRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Accept an invite token and join the linked workspace."""
    invite = db.query(Invite).filter(Invite.token == body.token).first()
    if not invite:
        raise HTTPException(404, "Invite not found.")
    if invite.is_revoked:
        raise HTTPException(410, "This invite has been revoked.")
    if invite.is_used:
        raise HTTPException(410, "This invite has already been used.")
    if invite.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(410, "This invite has expired.")

    # Check already a member
    existing = (
        db.query(Membership)
        .filter(Membership.workspace_id == invite.workspace_id, Membership.user_id == current_user.id)
        .first()
    )
    if existing:
        raise HTTPException(409, "You are already a member of this workspace.")

    membership = Membership(
        user_id=current_user.id,
        workspace_id=invite.workspace_id,
        role=invite.role,
    )
    db.add(membership)
    invite.is_used = True
    db.commit()
    db.refresh(membership)
    ws = membership.workspace
    return WorkspaceResponse(id=ws.id, name=ws.name, created_at=ws.created_at, role=membership.role)


# ── Preview invite (public — no auth required) ─────────────────────────────────

@router.get("/invite-preview/{token}")
def preview_invite(token: str, db: Session = Depends(get_db)):
    """Return workspace name and role for an invite token (no auth needed)."""
    invite = db.query(Invite).filter(Invite.token == token).first()
    if not invite or invite.is_revoked or invite.is_used:
        raise HTTPException(404, "Invite not found or already used.")
    if invite.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(410, "Invite has expired.")
    ws = db.get(Workspace, invite.workspace_id)
    return {
        "workspace_id": invite.workspace_id,
        "workspace_name": ws.name if ws else "Unknown",
        "role": invite.role,
        "expires_at": invite.expires_at,
    }
