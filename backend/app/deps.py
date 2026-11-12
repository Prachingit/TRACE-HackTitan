"""Authentication and identity dependencies for TRACE — Phase 2 (real JWT auth)."""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.security import COOKIE_NAME, decode_access_token
from app.db import get_db
from app.models import Membership, User, Workspace


class CurrentUser:
    def __init__(
        self,
        user: User,
        membership: "Membership | None",
        role: str,
        workspace: "Workspace | None",
    ):
        self.id = user.id
        self.name = user.name
        self.email = user.email
        self.role = role
        self.workspace_id = workspace.id if workspace else None
        self.workspace_name = workspace.name if workspace else None
        self.user = user
        self.membership = membership

    def require_admin(self) -> None:
        if self.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required.",
            )


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> CurrentUser:
    """Resolve current user from httpOnly JWT cookie."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )
    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid.",
        )
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )
    membership = db.query(Membership).filter(Membership.user_id == user.id).first()
    role = membership.role if membership else user.role_default
    workspace = membership.workspace if membership else None
    return CurrentUser(user=user, membership=membership, role=role, workspace=workspace)


def get_workspace_membership(
    workspace_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Membership:
    """Return the user's membership in a specific workspace, or 404."""
    membership = (
        db.query(Membership)
        .filter(
            Membership.user_id == current_user.id,
            Membership.workspace_id == workspace_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found.",
        )
    return membership
