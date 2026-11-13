"""Review service (Phase 6): accept / edit / reject / flag with eligibility rules and append-only history.

Rules enforced here (not in the UI):
- Accept requires at least one valid evidence row (document excerpt present in its chunk, or an interview answer)
  and no open contradiction involving the claim, unless the reviewer resolves those contradictions in the same
  action with a required note.
- Edit preserves the original text and writes a new version. Reject and flag require a note.
- Every action appends a ReviewEvent; nothing here updates or deletes events.
"""

import difflib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.engine.validation import is_valid_excerpt
from app.models import (
    Chunk,
    Claim,
    ClaimEvidence,
    Contradiction,
    ContradictionClaim,
    ReviewEvent,
    User,
)

ACTION_ALIASES = {"accept": "approve", "approve": "approve", "edit": "edit", "reject": "reject", "flag": "flag"}
OPEN_REVIEW_STATUSES = ("unreviewed", "needs_review", "edited")


class ReviewError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Eligibility ───────────────────────────────────────────────────────────────

def valid_evidence_count(db: Session, claim: Claim) -> int:
    """Count evidence rows that really support the claim: document excerpts found in their chunk, or interview answers."""
    n = 0
    for ev in db.query(ClaimEvidence).filter(ClaimEvidence.claim_id == claim.id).all():
        if ev.evidence_type == "interview_answer":
            if (ev.excerpt or "").strip() and (ev.author_id or ev.author):
                n += 1
            continue
        ch = db.get(Chunk, ev.chunk_id) if ev.chunk_id else None
        if ch is not None and is_valid_excerpt(ch.text, ev.excerpt):
            n += 1
    return n


def interview_answer_count(db: Session, claim_id: str) -> int:
    return (
        db.query(ClaimEvidence)
        .filter(ClaimEvidence.claim_id == claim_id, ClaimEvidence.evidence_type == "interview_answer")
        .count()
    )


def open_contradictions_for_claim(db: Session, claim_id: str) -> List[Contradiction]:
    return (
        db.query(Contradiction)
        .join(ContradictionClaim, ContradictionClaim.contradiction_id == Contradiction.id)
        .filter(ContradictionClaim.claim_id == claim_id, Contradiction.status == "open")
        .order_by(Contradiction.id)
        .all()
    )


def accept_blockers(db: Session, claim: Claim) -> List[str]:
    """Human-readable reasons why Accept is currently not allowed (empty list = allowed)."""
    reasons: List[str] = []
    if valid_evidence_count(db, claim) == 0:
        reasons.append("No valid evidence: link a source excerpt or record an interview answer first.")
    ctrs = open_contradictions_for_claim(db, claim.id)
    if ctrs:
        ids = ", ".join(c.id for c in ctrs)
        reasons.append(f"Resolve contradiction first: {ids}.")
    return reasons


# ── History ───────────────────────────────────────────────────────────────────

def next_version(db: Session, claim_id: str) -> int:
    last = (
        db.query(ReviewEvent.version)
        .filter(ReviewEvent.claim_id == claim_id)
        .order_by(ReviewEvent.version.desc())
        .first()
    )
    return (last[0] if last and last[0] else 0) + 1


def record_event(
    db: Session,
    claim: Claim,
    user_id: str,
    action: str,
    old_text: Optional[str],
    new_text: Optional[str],
    note: Optional[str],
) -> ReviewEvent:
    ev = ReviewEvent(
        claim_id=claim.id,
        reviewer_id=user_id,
        action=action,
        old_text=old_text,
        new_text=new_text,
        note=note,
        timestamp=_now(),
        version=next_version(db, claim.id),
        resulting_review_status=claim.review_status,
        resulting_verification_status=claim.verification_status,
    )
    db.add(ev)
    db.flush()
    return ev


_WORD_RE = re.compile(r"\s+|\w+|[^\w\s]", re.UNICODE)


