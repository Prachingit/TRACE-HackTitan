"""Interview service: generate questions (idempotent), record answers as evidence, skip with a reason."""

import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from app.engine.interview.gaps import Gap, identify_gaps
from app.engine.interview.rephrase import llm_available, rephrase
from app.engine.interview.templates import render
from app.engine.review import ReviewError, record_event
from app.models import Claim, ClaimEvidence, InterviewQuestion, Project, User


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _flatten_values(obj: Any) -> Iterable[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("reason", "rule_code", "contradiction_id"):
                continue
            yield from _flatten_values(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _flatten_values(v)
    elif isinstance(obj, str):
        yield obj
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        yield str(obj)


def generate_questions(
    db: Session,
    project: Project,
    llm_caller: Optional[Callable[[str], str]] = None,
) -> Dict[str, int]:
    """Create questions for real gaps. Re-running never duplicates and never deletes answered or skipped questions."""
    gaps = identify_gaps(db, project)
    existing = {
        q.fingerprint: q
        for q in db.query(InterviewQuestion).filter(InterviewQuestion.project_id == project.id).all()
        if q.fingerprint
    }
    current = {g.fingerprint for g in gaps}
    created = relinked = 0
    use_llm = llm_available(llm_caller)

    for g in gaps:
        q = existing.get(g.fingerprint)
        if q is not None:
            if q.status == "open":
                if q.claim_id != g.claim_id or q.contradiction_id != g.contradiction_id:
                    q.claim_id = g.claim_id
                    q.contradiction_id = g.contradiction_id
                    relinked += 1
                q.priority = g.priority
                q.clearance_level = g.clearance
            continue
        text = render(g)
        source = "template"
        if use_llm:
            better = rephrase(text, list(_flatten_values(g.facts)), caller=llm_caller)
            if better:
                text, source = better, "llm"
        db.add(
            InterviewQuestion(
                project_id=project.id,
                claim_id=g.claim_id,
                contradiction_id=g.contradiction_id,
                module=g.module,
                target_person_id=g.target_person_id,
                target_label=g.target_label,
                question=text,
                gap_type=g.gap_type,
                priority=g.priority,
                status="open",
                fingerprint=g.fingerprint,
                clearance_level=g.clearance,
                text_source=source,
                facts_json=json.dumps(g.facts, default=str),
            )
        )
        created += 1

    # Drop open, unanswered questions whose gap no longer exists. Answered and skipped questions are kept.
    removed = 0
    for fp, q in existing.items():
        if fp not in current and q.status == "open" and not q.answer:
            db.delete(q)
            removed += 1
    db.commit()
    total = db.query(InterviewQuestion).filter(InterviewQuestion.project_id == project.id).count()
    return {"created": created, "relinked": relinked, "removed": removed, "total": total, "gaps": len(gaps)}


def _new_claim_id() -> str:
    return f"CLM-{secrets.token_hex(4).upper()}"


def record_answer(db: Session, question: InterviewQuestion, user: User, answer: str) -> Claim:
    """Store the answer as NEW evidence authored by `user`. Never verifies and never edits original evidence."""
    text = (answer or "").strip()
    if not text:
        raise ReviewError(400, "An answer is required.")
    if question.status == "answered":
        raise ReviewError(409, "This question has already been answered.")
    now = _now()

    claim = db.get(Claim, question.claim_id) if question.claim_id else None
    if claim is None:
        claim = Claim(
            id=_new_claim_id(),
            project_id=question.project_id,
            claim_type="decision",
            title=f"Interview: {question.module} design and documentation"[:255],
            text=text,
            module=question.module,
            owner_name=user.name,
            author=user.name,
            verification_status="inferred",
            review_status="unreviewed",
            clearance_level=question.clearance_level or "team",
            extractor="human",
            event_time=now,
            fingerprint=hashlib.sha256(f"human|{question.id}".encode()).hexdigest()[:32],
            attrs_json=json.dumps({"origin": "interview", "interview_question_id": question.id}),
        )
        db.add(claim)
        db.flush()
        question.claim_id = claim.id
    elif claim.review_status != "rejected":
        claim.review_status = "needs_review"
        claim.updated_at = now

    db.add(
        ClaimEvidence(
            claim_id=claim.id,
            source_id=None,
            chunk_id=None,
            excerpt=text,
            author=user.name,
            author_id=user.id,
            timestamp=now,
            evidence_type="interview_answer",
            question_id=question.id,
        )
    )
    question.answer = text
    question.answered_at = now
    question.answered_by = user.id
    question.status = "answered"
    db.flush()
    record_event(
        db, claim, user.id, "answer", claim.text, claim.text,
        f"Interview answer recorded for question {question.id}. Pending reviewer decision.",
    )
    return claim


def record_skip(db: Session, question: InterviewQuestion, user: User, reason: str) -> None:
    reason = (reason or "").strip()
    if not reason:
        raise ReviewError(400, "A reason is required to skip a question.")
    if question.status == "answered":
        raise ReviewError(409, "This question has already been answered.")
    question.status = "skipped"
    question.skip_reason = reason
    question.skipped_by = user.id
    question.skipped_at = _now()
