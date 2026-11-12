"""Atlas Workspace Database Seeding Service.

Creates the workspace, users, memberships, project (is_synthetic=True),
and registers every synthetic file in backend/data/atlas/ as a Source.
Does NOT extract claims or chunks (Phase 3 scope).
Idempotent: running multiple times does not duplicate records.
"""

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import Membership, Project, Source, User, Workspace

ATLAS_DIR = Path(settings.ATLAS_DATA_DIR).resolve()

USERS_DATA = [
    {
        "id": "usr-meera",
        "name": "Meera Shah",
        "email": "meera.shah@example.com",
        "role": "admin",
        "role_default": "admin",
    },
    {
        "id": "usr-priya",
        "name": "Priya Nair",
        "email": "priya.nair@example.com",
        "role": "incoming",
        "role_default": "incoming",
    },
    {
        "id": "usr-rahul",
        "name": "Rahul Verma",
        "email": "rahul.verma@example.com",
        "role": "departing",
        "role_default": "departing",
    },
    {
        "id": "usr-ankit",
        "name": "Ankit Rao",
        "email": "ankit.rao@example.com",
        "role": "team_member",
        "role_default": "team_member",
    },
]

SOURCES_METADATA = [
    {
        "id": "SRC-001",
        "type": "github_commits",
        "filename": "commits.json",
        "clearance_level": "team",
    },
    {
        "id": "SRC-002",
        "type": "csv",
        "filename": "tasks.csv",
        "clearance_level": "team",
    },
    {
        "id": "SRC-003",
        "type": "markdown",
        "filename": "meeting_notes.md",
        "clearance_level": "team",
    },
    {
        "id": "SRC-004",
        "type": "chat_json",
        "filename": "chat.json",
        "clearance_level": "team",
    },
    {
        "id": "SRC-005",
        "type": "markdown",
        "filename": "docs/architecture.md",
        "clearance_level": "public",
    },
    {
        "id": "SRC-006",
        "type": "markdown",
        "filename": "docs/api_notes.md",
        "clearance_level": "public",
    },
    {
        "id": "SRC-007",
        "type": "markdown",
        "filename": "restricted_internal.md",
        "clearance_level": "restricted",
    },
]


def compute_file_hash(path: Path) -> str:
    """Compute sha256 hash of a file if it exists."""
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def seed_atlas(db: Session = None, reset: bool = False) -> Dict[str, Any]:
    """Seed Atlas Workspace, Users, Memberships, Project, and registered Sources."""
    should_close = False
    if db is None:
        init_db()
        db = SessionLocal()
        should_close = True

    try:
        # 1. Workspace
        workspace_id = "ws-atlas"
        workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if not workspace:
            workspace = Workspace(id=workspace_id, name="Atlas Workspace")
            db.add(workspace)
            db.flush()

        # 2. Users & Memberships
        for u_data in USERS_DATA:
            user = db.query(User).filter(User.id == u_data["id"]).first()
            if not user:
                user = User(
                    id=u_data["id"],
                    name=u_data["name"],
                    email=u_data["email"],
                    role_default=u_data["role_default"],
                )
                db.add(user)
                db.flush()

            # Membership
            membership = (
                db.query(Membership)
                .filter(Membership.user_id == user.id, Membership.workspace_id == workspace.id)
                .first()
            )
            if not membership:
                membership = Membership(
                    user_id=user.id,
                    workspace_id=workspace.id,
                    role=u_data["role"],
                )
                db.add(membership)
            else:
                membership.role = u_data["role"]

        # 3. Project
        project_id = "prj-atlas-core"
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            project = Project(
                id=project_id,
                workspace_id=workspace.id,
                name="Atlas Core Platform",
                description="Enterprise context and activity management engine (Synthetic Hackathon Demo).",
                category="Platform Infrastructure",
                team_size=len(USERS_DATA),
                technologies="Python, FastAPI, SQLite, React, Vite",
                start_date=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
                is_synthetic=True,
            )
            db.add(project)
            db.flush()

        # 4. Sources Registration
        sources_registered = 0
        for s_meta in SOURCES_METADATA:
            source = db.query(Source).filter(Source.id == s_meta["id"]).first()
            file_path = ATLAS_DIR / s_meta["filename"]
            content_hash = compute_file_hash(file_path)
            file_mtime = (
                datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
                if file_path.exists()
                else datetime.now(timezone.utc)
            )

            if not source:
                source = Source(
                    id=s_meta["id"],
                    project_id=project.id,
                    type=s_meta["type"],
                    filename=s_meta["filename"],
                    clearance_level=s_meta["clearance_level"],
                    status="registered",
                    content_hash=content_hash,
                    source_timestamp=file_mtime,
                )
                db.add(source)
                sources_registered += 1
            else:
                source.filename = s_meta["filename"]
                source.type = s_meta["type"]
                source.clearance_level = s_meta["clearance_level"]
                source.status = "registered"
                source.content_hash = content_hash
                source.source_timestamp = file_mtime

        db.commit()

        total_sources = db.query(Source).filter(Source.project_id == project.id).count()

        return {
            "project_id": project.id,
            "workspace_id": workspace.id,
            "sources_registered": total_sources,
        }

    except Exception as e:
        db.rollback()
        raise e
    finally:
        if should_close:
            db.close()


if __name__ == "__main__":
    result = seed_atlas()
    print("Atlas seed finished successfully:", result)
