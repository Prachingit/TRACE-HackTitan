"""Atlas sample loader.

Loads the synthetic Atlas files into ONE project owned by the caller.
Never creates users or workspaces and never touches other projects.
"""

import hashlib
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Project, Source
from app.services.background import parse_source

ATLAS_DIR = Path(settings.ATLAS_DATA_DIR).resolve()

SOURCES_METADATA = [
    {"type": "json", "filename": "commits.json", "clearance_level": "team"},
    {"type": "csv", "filename": "tasks.csv", "clearance_level": "team"},
    {"type": "markdown", "filename": "meeting_notes.md", "clearance_level": "team"},
    {"type": "chat_json", "filename": "chat.json", "clearance_level": "team"},
    {"type": "markdown", "filename": "docs/architecture.md", "clearance_level": "public"},
    {"type": "markdown", "filename": "docs/api_notes.md", "clearance_level": "public"},
    {"type": "markdown", "filename": "restricted_internal.md", "clearance_level": "restricted"},
]


def new_source_id() -> str:
    return f"SRC-{secrets.token_hex(4).upper()}"


def load_atlas_sample(db: Session, project_id: str) -> Dict[str, Any]:
    """Register and parse Atlas sample files inside the given project. Idempotent per project."""
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found.")

    added = 0
    skipped = 0
    for meta in SOURCES_METADATA:
        src_file = ATLAS_DIR / meta["filename"]
        if not src_file.exists():
            continue
        data = src_file.read_bytes()
        chash = hashlib.sha256(data).hexdigest()
        if db.query(Source).filter(Source.project_id == project_id, Source.content_hash == chash).first():
            skipped += 1
            continue

        source_id = new_source_id()
        dest_dir = Path(settings.DATA_DIR) / project_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{source_id}{src_file.suffix}"
        shutil.copyfile(src_file, dest)

        db.add(
            Source(
                id=source_id,
                project_id=project_id,
                type=meta["type"],
                filename=meta["filename"],
                clearance_level=meta["clearance_level"],
                status="queued",
                content_hash=chash,
                file_path=str(dest),
                source_timestamp=datetime.now(timezone.utc),
            )
        )
        db.commit()
        parse_source(source_id, db)
        added += 1

    project.is_synthetic = True
    db.commit()
    return {"project_id": project_id, "sources_added": added, "sources_skipped": skipped}
