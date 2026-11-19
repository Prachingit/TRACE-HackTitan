"""Living Handover engine (Round 3): source versioning, chunk-level change detection, stale-claim flags,
handover version lineage, freshness, and version diffs.

Rules enforced here:
- Change detection is deterministic (exact text, then locator + similarity, then best similarity).
- Old versions keep a read-only chunk snapshot, so diffs stay readable after the live chunks change.
- A claim whose cited chunk is removed or modified is flagged STALE (separate from verification/review status).
  Nothing here approves, rejects, edits, or deletes a claim.
- Approved handovers are never modified; a new version is a new Handover row linked by lineage.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.engine.types import norm_ws
from app.models import (
    Chunk,
    Claim,
    ClaimEvidence,
    Handover,
    ReviewEvent,
    Source,
    SourceChange,
    SourceVersion,
    SourceVersionChunk,
    User,
)

APPROVED_HANDOVER_STATUSES = ("approved", "shared", "acknowledged")
EDITABLE_HANDOVER_STATUSES = ("draft", "in_review")

LOCATOR_MATCH_THRESHOLD = 0.5
SIMILARITY_MATCH_THRESHOLD = 0.6


class ImmutableHandoverError(ValueError):
    """Raised when something tries to modify an approved handover version."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_iso(raw: Any) -> Optional[datetime]:
    if not raw or not isinstance(raw, str):
        return None
    try:
        return to_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        return None


