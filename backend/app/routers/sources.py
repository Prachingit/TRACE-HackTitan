"""Sources router — file upload, GitHub import, manual entry, list, detail, chunks, delete."""

import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.models import Chunk, Membership, Project, Source
from app.services.background import parse_source, run_parse_job
from app.services.github import (
    fetch_commits,
    fetch_issues,
    fetch_pull_requests,
    github_items_to_chunks,
)
from app.services.background import _persist_chunks

router = APIRouter(prefix="/api/projects", tags=["Sources"])

MAX_FILE_SIZE = 15 * 1024 * 1024  # 15 MB
MAX_SOURCES_PER_PROJECT = 50

# Allowed extensions → source type mapping
ALLOWED_EXTENSIONS: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "txt",
    ".md": "markdown",
    ".csv": "csv",
    ".json": "json",
}

# Magic bytes for content-type sniffing
MAGIC: dict[str, bytes] = {
    "pdf": b"%PDF",
    "docx": b"PK\x03\x04",  # ZIP-based (also xlsx, pptx — good enough for rejection)
    "json": b"\x00",         # checked by content
}


# ── Schemas ───────────────────────────────────────────────────────────────────

class SourceResponse(BaseModel):
    id: str
    project_id: str
    type: str
    filename: str
    clearance_level: str
    status: str
    error_message: Optional[str]
    uploaded_at: datetime
    source_timestamp: Optional[datetime]
    content_hash: Optional[str]
    chunk_count: int = 0

    model_config = {"from_attributes": True}


class ChunkResponse(BaseModel):
    id: str
    source_id: str
    ordinal: int
    text: str
    author: Optional[str]
    timestamp: Optional[datetime]
    locator: Optional[str]

    model_config = {"from_attributes": True}


class GithubImportRequest(BaseModel):
    repo_url: str
    clearance_level: str = "team"
    fetch_commits: bool = True
    fetch_prs: bool = True
    fetch_issues: bool = True


class ManualEntryRequest(BaseModel):
    title: str
    content: str
    clearance_level: str = "team"
    author: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

CLEARANCE_LEVELS = {"public", "team", "restricted"}


def _get_project_scoped(project_id: str, user_id: str, db: Session) -> tuple[Project, Membership]:
    """Return (Project, Membership) or raise 404 if not accessible."""
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


def _sanitize_filename(name: str) -> str:
    name = Path(name).name  # strip directory components
    name = re.sub(r"[^\w\-. ]", "_", name)
    return name[:128] or "upload"


def _content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _detect_ext(filename: str, data: bytes) -> str:
    """Return lowercase extension, raising 400 on disallowed or spoofed types."""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            f"File type '{suffix}' is not allowed. "
            f"Accepted: {', '.join(ALLOWED_EXTENSIONS)}",
        )
    # Content sniffing
    if suffix == ".pdf" and not data.startswith(b"%PDF"):
        raise HTTPException(400, "File has a .pdf extension but does not appear to be a PDF.")
    if suffix == ".docx" and not data.startswith(b"PK\x03\x04"):
        raise HTTPException(400, "File has a .docx extension but does not appear to be a valid DOCX.")
    return suffix


def _stored_path(project_id: str, source_id: str, suffix: str) -> Path:
    upload_dir = Path(settings.DATA_DIR) / project_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir / f"{source_id}{suffix}"


def _next_source_id(project_id: str, db: Session) -> str:
    from app.services.seed import new_source_id
    return new_source_id()


def _apply_clearance_filter(query, role: str):
    if role in ("incoming", "departing"):
        query = query.filter(Source.clearance_level != "restricted")
    return query


# ── List sources ──────────────────────────────────────────────────────────────

