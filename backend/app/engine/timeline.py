"""Chronological timeline builder from source timestamps and locators."""

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.engine.normalise import load_chunks
from app.engine.types import CLEARANCE_ORDER, HIDDEN_ROLES, module_name
from app.models import ModuleAlias


def build_timeline(
    db: Session,
    project_id: str,
    role: str,
) -> List[Dict[str, Any]]:
    """Return chronological events derived strictly from parsed chunks that have a timestamp.

    Respects role clearance: restricted sources are excluded for incoming/departing roles.
    """
    chunks, _, _ = load_chunks(db, project_id)
    aliases = {
        a.alias: a.target
        for a in db.query(ModuleAlias).filter(ModuleAlias.project_id == project_id).all()
    }

    from app.engine.extract import guess_module_from_text_or_paths

    events: List[Dict[str, Any]] = []
    for ch in chunks:
        if role in HIDDEN_ROLES and ch.clearance == "restricted":
            continue
        if ch.timestamp is None:
            continue

        first_line = ch.text.splitlines()[0].strip() if ch.text else ""
        mod = guess_module_from_text_or_paths(ch.text) or "general"
        mod = module_name(aliases.get(mod, mod)) or "general"

        events.append({
            "chunk_id": ch.id,
            "source_id": ch.source_id,
            "source_filename": ch.filename,
            "source_type": ch.source_type,
            "locator": ch.locator,
            "author": ch.author,
            "timestamp": ch.timestamp,
            "timestamp_inferred": ch.ts_inferred,
            "module": mod,
            "clearance_level": ch.clearance,
            "summary": first_line[:220],
        })

    events.sort(key=lambda e: (e["timestamp"], e["source_id"], e["locator"] or ""))
    return events
