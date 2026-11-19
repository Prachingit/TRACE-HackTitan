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
from app.engine.clearance import (
    ClearanceError,
    can_view_source,
    filter_chunks,
    filter_claims,
    filter_sources,
    resolve_viewer_profile,
)
from app.engine.living import (
    apply_version,
    create_pending_version,
    ensure_baseline,
    items_hash,
    latest_version,
    normalize_items,
    record_initial_version,
    serialize_change,
    utcnow,
)
from app.models import (
    Chunk,
    Claim,
    Membership,
    Project,
    Source,
    SourceChange,
    SourceVersion,
    SourceVersionChunk,
    User,
)
from app.services.background import parse_source, run_parse_job
from app.services.github import (
    fetch_commits,
    fetch_issues,
    fetch_pull_requests,
    github_items_to_chunks,
)
from app.services.background import _persist_chunks

router = APIRouter(prefix="/api/projects", tags=["Sources"])
versions_router = APIRouter(tags=["Sources"])

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
    version_number: int = 1
    is_new_version: bool = False

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


def _resolve_viewer(user: CurrentUser, role: str, view_as: Optional[str]):
    try:
        return resolve_viewer_profile(user.id, user.name, role, view_as)
    except ClearanceError as exc:
        raise HTTPException(exc.status_code, str(exc))


def _source_response(source: Source, db: Session, *, is_new_version: bool = False) -> SourceResponse:
    chunk_count = db.query(Chunk).filter(Chunk.source_id == source.id).count()
    latest = latest_version(db, source.id)
    v_num = latest.version_number if latest else 1
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
        version_number=v_num,
        is_new_version=is_new_version,
    )


# ── List sources ──────────────────────────────────────────────────────────────

