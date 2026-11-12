"""Normalise stage: load parsed chunks for a project and attach honest dates."""

import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.engine.types import DOC_SOURCE_TYPES, NChunk, SourceInfo, ensure_utc
from app.models import Chunk, Source

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_LONG = re.compile(r"\b(" + "|".join(m.capitalize() for m in _MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")


def find_date(text: str) -> Optional[datetime]:
    """First explicit calendar date in the text (ISO or 'October 08, 2026'), or None."""
    cands: List[Tuple[int, datetime]] = []
    m = _ISO.search(text)
    if m:
        try:
            cands.append((m.start(), datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc)))
        except ValueError:
            pass
    m = _LONG.search(text)
    if m:
        try:
            cands.append((m.start(), datetime(int(m[3]), _MONTHS[m[1].lower()], int(m[2]), tzinfo=timezone.utc)))
        except ValueError:
            pass
    return min(cands, key=lambda c: c[0])[1] if cands else None


def load_chunks(db: Session, project_id: str) -> Tuple[List[NChunk], Dict[str, SourceInfo], Dict[str, int]]:
    """Return (chunks, sources, stats) for parsed sources only.

    Document chunks without their own timestamp inherit the most recent date seen earlier in
    the same source (e.g. meeting notes with a dated heading). Those are flagged ts_inferred.
    Upload/file-modified time is never used as an event time.
    """
    all_sources = db.query(Source).filter(Source.project_id == project_id).all()
    parsed = [s for s in all_sources if s.status == "parsed"]
    sources = {s.id: SourceInfo(s.id, s.filename, s.type, s.clearance_level) for s in parsed}
    stats = {"sources_total": len(all_sources), "sources_parsed": len(parsed),
             "sources_skipped": len(all_sources) - len(parsed)}

    chunks: List[NChunk] = []
    for s in parsed:
        rows = db.query(Chunk).filter(Chunk.source_id == s.id).order_by(Chunk.ordinal).all()
        running: Optional[datetime] = None
        for r in rows:
            ts = ensure_utc(r.timestamp)
            inferred = False
            if ts is None and s.type in (DOC_SOURCE_TYPES | {"csv"}):
                own = find_date(r.text)
                if own is not None:
                    running = own
                    ts, inferred = own, False  # date written in the chunk itself
                elif running is not None and s.type in DOC_SOURCE_TYPES:
                    ts, inferred = running, True
            elif ts is not None:
                running = ts
            chunks.append(NChunk(
                id=r.id, source_id=s.id, source_type=s.type, filename=s.filename,
                clearance=s.clearance_level, text=r.text, author=r.author, timestamp=ts,
                locator=r.locator, ordinal=r.ordinal, ts_inferred=inferred,
            ))
    stats["chunks"] = len(chunks)
    return chunks, sources, stats