def text_diff(old: Optional[str], new: Optional[str]) -> List[Dict[str, str]]:
    """Word-level diff as a list of {op: equal|insert|delete, text}."""
    a = _WORD_RE.findall(old or "")
    b = _WORD_RE.findall(new or "")
    out: List[Dict[str, str]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":
            out.append({"op": "equal", "text": "".join(a[i1:i2])})
        else:
            if i2 > i1:
                out.append({"op": "delete", "text": "".join(a[i1:i2])})
            if j2 > j1:
                out.append({"op": "insert", "text": "".join(b[j1:j2])})
    return out


def serialize_history(db: Session, claim_id: str) -> List[Dict[str, Any]]:
    rows = (
        db.query(ReviewEvent)
        .filter(ReviewEvent.claim_id == claim_id)
        .order_by(ReviewEvent.version.asc(), ReviewEvent.timestamp.asc())
        .all()
    )
    out = []
    for r in rows:
        reviewer = db.get(User, r.reviewer_id)
        out.append(
            {
                "id": r.id,
                "claim_id": r.claim_id,
                "version": r.version,
                "action": r.action,
                "reviewer_id": r.reviewer_id,
                "reviewer_name": reviewer.name if reviewer else r.reviewer_id,
                "old_text": r.old_text,
                "new_text": r.new_text,
                "note": r.note,
                "timestamp": r.timestamp,
                "resulting_review_status": r.resulting_review_status,
                "resulting_verification_status": r.resulting_verification_status,
                "diff": text_diff(r.old_text, r.new_text) if r.action == "edit" else [],
            }
        )
    return out


# ── Actions ───────────────────────────────────────────────────────────────────

@dataclass
class ReviewResult:
    claim: Claim
    resolved_contradiction_ids: List[str]


def apply_review(
    db: Session,
    claim: Claim,
    user: User,
    action: str,
    text: Optional[str] = None,
    note: Optional[str] = None,
    resolve_contradictions: bool = False,
) -> ReviewResult:
    act = ACTION_ALIASES.get((action or "").strip().lower())
    if act is None:
        raise ReviewError(400, "Invalid review action. Use accept, edit, reject, or flag.")
    note = (note or "").strip() or None
    now = _now()
    old_text = claim.text
    resolved_ids: List[str] = []

    if act == "flag":
        if not note:
            raise ReviewError(400, "A note is required when flagging a claim for review.")
        claim.review_status = "needs_review"
        claim.review_note = note

    elif act == "reject":
        if not note:
            raise ReviewError(400, "A reason is required to reject a claim.")
        claim.review_status = "rejected"
        claim.reviewed_by = user.id
        claim.reviewed_at = now
        claim.review_note = note

    elif act == "edit":
        new_text = (text or "").strip()
        if not new_text:
            raise ReviewError(400, "New text is required when editing a claim.")
        if new_text == (claim.text or "").strip():
            raise ReviewError(400, "The new text is identical to the current text.")
        if claim.original_text is None:
            claim.original_text = claim.text
        claim.text = new_text
        claim.review_status = "edited"
        claim.reviewed_by = user.id
        claim.reviewed_at = now
        claim.review_note = note
        # The edited wording is no longer what the evidence literally says: it must be accepted again to be verified.
        if claim.verification_status == "verified":
            claim.verification_status = "inferred"

    else:  # approve
        reasons = accept_blockers(db, claim)
        open_ctrs = open_contradictions_for_claim(db, claim.id)
        if open_ctrs and resolve_contradictions:
            if not note:
                raise ReviewError(400, "A note is required to resolve contradictions while accepting a claim.")
            if valid_evidence_count(db, claim) == 0:
                raise ReviewError(409, reasons[0])
            for c in open_ctrs:
                c.status = "resolved"
                c.resolved_by = user.id
                c.resolved_at = now
                c.resolution_note = note
                resolved_ids.append(c.id)
        elif reasons:
            raise ReviewError(409, " ".join(reasons))
        claim.review_status = "approved"
        claim.verification_status = "verified"
        claim.reviewed_by = user.id
        claim.reviewed_at = now
        claim.review_note = note

    claim.updated_at = now
    record_event(db, claim, user.id, act, old_text, claim.text, note)
    return ReviewResult(claim=claim, resolved_contradiction_ids=resolved_ids)