def _json_list(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        val = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return [str(v) for v in val] if isinstance(val, list) else []


def _json_obj(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            val = json.loads(raw)
            return val if isinstance(val, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def items_hash(items: Sequence[Dict[str, Any]]) -> str:
    """Content hash over normalised chunk items (used for GitHub re-sync and manual edits)."""
    joined = "\n\u241e\n".join(f"{it.get('locator') or ''}\u241f{it['text']}" for it in items)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


# ── Chunk item normalisation ─────────────────────────────────────────────────

def normalize_items(raw_chunks: Iterable[Sequence[Any]]) -> List[Dict[str, Any]]:
    """Parser tuples (ordinal, text, locator[, author, timestamp]) -> dicts used for persistence and diffing."""
    out: List[Dict[str, Any]] = []
    for item in raw_chunks:
        ordinal = item[0]
        text = (item[1] or "")[:8000]
        locator = item[2] if len(item) > 2 else None
        author = item[3] if len(item) > 3 else None
        ts_raw = item[4] if len(item) > 4 else None
        ts: Optional[datetime] = None
        if isinstance(ts_raw, datetime):
            ts = ts_raw
        elif ts_raw:
            try:
                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                ts = None
        out.append(
            {
                "ordinal": int(ordinal) if ordinal is not None else len(out) + 1,
                "text": text,
                "locator": str(locator)[:255] if locator else None,
                "author": str(author)[:128] if author else None,
                "timestamp": ts,
            }
        )
    return out


# ── Deterministic chunk matching ─────────────────────────────────────────────

@dataclass(frozen=True)
class ChunkMatch:
    change_type: str  # unchanged | modified | removed | added
    old_index: Optional[int]
    new_index: Optional[int]
    similarity: float


def similarity(a: str, b: str) -> float:
    na, nb = norm_ws(a or ""), norm_ws(b or "")
    if not na and not nb:
        return 1.0
    sm = difflib.SequenceMatcher(a=na, b=nb, autojunk=False)
    if sm.real_quick_ratio() < 0.2:
        return round(sm.real_quick_ratio(), 4)
    return round(sm.ratio(), 4)


def match_chunks(
    old: Sequence[Tuple[str, Optional[str]]],
    new: Sequence[Tuple[str, Optional[str]]],
) -> List[ChunkMatch]:
    """Match old chunks to new chunks. Inputs are (text, locator) tuples.

    1. Exact (whitespace-normalised) text match, preferring the same locator -> unchanged.
    2. Same non-empty locator with similarity >= 0.5 -> modified.
    3. Remaining pairs by best similarity >= 0.6 (greedy, highest first) -> modified.
    4. Leftovers -> removed (old) / added (new).
    """
    matches: List[ChunkMatch] = []
    used_old: Set[int] = set()
    used_new: Set[int] = set()

    by_text: Dict[str, List[int]] = {}
    for i, (txt, _loc) in enumerate(old):
        by_text.setdefault(norm_ws(txt or ""), []).append(i)

    for j, (txt, loc) in enumerate(new):
        cands = [i for i in by_text.get(norm_ws(txt or ""), []) if i not in used_old]
        if not cands:
            continue
        pick = next((i for i in cands if old[i][1] == loc), cands[0])
        used_old.add(pick)
        used_new.add(j)
        matches.append(ChunkMatch("unchanged", pick, j, 1.0))

    old_by_loc: Dict[str, List[int]] = {}
    for i, (_txt, loc) in enumerate(old):
        if i not in used_old and loc:
            old_by_loc.setdefault(loc, []).append(i)
    for j, (txt, loc) in enumerate(new):
        if j in used_new or not loc:
            continue
        cands = [i for i in old_by_loc.get(loc, []) if i not in used_old]
        if not cands:
            continue
        best_i, best_s = None, -1.0
        for i in cands:
            s = similarity(old[i][0], txt)
            if s > best_s:
                best_i, best_s = i, s
        if best_i is not None and best_s >= LOCATOR_MATCH_THRESHOLD:
            used_old.add(best_i)
            used_new.add(j)
            matches.append(ChunkMatch("modified", best_i, j, best_s))

    rem_old = [i for i in range(len(old)) if i not in used_old]
    rem_new = [j for j in range(len(new)) if j not in used_new]
    scored: List[Tuple[float, int, int]] = []
    for i in rem_old:
        for j in rem_new:
            s = similarity(old[i][0], new[j][0])
            if s >= SIMILARITY_MATCH_THRESHOLD:
                scored.append((s, i, j))
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    for s, i, j in scored:
        if i in used_old or j in used_new:
            continue
        used_old.add(i)
        used_new.add(j)
        matches.append(ChunkMatch("modified", i, j, s))

    for i in range(len(old)):
        if i not in used_old:
            matches.append(ChunkMatch("removed", i, None, 0.0))
    for j in range(len(new)):
        if j not in used_new:
            matches.append(ChunkMatch("added", None, j, 0.0))
    return matches


# ── Source versions ──────────────────────────────────────────────────────────

def latest_version(db: Session, source_id: str, status: Optional[str] = "applied") -> Optional[SourceVersion]:
    q = db.query(SourceVersion).filter(SourceVersion.source_id == source_id)
    if status:
        q = q.filter(SourceVersion.status == status)
    return q.order_by(SourceVersion.version_number.desc()).first()


def pending_version(db: Session, source_id: str) -> Optional[SourceVersion]:
    return latest_version(db, source_id, status="pending")


def _next_version_number(db: Session, source_id: str) -> int:
    cur = db.query(func.max(SourceVersion.version_number)).filter(SourceVersion.source_id == source_id).scalar()
    return int(cur or 0) + 1


def _snapshot_live_chunks(db: Session, source: Source, version: SourceVersion) -> int:
    rows = db.query(Chunk).filter(Chunk.source_id == source.id).order_by(Chunk.ordinal.asc(), Chunk.id.asc()).all()
    for ch in rows:
        db.add(
            SourceVersionChunk(
                version_id=version.id,
                chunk_id=ch.id,
                ordinal=ch.ordinal,
                text=ch.text,
                locator=ch.locator,
                author=ch.author,
                timestamp=ch.timestamp,
            )
        )
    version.chunk_count = len(rows)
    return len(rows)


def record_initial_version(
    db: Session,
    source: Source,
    *,
    origin: str = "initial",
    user_id: Optional[str] = None,
    content_hash: Optional[str] = None,
) -> Optional[SourceVersion]:
    """Create v1 with a snapshot of the current live chunks if the source has no versions yet (idempotent)."""
    if db.query(SourceVersion).filter(SourceVersion.source_id == source.id).first() is not None:
        return None
    v = SourceVersion(
        source_id=source.id,
        project_id=source.project_id,
        version_number=1,
        content_hash=content_hash or source.content_hash,
        status="applied",
        origin=origin,
        file_path=source.file_path,
        uploaded_by=user_id,
    )
    db.add(v)
    db.flush()
    _snapshot_live_chunks(db, source, v)
    db.flush()
    return v


def ensure_baseline(db: Session, source: Source, user_id: Optional[str] = None) -> Optional[SourceVersion]:
    """Legacy sources (parsed before versioning existed) get a v1 'baseline' snapshot before their first change."""
    existing = latest_version(db, source.id)
    if existing is not None:
        return existing
    if db.query(SourceVersion).filter(SourceVersion.source_id == source.id).first() is not None:
        return None  # only pending/failed rows exist; caller decides
    return record_initial_version(db, source, origin="baseline", user_id=user_id)


def create_pending_version(
    db: Session,
    source: Source,
    *,
    content_hash: Optional[str],
    file_path: Optional[str],
    user_id: Optional[str],
    origin: str,
) -> SourceVersion:
    # A stale pending row from a crashed job is marked failed so numbering stays monotonic.
    for old in db.query(SourceVersion).filter(SourceVersion.source_id == source.id, SourceVersion.status == "pending").all():
        old.status = "failed"
        old.error_message = "Superseded by a newer upload before it was processed."
    v = SourceVersion(
        source_id=source.id,
        project_id=source.project_id,
        version_number=_next_version_number(db, source.id),
        content_hash=content_hash,
        status="pending",
        origin=origin,
        file_path=file_path,
        uploaded_by=user_id,
    )
    db.add(v)
    db.flush()
    return v


def _locator_label(locator: Optional[str]) -> str:
    return locator or "unlabelled chunk"


def apply_version(
    db: Session,
    source: Source,
    version: SourceVersion,
    raw_items: Sequence[Sequence[Any]] | Sequence[Dict[str, Any]],
) -> Dict[str, int]:
    """Diff the new version against the previous applied version, update live chunks in place, snapshot the new
    version, store SourceChange rows, and flag stale / possibly affected claims. Does not commit."""
    items = list(raw_items)
    new_items = items if (items and isinstance(items[0], dict)) else normalize_items(items)  # type: ignore[arg-type]

    prev = latest_version(db, source.id)
    if prev is None:
        prev = ensure_baseline(db, source, user_id=version.uploaded_by)
    old_snap: List[SourceVersionChunk] = list(prev.snapshot_chunks) if prev else []

    live_by_id: Dict[str, Chunk] = {c.id: c for c in db.query(Chunk).filter(Chunk.source_id == source.id).all()}
    matches = match_chunks(
        [(s.text, s.locator) for s in old_snap],
        [(n["text"], n["locator"]) for n in new_items],
    )

    # Evidence affected by removed/modified chunks must be captured before any chunk row is deleted.
    changed_live_ids = [
        old_snap[m.old_index].chunk_id
        for m in matches
        if m.change_type in ("removed", "modified") and m.old_index is not None and old_snap[m.old_index].chunk_id
    ]
    ev_by_chunk: Dict[str, List[ClaimEvidence]] = {}
    if changed_live_ids:
        for ev in db.query(ClaimEvidence).filter(ClaimEvidence.chunk_id.in_(changed_live_ids)).all():
            ev_by_chunk.setdefault(ev.chunk_id, []).append(ev)

    new_live: Dict[int, Chunk] = {}
    pending_changes: List[Tuple[ChunkMatch, Optional[str]]] = []  # (match, live chunk id involved)
    for m in matches:
        if m.change_type in ("unchanged", "modified"):
            snap = old_snap[m.old_index]  # type: ignore[index]
            item = new_items[m.new_index]  # type: ignore[index]
            live = live_by_id.get(snap.chunk_id) if snap.chunk_id else None
            if live is None:
                live = Chunk(source_id=source.id, ordinal=item["ordinal"], text=item["text"])
                db.add(live)
            live.ordinal = item["ordinal"]
            live.text = item["text"]
            live.locator = item["locator"]
            live.author = item["author"]
            live.timestamp = item["timestamp"]
            new_live[m.new_index] = live  # type: ignore[index]
            if m.change_type == "modified":
                pending_changes.append((m, snap.chunk_id))
        elif m.change_type == "removed":
            snap = old_snap[m.old_index]  # type: ignore[index]
            live = live_by_id.get(snap.chunk_id) if snap.chunk_id else None
            if live is not None:
                db.delete(live)
            pending_changes.append((m, snap.chunk_id))
        else:  # added
            item = new_items[m.new_index]  # type: ignore[index]
            live = Chunk(
                source_id=source.id,
                ordinal=item["ordinal"],
                text=item["text"],
                locator=item["locator"],
                author=item["author"],
                timestamp=item["timestamp"],
            )
            db.add(live)
            new_live[m.new_index] = live  # type: ignore[index]
            pending_changes.append((m, None))
    db.flush()

    # Snapshot of the new version, in new order.
    snap_by_new_index: Dict[int, SourceVersionChunk] = {}
    for j, item in enumerate(new_items):
        live = new_live.get(j)
        row = SourceVersionChunk(
            version_id=version.id,
            chunk_id=live.id if live else None,
            ordinal=item["ordinal"],
            text=item["text"],
            locator=item["locator"],
            author=item["author"],
            timestamp=item["timestamp"],
        )
        db.add(row)
        snap_by_new_index[j] = row
    db.flush()

    counts = {"added": 0, "removed": 0, "modified": 0}
    change_rows: List[Tuple[SourceChange, ChunkMatch]] = []
    for m, live_id in pending_changes:
        old_row = old_snap[m.old_index] if m.old_index is not None else None
        new_row = snap_by_new_index.get(m.new_index) if m.new_index is not None else None
        sc = SourceChange(
            project_id=source.project_id,
            source_id=source.id,
            from_version_id=prev.id if prev else None,
            to_version_id=version.id,
            change_type=m.change_type,
            old_snapshot_chunk_id=old_row.id if old_row else None,
            new_snapshot_chunk_id=new_row.id if new_row else None,
            chunk_id=live_id if m.change_type != "added" else (new_row.chunk_id if new_row else None),
            similarity=m.similarity if m.change_type == "modified" else None,
        )
        db.add(sc)
        change_rows.append((sc, m))
        counts[m.change_type] += 1
    db.flush()

    version.status = "applied"
    version.chunk_count = len(new_items)
    version.added_count = counts["added"]
    version.removed_count = counts["removed"]
    version.modified_count = counts["modified"]
    version.error_message = None

    _flag_stale_claims(db, source, version, change_rows, old_snap, new_items, ev_by_chunk)
    _flag_possibly_affected(db, source, version, change_rows, new_items)
    db.flush()
    return counts


def _flag_stale_claims(
    db: Session,
    source: Source,
    version: SourceVersion,
    change_rows: List[Tuple[SourceChange, ChunkMatch]],
    old_snap: List[SourceVersionChunk],
    new_items: List[Dict[str, Any]],
    ev_by_chunk: Dict[str, List[ClaimEvidence]],
) -> Set[str]:
    now = utcnow()
    touched: Set[str] = set()
    for sc, m in change_rows:
        if sc.change_type not in ("removed", "modified") or not sc.chunk_id:
            continue
        old_row = old_snap[m.old_index] if m.old_index is not None else None
        for ev in ev_by_chunk.get(sc.chunk_id, []):
            claim = db.get(Claim, ev.claim_id)
            if claim is None:
                continue
            if sc.change_type == "removed":
                what = f"was removed in v{version.version_number}"
            else:
                still = bool(ev.excerpt) and norm_ws(ev.excerpt) in norm_ws(new_items[m.new_index]["text"])  # type: ignore[index]
                what = (
                    f"was modified in v{version.version_number} (similarity {m.similarity:.2f}; "
                    + ("the cited excerpt is still present" if still else "the cited excerpt is no longer present")
                    + ")"
                )
            loc = _locator_label(old_row.locator if old_row else None)
            # Never name a restricted source inside a reason attached to a non-restricted claim.
            if source.clearance_level == "restricted" and claim.clearance_level != "restricted":
                reason = f"A cited source changed: the cited chunk {what}."
            else:
                reason = f"{source.filename}: cited chunk '{loc}' {what}."
            ids = _json_list(claim.stale_change_ids)
            if sc.id not in ids:
                ids.append(sc.id)
            claim.stale_change_ids = json.dumps(ids)
            if not claim.is_stale:
                claim.is_stale = True
                claim.stale_since = now
                claim.stale_reason = reason
            elif reason not in (claim.stale_reason or ""):
                claim.stale_reason = f"{claim.stale_reason}; {reason}" if claim.stale_reason else reason
            touched.add(claim.id)
    return touched


_GENERIC_MODULES = {"general", "unknown", "misc", "other"}


def _flag_possibly_affected(
    db: Session,
    source: Source,
    version: SourceVersion,
    change_rows: List[Tuple[SourceChange, ChunkMatch]],
    new_items: List[Dict[str, Any]],
) -> Set[str]:
    """New chunks that mention an existing module mark that module's (non-stale) claims as possibly affected."""
    added_texts = [
        (new_items[m.new_index]["text"], new_items[m.new_index]["locator"])  # type: ignore[index]
        for sc, m in change_rows
        if sc.change_type == "added" and m.new_index is not None
    ]
    if not added_texts:
        return set()
    claims = (
        db.query(Claim)
        .filter(Claim.project_id == source.project_id, Claim.review_status != "rejected")
        .all()
    )
    modules = sorted({c.module for c in claims if c.module and c.module.lower() not in _GENERIC_MODULES and len(c.module) >= 3})
    hits: Dict[str, Tuple[str, Optional[str]]] = {}
    for mod in modules:
        variants = {mod.lower(), mod.lower().replace("_", " "), mod.lower().replace("-", " ")}
        pats = [re.compile(r"\b" + re.escape(v) + r"\b", re.IGNORECASE) for v in variants if v]
        for text, loc in added_texts:
            if any(p.search(text or "") for p in pats):
                hits[mod] = (text, loc)
                break
    touched: Set[str] = set()
    for c in claims:
        if c.is_stale or c.module not in hits:
            continue
        _text, loc = hits[c.module]
        if source.clearance_level == "restricted" and c.clearance_level != "restricted":
            continue  # do not reveal restricted content through a team-visible hint
        c.possibly_affected = True
        c.affected_reason = (
            f"New content in {source.filename} v{version.version_number} ('{_locator_label(loc)}') "
            f"mentions module '{c.module}'."
        )
        touched.add(c.id)
    return touched


def clear_stale_on_review(claim: Claim) -> bool:
    """Called when a human accepts, edits, or rejects a claim: the human decision resolves the stale flag."""
    changed = bool(claim.is_stale or claim.possibly_affected)
    claim.is_stale = False
    claim.possibly_affected = False
    return changed


# ── Stale detail for UI (old vs new excerpt) ─────────────────────────────────

def serialize_change(
    db: Session,
    sc: SourceChange,
    source: Optional[Source] = None,
    versions_by_id: Optional[Dict[str, SourceVersion]] = None,
) -> Dict[str, Any]:
    src = source or db.get(Source, sc.source_id)
    old_row = db.get(SourceVersionChunk, sc.old_snapshot_chunk_id) if sc.old_snapshot_chunk_id else None
    new_row = db.get(SourceVersionChunk, sc.new_snapshot_chunk_id) if sc.new_snapshot_chunk_id else None

    def _vnum(vid: Optional[str]) -> Optional[int]:
        if not vid:
            return None
        v = (versions_by_id or {}).get(vid) or db.get(SourceVersion, vid)
        return v.version_number if v else None

    return {
        "id": sc.id,
        "source_id": sc.source_id,
        "source_filename": src.filename if src else sc.source_id,
        "source_clearance": src.clearance_level if src else None,
        "change_type": sc.change_type,
        "from_version": _vnum(sc.from_version_id),
        "to_version": _vnum(sc.to_version_id),
        "similarity": sc.similarity,
        "old_locator": old_row.locator if old_row else None,
        "new_locator": new_row.locator if new_row else None,
        "old_text": old_row.text if old_row else None,
        "new_text": new_row.text if new_row else None,
        "created_at": sc.created_at.isoformat() if sc.created_at else None,
    }


def stale_changes_for_claim(db: Session, claim: Claim, can_see_restricted: bool) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for cid in _json_list(claim.stale_change_ids):
        sc = db.get(SourceChange, cid)
        if sc is None:
            continue
        src = db.get(Source, sc.source_id)
        if src is None or (src.clearance_level == "restricted" and not can_see_restricted):
            continue
        out.append(serialize_change(db, sc, src))
    return out


def claim_excerpts_for_claims(db: Session, claim_ids: Iterable[str]) -> Dict[str, Set[str]]:
    rows = db.query(ClaimEvidence.claim_id, ClaimEvidence.chunk_id).filter(ClaimEvidence.claim_id.in_(list(claim_ids))).all()
    out: Dict[str, Set[str]] = {}
    for cid, chid in rows:
        if chid:
            out.setdefault(cid, set()).add(chid)
    return out


# ── Handover lineage, freshness, diff ────────────────────────────────────────

def lineage_root_id(h: Handover) -> str:
    return h.lineage_id or h.id


def lineage_versions(db: Session, h: Handover) -> List[Handover]:
    root = lineage_root_id(h)
    rows = (
        db.query(Handover)
        .filter(Handover.project_id == h.project_id)
        .filter((Handover.lineage_id == root) | (Handover.id == root))
        .all()
    )
    return sorted(rows, key=lambda r: (r.version_number or 1, to_utc(r.created_at) or utcnow()))


def snapshot_claims(h: Handover) -> Dict[str, Dict[str, Any]]:
    snap = _json_obj(h.snapshot_json)
    out: Dict[str, Dict[str, Any]] = {}
    for c in snap.get("approved_claims") or []:
        if isinstance(c, dict) and c.get("id"):
            out[str(c["id"])] = c
    return out


def snapshot_time(h: Handover) -> Optional[datetime]:
    return _parse_iso(_json_obj(h.snapshot_json).get("generated_at")) or to_utc(h.created_at)


def handover_freshness(db: Session, h: Handover) -> Dict[str, Any]:
    """Admin-only: is this handover version out of date relative to the current claims?"""
    snap = snapshot_claims(h)
    ids = list(snap.keys())
    current = {c.id: c for c in db.query(Claim).filter(Claim.id.in_(ids)).all()} if ids else {}
    stale_ids = sorted(cid for cid, c in current.items() if c.is_stale)
    unapproved_ids = sorted(cid for cid, c in current.items() if c.review_status not in ("approved", "edited"))
    missing_ids = sorted(cid for cid in ids if cid not in current)
    changed_text_ids = sorted(
        cid
        for cid, c in current.items()
        if snap[cid].get("text") is not None and (snap[cid].get("text") or "") != (c.text or "")
    )
    newly_approved = (
        db.query(Claim)
        .filter(
            Claim.project_id == h.project_id,
            Claim.review_status.in_(("approved", "edited")),
            Claim.is_stale.is_(False),
        )
        .all()
    )
    new_ids = sorted(c.id for c in newly_approved if c.id not in snap)

    reasons: List[str] = []
    if stale_ids:
        reasons.append(f"{len(stale_ids)} claim(s) in this version are stale because their source changed.")
    if unapproved_ids:
        reasons.append(f"{len(unapproved_ids)} claim(s) in this version are no longer approved.")
    if missing_ids:
        reasons.append(f"{len(missing_ids)} claim(s) in this version no longer exist.")
    if changed_text_ids:
        reasons.append(f"{len(changed_text_ids)} claim(s) were edited after this version was generated.")
    if new_ids:
        reasons.append(f"{len(new_ids)} claim(s) were approved after this version was generated.")
    return {
        "out_of_date": bool(reasons),
        "stale_claim_ids": stale_ids,
        "unapproved_claim_ids": unapproved_ids,
        "missing_claim_ids": missing_ids,
        "edited_claim_ids": changed_text_ids,
        "new_approved_claim_ids": new_ids,
        "reasons": reasons,
    }


def newer_approved_version(db: Session, h: Handover) -> Optional[Handover]:
    newer = [
        v
        for v in lineage_versions(db, h)
        if (v.version_number or 1) > (h.version_number or 1) and v.status in APPROVED_HANDOVER_STATUSES
    ]
    return newer[-1] if newer else None


def open_draft_version(db: Session, h: Handover) -> Optional[Handover]:
    drafts = [
        v
        for v in lineage_versions(db, h)
        if (v.version_number or 1) > (h.version_number or 1) and v.status in EDITABLE_HANDOVER_STATUSES
    ]
    return drafts[-1] if drafts else None


def _cause_for(
    db: Session,
    claim_ids: Sequence[str],
    start: Optional[datetime],
    end: Optional[datetime],
    can_see_restricted: bool,
) -> Dict[str, Any]:
    evs = (
        db.query(ReviewEvent)
        .filter(ReviewEvent.claim_id.in_(list(claim_ids)))
        .order_by(ReviewEvent.timestamp.asc())
        .all()
        if claim_ids
        else []
    )
    in_window = []
    for e in evs:
        ts = to_utc(e.timestamp)
        if ts is None:
            continue
        if start is not None and ts <= start:
            continue
        if end is not None and ts > end:
            continue
        in_window.append(e)
    if in_window:
        last = in_window[-1]
        reviewer = db.get(User, last.reviewer_id)
        return {
            "type": "review_action",
            "label": f"Review action: {last.action} by {reviewer.name if reviewer else 'unknown'}",
            "action": last.action,
            "reviewer_name": reviewer.name if reviewer else None,
            "at": to_utc(last.timestamp).isoformat() if last.timestamp else None,
            "note": last.note,
        }
    for cid in claim_ids:
        claim = db.get(Claim, cid)
        if claim is None:
            continue
        for ch in stale_changes_for_claim(db, claim, can_see_restricted):
            return {
                "type": "source_change",
                "label": (
                    f"Source change: {ch['change_type']} chunk in {ch['source_filename']} "
                    f"(v{ch['from_version']} to v{ch['to_version']})"
                ),
                "change_id": ch["id"],
            }
    return {"type": "unknown", "label": "No review action or source change recorded between these versions."}


def diff_handovers(
    db: Session,
    from_h: Handover,
    to_h: Handover,
    *,
    can_see_restricted: bool,
) -> Dict[str, Any]:
    """Diff the approved-claim snapshots of two versions in the same lineage."""
    a = snapshot_claims(from_h)
    b = snapshot_claims(to_h)
    if not can_see_restricted:
        a = {k: v for k, v in a.items() if v.get("clearance_level") != "restricted"}
        b = {k: v for k, v in b.items() if v.get("clearance_level") != "restricted"}
    start, end = snapshot_time(from_h), snapshot_time(to_h)

    def _text(v: Dict[str, Any]) -> str:
        return v.get("text") or v.get("title") or ""

    added_ids = [k for k in b if k not in a]
    removed_ids = [k for k in a if k not in b]

    # Pair replacements proposed by re-analysis (attrs.supersedes) into a single "changed" row.
    paired: List[Tuple[str, str]] = []
    if added_ids and removed_ids:
        for nid in list(added_ids):
            claim = db.get(Claim, nid)
            sup = _json_obj(claim.attrs_json).get("supersedes") if claim else None
            sup_ids = [str(s) for s in sup] if isinstance(sup, list) else []
            for oid in sup_ids:
                if oid in removed_ids:
                    paired.append((oid, nid))
                    removed_ids.remove(oid)
                    added_ids.remove(nid)
                    break

    def _row(kind: str, old: Optional[Dict[str, Any]], new: Optional[Dict[str, Any]], ids: List[str]) -> Dict[str, Any]:
        ref = new or old or {}
        return {
            "change": kind,
            "claim_id": (new or {}).get("id") or (old or {}).get("id"),
            "old_claim_id": (old or {}).get("id"),
            "new_claim_id": (new or {}).get("id"),
            "title": ref.get("title"),
            "module": ref.get("module"),
            "claim_type": ref.get("claim_type"),
            "clearance_level": ref.get("clearance_level"),
            "old_text": _text(old) if old else None,
            "new_text": _text(new) if new else None,
            "old_review_status": (old or {}).get("review_status"),
            "new_review_status": (new or {}).get("review_status"),
            "cause": _cause_for(db, ids, start, end, can_see_restricted),
        }

    added = [_row("added", None, b[k], [k]) for k in added_ids]
    removed = [_row("removed", a[k], None, [k]) for k in removed_ids]
    changed: List[Dict[str, Any]] = [_row("changed", a[o], b[n], [o, n]) for o, n in paired]
    for k in a:
        if k in b:
            va, vb = a[k], b[k]
            keys = ("text", "title", "review_status", "verification_status", "module")
            if any((va.get(x) or "") != (vb.get(x) or "") for x in keys):
                changed.append(_row("changed", va, vb, [k]))
    return {
        "from": {"id": from_h.id, "version_number": from_h.version_number or 1, "status": from_h.status},
        "to": {"id": to_h.id, "version_number": to_h.version_number or 1, "status": to_h.status},
        "counts": {"added": len(added), "removed": len(removed), "changed": len(changed)},
        "added": added,
        "removed": removed,
        "changed": changed,
    }