@router.get("/{project_id}/sources", response_model=List[SourceResponse])
def list_sources(
    project_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, membership = _get_project_scoped(project_id, current_user.id, db)
    q = db.query(Source).filter(Source.project_id == project_id)
    q = _apply_clearance_filter(q, membership.role)
    sources = q.order_by(Source.uploaded_at.desc()).all()
    result = []
    for s in sources:
        chunk_count = db.query(Chunk).filter(Chunk.source_id == s.id).count()
        resp = SourceResponse(
            id=s.id,
            project_id=s.project_id,
            type=s.type,
            filename=s.filename,
            clearance_level=s.clearance_level,
            status=s.status,
            error_message=s.error_message,
            uploaded_at=s.uploaded_at,
            source_timestamp=s.source_timestamp,
            content_hash=s.content_hash,
            chunk_count=chunk_count,
        )
        result.append(resp)
    return result


# ── Source detail ─────────────────────────────────────────────────────────────

@router.get("/{project_id}/sources/{source_id}", response_model=SourceResponse)
def get_source(
    project_id: str,
    source_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, membership = _get_project_scoped(project_id, current_user.id, db)
    source = db.query(Source).filter(Source.project_id == project_id, Source.id == source_id).first()
    if not source:
        raise HTTPException(404, "Source not found.")
    if source.clearance_level == "restricted" and membership.role in ("incoming", "departing"):
        raise HTTPException(404, "Source not found.")
    chunk_count = db.query(Chunk).filter(Chunk.source_id == source_id).count()
    return SourceResponse(
        id=source.id,
        project_id=source.project_id,
        type=source.type,
        filename=source.filename,
        clearance_level=source.clearance_level,
        status=source.status,
        error_message=source.error_message,
        uploaded_at=source.uploaded_at,
        source_timestamp=source.source_timestamp,
        content_hash=source.content_hash,
        chunk_count=chunk_count,
    )


# ── Chunks ────────────────────────────────────────────────────────────────────

@router.get("/{project_id}/sources/{source_id}/chunks", response_model=List[ChunkResponse])
def get_chunks(
    project_id: str,
    source_id: str,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, membership = _get_project_scoped(project_id, current_user.id, db)
    source = db.query(Source).filter(Source.project_id == project_id, Source.id == source_id).first()
    if not source:
        raise HTTPException(404, "Source not found.")
    if source.clearance_level == "restricted" and membership.role in ("incoming", "departing"):
        raise HTTPException(404, "Source not found.")
    chunks = (
        db.query(Chunk)
        .filter(Chunk.source_id == source_id)
        .order_by(Chunk.ordinal)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [ChunkResponse.model_validate(c) for c in chunks]


# ── File upload ───────────────────────────────────────────────────────────────

@router.post("/{project_id}/sources/upload", response_model=SourceResponse, status_code=201)
async def upload_source(
    project_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    clearance_level: str = Form(default="team"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, membership = _get_project_scoped(project_id, current_user.id, db)

    if clearance_level not in CLEARANCE_LEVELS:
        raise HTTPException(400, f"Invalid clearance level. Choose from: {', '.join(CLEARANCE_LEVELS)}")

    # Only admins can mark restricted
    if clearance_level == "restricted" and membership.role != "admin":
        raise HTTPException(403, "Only admins can assign restricted clearance.")

    # Source count limit
    existing_count = db.query(Source).filter(Source.project_id == project_id).count()
    if existing_count >= MAX_SOURCES_PER_PROJECT:
        raise HTTPException(400, f"Project has reached the maximum of {MAX_SOURCES_PER_PROJECT} sources.")

    if not file.filename:
        raise HTTPException(400, "No filename provided.")

    data = await file.read()

    if not data:
        raise HTTPException(400, "File is empty.")
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(413, f"File exceeds the {MAX_FILE_SIZE // 1024 // 1024} MB size limit.")

    suffix = _detect_ext(file.filename, data)
    source_type = ALLOWED_EXTENSIONS[suffix]
    safe_name = _sanitize_filename(file.filename)
    chash = _content_hash(data)

    # Duplicate detection within project
    dup = db.query(Source).filter(Source.project_id == project_id, Source.content_hash == chash).first()
    if dup:
        raise HTTPException(409, f"A source with identical content already exists: {dup.filename} ({dup.id}).")

    source_id = _next_source_id(project_id, db)
    dest = _stored_path(project_id, source_id, suffix)
    dest.write_bytes(data)

    source = Source(
        id=source_id,
        project_id=project_id,
        type=source_type,
        filename=safe_name,
        clearance_level=clearance_level,
        status="queued",
        content_hash=chash,
        file_path=str(dest),
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    # Queue background parsing
    background_tasks.add_task(run_parse_job, source_id)

    chunk_count = 0
    return SourceResponse(
        id=source.id, project_id=source.project_id, type=source.type, filename=source.filename,
        clearance_level=source.clearance_level, status=source.status, error_message=source.error_message,
        uploaded_at=source.uploaded_at, source_timestamp=source.source_timestamp,
        content_hash=source.content_hash, chunk_count=chunk_count,
    )


# ── GitHub import ─────────────────────────────────────────────────────────────

@router.post("/{project_id}/sources/github", response_model=SourceResponse, status_code=201)
def import_github(
    project_id: str,
    body: GithubImportRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, membership = _get_project_scoped(project_id, current_user.id, db)

    if body.clearance_level not in CLEARANCE_LEVELS:
        raise HTTPException(400, f"Invalid clearance level. Choose from: {', '.join(CLEARANCE_LEVELS)}")
    if body.clearance_level == "restricted" and membership.role != "admin":
        raise HTTPException(403, "Only admins can assign restricted clearance.")

    # Parse owner/repo from URL
    match = re.search(r"github\.com[:/]([^/]+)/([^/.\s]+?)(?:\.git)?$", body.repo_url.strip())
    if not match:
        raise HTTPException(400, "Invalid GitHub URL. Expected format: https://github.com/owner/repo")
    owner, repo = match.group(1), match.group(2)

    existing_count = db.query(Source).filter(Source.project_id == project_id).count()
    if existing_count >= MAX_SOURCES_PER_PROJECT:
        raise HTTPException(400, f"Project has reached the maximum of {MAX_SOURCES_PER_PROJECT} sources.")

    source_id = _next_source_id(project_id, db)
    source = Source(
        id=source_id,
        project_id=project_id,
        type="github_commits",
        filename=f"github:{owner}/{repo}",
        clearance_level=body.clearance_level,
        status="queued",
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    def _do_import(src_id: str) -> None:
        from app.db import SessionLocal
        _db = SessionLocal()
        try:
            _src = _db.get(Source, src_id)
            if not _src:
                return
            _src.status = "parsing"
            _db.commit()
            try:
                commits = fetch_commits(owner, repo) if body.fetch_commits else []
                prs = fetch_pull_requests(owner, repo) if body.fetch_prs else []
                issues = fetch_issues(owner, repo) if body.fetch_issues else []
                items = github_items_to_chunks(commits, prs, issues)
                if not items:
                    _src.status = "failed"
                    _src.error_message = "Repository appears to be empty or has no accessible content."
                else:
                    _persist_chunks(src_id, items, _db)
                    _src.status = "parsed"
                    _src.error_message = None
            except Exception as exc:
                _src.status = "failed"
                _src.error_message = str(exc)[:2000]
            _db.commit()
        finally:
            _db.close()

    background_tasks.add_task(_do_import, source_id)

    return SourceResponse(
        id=source.id, project_id=source.project_id, type=source.type, filename=source.filename,
        clearance_level=source.clearance_level, status=source.status, error_message=source.error_message,
        uploaded_at=source.uploaded_at, source_timestamp=source.source_timestamp,
        content_hash=source.content_hash, chunk_count=0,
    )


# ── Manual entry ──────────────────────────────────────────────────────────────

@router.post("/{project_id}/sources/manual", response_model=SourceResponse, status_code=201)
def add_manual_source(
    project_id: str,
    body: ManualEntryRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, membership = _get_project_scoped(project_id, current_user.id, db)

    if body.clearance_level not in CLEARANCE_LEVELS:
        raise HTTPException(400, f"Invalid clearance level. Choose from: {', '.join(CLEARANCE_LEVELS)}")
    if body.clearance_level == "restricted" and membership.role != "admin":
        raise HTTPException(403, "Only admins can assign restricted clearance.")

    if not body.title.strip():
        raise HTTPException(400, "Title cannot be blank.")
    if not body.content.strip():
        raise HTTPException(400, "Content cannot be blank.")

    existing_count = db.query(Source).filter(Source.project_id == project_id).count()
    if existing_count >= MAX_SOURCES_PER_PROJECT:
        raise HTTPException(400, f"Project has reached the maximum of {MAX_SOURCES_PER_PROJECT} sources.")

    source_id = _next_source_id(project_id, db)
    source = Source(
        id=source_id,
        project_id=project_id,
        type="manual",
        filename=body.title.strip()[:255],
        clearance_level=body.clearance_level,
        status="parsed",  # Manual entries are immediately parsed
        content_hash=hashlib.sha256(body.content.encode()).hexdigest(),
    )
    db.add(source)
    db.flush()

    chunk = Chunk(
        source_id=source_id,
        ordinal=1,
        text=body.content.strip(),
        author=body.author or current_user.name,
        timestamp=datetime.now(timezone.utc),
        locator="manual",
    )
    db.add(chunk)
    db.commit()
    db.refresh(source)

    return SourceResponse(
        id=source.id, project_id=source.project_id, type=source.type, filename=source.filename,
        clearance_level=source.clearance_level, status=source.status, error_message=source.error_message,
        uploaded_at=source.uploaded_at, source_timestamp=source.source_timestamp,
        content_hash=source.content_hash, chunk_count=1,
    )


# ── Retry parsing ─────────────────────────────────────────────────────────────

@router.post("/{project_id}/sources/{source_id}/retry", response_model=SourceResponse)
def retry_source(
    project_id: str,
    source_id: str,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, membership = _get_project_scoped(project_id, current_user.id, db)
    source = db.query(Source).filter(Source.project_id == project_id, Source.id == source_id).first()
    if not source:
        raise HTTPException(404, "Source not found.")
    if source.status not in ("failed", "queued"):
        raise HTTPException(400, f"Cannot retry a source with status '{source.status}'.")

    source.status = "queued"
    db.commit()
    background_tasks.add_task(run_parse_job, source_id)

    chunk_count = db.query(Chunk).filter(Chunk.source_id == source_id).count()
    return SourceResponse(
        id=source.id, project_id=source.project_id, type=source.type, filename=source.filename,
        clearance_level=source.clearance_level, status=source.status, error_message=source.error_message,
        uploaded_at=source.uploaded_at, source_timestamp=source.source_timestamp,
        content_hash=source.content_hash, chunk_count=chunk_count,
    )


# ── Delete source ─────────────────────────────────────────────────────────────

@router.delete("/{project_id}/sources/{source_id}", status_code=204)
def delete_source(
    project_id: str,
    source_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, membership = _get_project_scoped(project_id, current_user.id, db)
    if membership.role not in ("admin",):
        raise HTTPException(403, "Only admins can delete sources.")

    source = db.query(Source).filter(Source.project_id == project_id, Source.id == source_id).first()
    if not source:
        raise HTTPException(404, "Source not found.")

    # Delete stored file if it exists
    if source.file_path:
        fp = Path(source.file_path)
        if fp.exists():
            try:
                fp.unlink()
            except OSError:
                pass  # Log and continue — don't fail the delete

    db.delete(source)
    db.commit()


# ── Load Atlas sample data ─────────────────────────────────────────────────────

@router.post("/{project_id}/sample", status_code=201)
def load_sample(
    project_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Load Atlas Workspace sample data into this project. Admin only."""
    project, membership = _get_project_scoped(project_id, current_user.id, db)
    if membership.role != "admin":
        raise HTTPException(403, "Only admins can load sample data.")

    from app.services.seed import load_atlas_sample
    result = load_atlas_sample(db, project_id)
    return {"message": "Atlas sample data loaded.", **result}


