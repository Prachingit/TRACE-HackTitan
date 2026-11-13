"""Background parsing dispatcher for TRACE sources."""

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

from sqlalchemy.orm import Session

from app.models import Chunk, Source
from app.parsers import csv_parser, docx_parser, json_parser, pdf_parser, text_md


def parse_source(source_id: str, db: Session) -> None:
    """
    Parse a source identified by source_id.
    Sets status to 'parsing' at start, 'parsed' on success, 'failed' on error.
    Idempotent: re-running clears existing chunks and re-parses.
    """
    source = db.get(Source, source_id)
    if not source:
        return

    # Mark as parsing
    source.status = "parsing"
    source.error_message = None
    db.commit()

    try:
        # Delete existing chunks (idempotent retry)
        db.query(Chunk).filter(Chunk.source_id == source_id).delete()
        db.flush()

        file_path = source.file_path
        if not file_path or not Path(file_path).exists():
            raise FileNotFoundError(
                f"Uploaded file is no longer on disk (ephemeral storage was reset): {file_path}. Please re-upload the file."
            )

        raw_chunks = _dispatch(source.type, file_path)
        _persist_chunks(source_id, raw_chunks, db)

        source.status = "parsed"
        source.error_message = None

    except Exception as exc:
        source.status = "failed"
        source.error_message = str(exc)[:2000]

    db.commit()


def _dispatch(source_type: str, file_path: str) -> List:
    """Route to the correct parser based on source type."""
    if source_type in ("markdown", "txt"):
        return text_md.parse_text(file_path)
    elif source_type == "pdf":
        return pdf_parser.parse_pdf(file_path)
    elif source_type in ("docx",):
        return docx_parser.parse_docx(file_path)
    elif source_type == "csv":
        raw = csv_parser.parse_csv(file_path)
        return raw
    elif source_type in ("chat_json", "json"):
        raw = json_parser.parse_json(file_path)
        return raw
    elif source_type == "manual":
        # Manual entries are already stored as a single chunk at registration time
        return []
    else:
        raise ValueError(f"No parser registered for source type '{source_type}'.")


def _persist_chunks(source_id: str, raw_chunks: List, db: Session) -> None:
    for item in raw_chunks:
        # Normalize to common structure: (ordinal, text, locator[, author, timestamp])
        ordinal = item[0]
        text = item[1]
        locator = item[2] if len(item) > 2 else None
        author = item[3] if len(item) > 3 else None
        ts_raw = item[4] if len(item) > 4 else None

        ts: datetime | None = None
        if ts_raw:
            try:
                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                ts = None

        chunk = Chunk(
            source_id=source_id,
            ordinal=ordinal,
            text=text[:8000],  # Guard against huge single chunks
            author=str(author)[:128] if author else None,
            timestamp=ts,
            locator=str(locator)[:255] if locator else None,
        )
        db.add(chunk)


def reset_stuck_sources(db: Session) -> int:
    """Reset any sources stuck in 'parsing' state back to 'queued' on startup."""
    stuck = db.query(Source).filter(Source.status == "parsing").all()
    for source in stuck:
        source.status = "queued"
    db.commit()
    return len(stuck)


def run_parse_job(source_id: str) -> None:
    """Entry point for BackgroundTasks: opens its own session (request session is closed by then)."""
    from app import db as db_module

    session = db_module.SessionLocal()
    try:
        parse_source(source_id, session)
    finally:
        session.close()