@router.get("/{project_id}/sources", response_model=List[SourceResponse])
def list_sources(
    project_id: str,
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, membership = _get_project_scoped(project_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, membership.role, view_as)
    all_sources = (
        db.query(Source)
        .filter(Source.project_id == project_id)
        .order_by(Source.uploaded_at.desc())
        .all()
    )
    sources = filter_sources(viewer, all_sources)
    return [_source_response(s, db) for s in sources]


# ── Source detail ─────────────────────────────────────────────────────────────

@router.get("/{project_id}/sources/{source_id}", response_model=SourceResponse)
def get_source(
    project_id: str,
    source_id: str,
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, membership = _get_project_scoped(project_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, membership.role, view_as)
    source = db.query(Source).filter(Source.project_id == project_id, Source.id == source_id).first()
    if not source or not can_view_source(viewer, source):
        raise HTTPException(404, "Source not found.")
    return _source_response(source, db)


# ── Chunks ────────────────────────────────────────────────────────────────────

@router.get("/{project_id}/sources/{source_id}/chunks", response_model=List[ChunkResponse])
def get_chunks(
    project_id: str,
    source_id: str,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, membership = _get_project_scoped(project_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, membership.role, view_as)
    source = db.query(Source).filter(Source.project_id == project_id, Source.id == source_id).first()
    if not source or not can_view_source(viewer, source):
        raise HTTPException(404, "Source not found.")
    chunks = (
        db.query(Chunk)
        .filter(Chunk.source_id == source_id)
        .order_by(Chunk.ordinal)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [ChunkResponse.model_validate(c) for c in filter_chunks(viewer, chunks, source)]


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
        raise HTTPException(
            409,
            f"No new version created: identical content already exists in {dup.filename} ({dup.id}).",
        )

    # Re-upload of an existing filename creates a new version of that source instead of a duplicate.
    existing_same_name = (
        db.query(Source)
        .filter(Source.project_id == project_id, Source.filename == safe_name)
        .first()
    )
    if existing_same_name:
        if existing_same_name.clearance_level == "restricted" and membership.role != "admin":
            raise HTTPException(403, "Only admins can update a restricted source.")
        base = ensure_baseline(db, existing_same_name, user_id=current_user.id)
        next_v = (base.version_number if base else 1) + 1
        dest = _stored_path(project_id, f"{existing_same_name.id}_v{next_v}", suffix)
        dest.write_bytes(data)
        create_pending_version(
            db,
            existing_same_name,
            content_hash=chash,
            file_path=str(dest),
            user_id=current_user.id,
            origin="reupload",
        )
        existing_same_name.status = "queued"
        existing_same_name.error_message = None
        db.commit()
        db.refresh(existing_same_name)
        background_tasks.add_task(run_parse_job, existing_same_name.id)
        return _source_response(existing_same_name, db, is_new_version=True)

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

    return _source_response(source, db)


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

    fname = f"github:{owner}/{repo}"
    existing = (
        db.query(Source)
        .filter(Source.project_id == project_id, Source.filename == fname, Source.type == "github_commits")
        .first()
    )
    is_resync = existing is not None
    if existing is not None:
        if existing.clearance_level == "restricted" and membership.role != "admin":
            raise HTTPException(403, "Only admins can re-sync a restricted source.")
        source = existing
        source.status = "queued"
        source.error_message = None
        db.commit()
        db.refresh(source)
    else:
        existing_count = db.query(Source).filter(Source.project_id == project_id).count()
        if existing_count >= MAX_SOURCES_PER_PROJECT:
            raise HTTPException(400, f"Project has reached the maximum of {MAX_SOURCES_PER_PROJECT} sources.")
        source_id = _next_source_id(project_id, db)
        source = Source(
            id=source_id,
            project_id=project_id,
            type="github_commits",
            filename=fname,
            clearance_level=body.clearance_level,
            status="queued",
        )
        db.add(source)
        db.commit()
        db.refresh(source)

    source_id = source.id
    actor_id = current_user.id

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
                    norm = normalize_items(items)
                    new_hash = items_hash(norm)
                    if is_resync and _src.content_hash == new_hash:
                        _src.status = "parsed"
                        _src.error_message = None
                    elif is_resync:
                        ensure_baseline(_db, _src, user_id=actor_id)
                        pv = create_pending_version(
                            _db, _src, content_hash=new_hash, file_path=None, user_id=actor_id, origin="github_resync"
                        )
                        apply_version(_db, _src, pv, norm)
                        _src.content_hash = new_hash
                        _src.status = "parsed"
                        _src.error_message = None
                        _src.uploaded_at = utcnow()
                    else:
                        _persist_chunks(src_id, items, _db)
                        _db.flush()
                        _src.content_hash = new_hash
                        _src.status = "parsed"
                        _src.error_message = None
                        record_initial_version(_db, _src, origin="initial", user_id=actor_id, content_hash=new_hash)
            except Exception as exc:
                _src.status = "failed"
                _src.error_message = str(exc)[:2000]
            _db.commit()
        finally:
            _db.close()

    background_tasks.add_task(_do_import, source_id)

    return _source_response(source, db, is_new_version=is_resync)


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

    title = body.title.strip()[:255]
    content = body.content.strip()
    chash = hashlib.sha256(content.encode()).hexdigest()

    existing = (
        db.query(Source)
        .filter(Source.project_id == project_id, Source.filename == title, Source.type == "manual")
        .first()
    )
    if existing:
        if existing.clearance_level == "restricted" and membership.role != "admin":
            raise HTTPException(403, "Only admins can update a restricted source.")
        if existing.content_hash == chash:
            raise HTTPException(409, f"No new version created: identical content already exists in '{title}'.")
        ensure_baseline(db, existing, user_id=current_user.id)
        pv = create_pending_version(
            db, existing, content_hash=chash, file_path=None, user_id=current_user.id, origin="manual_edit"
        )
        apply_version(
            db,
            existing,
            pv,
            [(1, content, "manual", body.author or current_user.name, utcnow())],
        )
        existing.content_hash = chash
        existing.uploaded_at = utcnow()
        db.commit()
        db.refresh(existing)
        return _source_response(existing, db, is_new_version=True)

    existing_count = db.query(Source).filter(Source.project_id == project_id).count()
    if existing_count >= MAX_SOURCES_PER_PROJECT:
        raise HTTPException(400, f"Project has reached the maximum of {MAX_SOURCES_PER_PROJECT} sources.")

    source_id = _next_source_id(project_id, db)
    source = Source(
        id=source_id,
        project_id=project_id,
        type="manual",
        filename=title,
        clearance_level=body.clearance_level,
        status="parsed",  # Manual entries are immediately parsed
        content_hash=chash,
    )
    db.add(source)
    db.flush()

    chunk = Chunk(
        source_id=source_id,
        ordinal=1,
        text=content,
        author=body.author or current_user.name,
        timestamp=utcnow(),
        locator="manual",
    )
    db.add(chunk)
    db.flush()
    record_initial_version(db, source, origin="initial", user_id=current_user.id, content_hash=chash)
    db.commit()
    db.refresh(source)

    return _source_response(source, db)


@router.patch("/{project_id}/sources/{source_id}/manual", response_model=SourceResponse)
def update_manual_source(
    project_id: str,
    source_id: str,
    body: ManualEntryRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Edit an existing manual entry, creating a new SourceVersion and flagging stale claims."""
    _, membership = _get_project_scoped(project_id, current_user.id, db)
    source = db.query(Source).filter(Source.project_id == project_id, Source.id == source_id).first()
    if not source or source.type != "manual":
        raise HTTPException(404, "Manual source not found.")
    if source.clearance_level == "restricted" and membership.role != "admin":
        raise HTTPException(403, "Only admins can update a restricted source.")
    content = body.content.strip()
    if not content:
        raise HTTPException(400, "Content cannot be blank.")
    chash = hashlib.sha256(content.encode()).hexdigest()
    if source.content_hash == chash:
        raise HTTPException(409, f"No new version created: identical content already exists in '{source.filename}'.")

    ensure_baseline(db, source, user_id=current_user.id)
    pv = create_pending_version(
        db, source, content_hash=chash, file_path=None, user_id=current_user.id, origin="manual_edit"
    )
    apply_version(
        db,
        source,
        pv,
        [(1, content, "manual", body.author or current_user.name, utcnow())],
    )
    if body.title and body.title.strip():
        source.filename = body.title.strip()[:255]
    source.content_hash = chash
    source.uploaded_at = utcnow()
    db.commit()
    db.refresh(source)
    return _source_response(source, db, is_new_version=True)


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

    if source.type not in ("manual", "github") and (not source.file_path or not Path(source.file_path).exists()):
        raise HTTPException(
            409,
            "Uploaded file is no longer on disk (ephemeral storage was reset after a restart). Please re-upload the file.",
        )

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


# ── Living Handover: Source Versions & Project Changes ────────────────────────

def _serialize_version(db: Session, v: SourceVersion, include_chunks: bool = True) -> dict:
    uploader = db.get(User, v.uploaded_by) if v.uploaded_by else None
    payload = {
        "id": v.id,
        "source_id": v.source_id,
        "project_id": v.project_id,
        "version_number": v.version_number,
        "content_hash": v.content_hash,
        "status": v.status,
        "origin": v.origin,
        "uploaded_by": v.uploaded_by,
        "uploaded_by_name": uploader.name if uploader else None,
        "chunk_count": v.chunk_count,
        "added_count": v.added_count,
        "removed_count": v.removed_count,
        "modified_count": v.modified_count,
        "error_message": v.error_message,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }
    if include_chunks:
        snaps = (
            db.query(SourceVersionChunk)
            .filter(SourceVersionChunk.version_id == v.id)
            .order_by(SourceVersionChunk.ordinal.asc(), SourceVersionChunk.id.asc())
            .all()
        )
        payload["chunks"] = [
            {
                "id": ch.id,
                "chunk_id": ch.chunk_id,
                "ordinal": ch.ordinal,
                "text": ch.text,
                "locator": ch.locator,
                "author": ch.author,
                "timestamp": ch.timestamp.isoformat() if ch.timestamp else None,
            }
            for ch in snaps
        ]
    return payload


@versions_router.get("/api/sources/{source_id}/versions")
def get_source_versions(
    source_id: str,
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List immutable versions (with readable chunk snapshots) for a source, enforcing clearance."""
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found.")
    _, membership = _get_project_scoped(source.project_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, membership.role, view_as)
    if not can_view_source(viewer, source):
        raise HTTPException(404, "Source not found.")

    ensure_baseline(db, source)
    db.commit()
    versions = (
        db.query(SourceVersion)
        .filter(SourceVersion.source_id == source.id)
        .order_by(SourceVersion.version_number.desc())
        .all()
    )
    return {
        "source": _source_response(source, db).model_dump(),
        "versions": [_serialize_version(db, v, include_chunks=True) for v in versions],
    }


@router.get("/{project_id}/changes")
def get_project_changes(
    project_id: str,
    source_id: Optional[str] = Query(default=None),
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return source versions, chunk-level changes, and affected claims for a project (clearance-filtered)."""
    _, membership = _get_project_scoped(project_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, membership.role, view_as)

    all_sources = db.query(Source).filter(Source.project_id == project_id).all()
    visible_sources = {s.id: s for s in filter_sources(viewer, all_sources)}
    visible_ids = list(visible_sources.keys())

    if source_id and source_id not in visible_ids:
        raise HTTPException(404, "Source not found.")
    target_ids = [source_id] if source_id else visible_ids

    versions_out = []
    versions_by_id = {}
    if target_ids:
        v_rows = (
            db.query(SourceVersion)
            .filter(SourceVersion.source_id.in_(target_ids))
            .order_by(SourceVersion.created_at.desc(), SourceVersion.version_number.desc())
            .all()
        )
        versions_by_id = {v.id: v for v in v_rows}
        for v in v_rows:
            d = _serialize_version(db, v, include_chunks=False)
            src = visible_sources.get(v.source_id)
            d["source_filename"] = src.filename if src else v.source_id
            d["source_type"] = src.type if src else None
            d["clearance_level"] = src.clearance_level if src else None
            versions_out.append(d)

    changes_out = []
    if target_ids:
        ch_rows = (
            db.query(SourceChange)
            .filter(SourceChange.project_id == project_id, SourceChange.source_id.in_(target_ids))
            .order_by(SourceChange.created_at.desc(), SourceChange.id.asc())
            .all()
        )
        for ch in ch_rows:
            changes_out.append(
                serialize_change(db, ch, visible_sources.get(ch.source_id), versions_by_id)
            )

    all_claims = db.query(Claim).filter(Claim.project_id == project_id).all()
    visible_claims = filter_claims(db, viewer, all_claims)
    stale_claims = [c for c in visible_claims if c.is_stale]
    affected_claims = [c for c in visible_claims if c.possibly_affected and not c.is_stale]

    return {
        "project_id": project_id,
        "versions": versions_out,
        "changes": changes_out,
        "stale_claims_count": len(stale_claims),
        "possibly_affected_count": len(affected_claims),
        "affected_claims": [
            {
                "id": c.id,
                "title": c.title or c.text[:90],
                "text": c.text,
                "module": c.module,
                "verification_status": c.verification_status,
                "review_status": c.review_status,
                "clearance_level": c.clearance_level,
                "is_stale": bool(c.is_stale),
                "stale_reason": c.stale_reason,
                "possibly_affected": bool(c.possibly_affected),
                "affected_reason": c.affected_reason,
            }
            for c in (stale_claims + affected_claims)
        ],
    }


