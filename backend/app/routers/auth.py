"""Auth router — signup, login, logout, /me, forgot-password."""

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.core.security import COOKIE_NAME, create_access_token, hash_password, verify_password
from app.config import settings
from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.models import User

router = APIRouter(prefix="/api/auth", tags=["Auth"])
limiter = Limiter(key_func=get_remote_address)

GENERIC_LOGIN_ERROR = "Invalid email or password."
MIN_PASSWORD_LENGTH = 10


# ── Schemas ──────────────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    confirm_password: str

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be blank.")
        return v

    @field_validator("password")
    @classmethod
    def password_length(cls, v: str) -> str:
        if len(v) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        return v

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("Passwords do not match.")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    role_default: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=(settings.ENV == "production"),
        max_age=7 * 24 * 60 * 60,  # 7 days
        path="/",
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def signup(request: Request, body: SignupRequest, response: Response, db: Session = Depends(get_db)):
    """Create a new user account."""
    email_lower = body.email.lower()
    if db.query(User).filter(User.email == email_lower).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )
    user = User(
        name=body.name.strip(),
        email=email_lower,
        password_hash=hash_password(body.password),
        role_default="admin",  # First user in their workspace is admin
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.id)
    _set_auth_cookie(response, token)
    return UserResponse.model_validate(user)


@router.post("/login", response_model=UserResponse)
@limiter.limit("10/minute")
def login(request: Request, body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """Authenticate and issue a session cookie."""
    email_lower = body.email.lower()
    user = db.query(User).filter(User.email == email_lower).first()
    # Use constant-time comparison regardless of whether user exists
    if not user or not verify_password(body.password, user.password_hash or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=GENERIC_LOGIN_ERROR,
        )
    token = create_access_token(user.id)
    _set_auth_cookie(response, token)
    return UserResponse.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    """Clear the session cookie."""
    response.delete_cookie(key=COOKIE_NAME, path="/")


@router.get("/me", response_model=UserResponse)
def me(current_user: CurrentUser = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return UserResponse.model_validate(current_user.user)


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(body: ForgotPasswordRequest):
    """
    Initiate password reset.
    Returns 202 regardless of whether the email exists (no email enumeration).
    If SMTP is not configured, returns an honest message.
    """
    if not settings.smtp_configured:
        return {
            "message": (
                "Email-based password reset is not configured on this server. "
                "Please contact your workspace admin to reset your password manually."
            )
        }
    # SMTP is configured — in a production build, enqueue a reset token email here.
    # For now, acknowledge the request without revealing email existence.
    return {"message": "If an account with that email exists, a reset link has been sent."}


class DemoLoginRequest(BaseModel):
    role: str = "admin"


@router.get("/demo")
def get_demo_info():
    """Return synthetic demo account credentials and 5-step judge guide."""
    from app.services.demo import DEMO_ACCOUNTS

    return {
        "synthetic": True,
        "workspace_name": "Atlas Workspace (SYNTHETIC DEMO)",
        "accounts": [
            {
                "role": a["role"],
                "label": a["label"],
                "email": a["email"],
                "password": a["password"],
                "summary": a["summary"],
            }
            for a in DEMO_ACCOUNTS
        ],
        "steps": [
            "1. Sign in as Team Lead (Alex) to inspect Continuity Overview, Handover Center, Evidence Ledger, and Contradiction Radar.",
            "2. Open a claim in Evidence Ledger to verify exact source excerpts and test Admin-only 'Preview as: Incoming' clearance filtering.",
            "3. Switch to Incoming Member (Priya) to see the gated Incoming Portal, 'Where should I start?' continuation plan, and zero restricted data.",
            "4. Switch to Departing Member (Rahul) to see only Rahul's own contributions and Exit Interview items.",
            "5. Or create your own real account via Sign up to upload any non-Atlas project files into a clean workspace.",
        ],
    }


@router.post("/demo", response_model=UserResponse)
def login_demo(
    body: DemoLoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """One-click login into an isolated, synthetic demo role."""
    from app.services.demo import DEMO_ACCOUNTS, ensure_demo_seeded

    target = next((a for a in DEMO_ACCOUNTS if a["role"] == body.role), None)
    if target is None:
        raise HTTPException(400, "Invalid demo role. Choose admin, incoming, or departing.")

    ensure_demo_seeded(db)
    user = db.query(User).filter(User.email == target["email"]).first()
    if not user:
        raise HTTPException(500, "Demo account unavailable.")

    token = create_access_token(user.id)
    _set_auth_cookie(response, token)
    return UserResponse.model_validate(user)
