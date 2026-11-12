"""Authentication and identity dependencies for TRACE.

In Phase 1, auth is powered by a clean demo-identity dependency:
The client passes `X-Demo-User` (user id or role alias), and the backend
resolves the User and Membership record. Unknown users return HTTP 401.
"""

from typing import Optional
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Membership, User, Workspace


class CurrentUser:
    def __init__(self, user: User, membership: Optional[Membership], role: str, workspace: Optional[Workspace]):
        self.id = user.id
        self.name = user.name
        self.email = user.email
        self.role = role
        self.workspace_id = workspace.id if workspace else "default"
        self.workspace_name = workspace.name if workspace else "Default Workspace"
        self.user = user
        self.membership = membership


def get_current_user(
    x_demo_user: Optional[str] = Header(None, alias="X-Demo-User"),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """Resolve current user from X-Demo-User header.
    
    Returns 401 if header is missing or user does not exist.
    """
    if not x_demo_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing demo authentication header: X-Demo-User",
        )

    # 1. Look up by User.id
    user = db.query(User).filter(User.id == x_demo_user).first()

    # 2. Look up by email or role alias if user ID not directly matched
    if not user:
        # Check if x_demo_user is an email or role-based alias (admin, incoming, departing)
        user = db.query(User).filter((User.email == x_demo_user) | (User.role_default == x_demo_user)).first()

    # 3. If still not found, check membership role match
    if not user:
        membership = db.query(Membership).filter(Membership.role == x_demo_user).first()
        if membership:
            user = db.query(User).filter(User.id == membership.user_id).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unknown demo user: '{x_demo_user}'",
        )

    membership = db.query(Membership).filter(Membership.user_id == user.id).first()
    role = membership.role if membership else user.role_default
    workspace = membership.workspace if membership else db.query(Workspace).first()

    return CurrentUser(user=user, membership=membership, role=role, workspace=workspace)
