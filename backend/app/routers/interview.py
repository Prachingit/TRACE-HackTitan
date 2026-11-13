"""Phase 6 router: exit interview questions, answers (as evidence) and skips."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.engine.interview.service import generate_questions, record_answer, record_skip
from app.engine.review import ReviewError
from app.models import (
    Claim,
    ClaimEvidence,
    Contradiction,
    ContradictionClaim,
    InterviewQuestion,
    Membership,
    Source,
    User,
)
from app.routers.analysis import _get_scoped_project

router = APIRouter(tags=["Interview"])

PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
STATUS_RANK = {"open": 0, "skipped": 1, "answered": 2}


# ── Schemas ───────────────────────────────────────────────────────────────────

class AnswerRequest(BaseModel):
    answer: str
    answered_by: Optional[str] = None  # display only; the signed-in user is always the author


class SkipRequest(BaseModel):
    reason: str


class ContextExcerpt(BaseModel):
    claim_id: str
    source_id: Optional[str] = None
    source_filename: Optional[str] = None
    locator: Optional[str] = None
    excerpt: str


class QuestionResponse(BaseModel):
    id: str
    project_id: str
    claim_id: Optional[str] = None
    contradiction_id: Optional[str] = None
    module: str
    gap_type: str
    priority: str
    question: str
    status: str
    text_source: str
    target_person_id: Optional[str] = None
    target_label: str = "unassigned"
    answer: Optional[str] = None
    answered_at: Optional[datetime] = None
    answered_by_name: Optional[str] = None
    skip_reason: Optional[str] = None
    clearance_level: str
    can_answer: bool = False
    claim: Optional[Dict[str, Any]] = None
    contradiction: Optional[Dict[str, Any]] = None
    context: List[ContextExcerpt] = []
    created_at: datetime


class GroupCount(BaseModel):
    name: str
    person_id: Optional[str] = None
    total: int
    answered: int
    skipped: int


class InterviewResponse(BaseModel):
    progress: Dict[str, int]
    by_module: List[GroupCount]
    by_person: List[GroupCount]
    questions: List[QuestionResponse]


class GenerateResponse(BaseModel):
    created: int
    relinked: int
    removed: int
    total: int
    gaps: int


# ── Helpers ───────────────────────────────────────────────────────────────────

def _check_role(membership: Membership) -> None:
    if membership.role == "incoming":
        raise HTTPException(status_code=403, detail="The exit interview is not available to incoming members.")


def _can_answer(q: InterviewQuestion, user: CurrentUser, role: str) -> bool:
    if role == "admin":
        return True
    if role not in ("team_member", "departing"):
        return False
    if q.target_person_id and q.target_person_id == user.id:
        return True
    return bool(q.target_label and q.target_label.strip().lower() == (user.name or "").strip().lower())


def _context(db: Session, q: InterviewQuestion, role: str, limit: int = 4) -> List[ContextExcerpt]:
    claim_ids: List[str] = []
    if q.claim_id:
        claim_ids.append(q.claim_id)
    if q.contradiction_id:
        for cc in db.query(ContradictionClaim).filter(ContradictionClaim.contradiction_id == q.contradiction_id).all():
            if cc.claim_id not in claim_ids:
                claim_ids.append(cc.claim_id)
    out: List[ContextExcerpt] = []
    for cid in claim_ids:
        clm = db.get(Claim, cid)
        if clm is None or (role != "admin" and clm.clearance_level == "restricted"):
            continue
        for ev in db.query(ClaimEvidence).filter(
            ClaimEvidence.claim_id == cid, ClaimEvidence.evidence_type != "interview_answer"
        ).all():
            src = db.get(Source, ev.source_id) if ev.source_id else None
            if src is not None and role != "admin" and src.clearance_level == "restricted":
                continue
            locator = None
            if ev.chunk_id:
                from app.models import Chunk
                ch = db.get(Chunk, ev.chunk_id)
                locator = ch.locator if ch else None
            out.append(
                ContextExcerpt(
                    claim_id=cid,
                    source_id=ev.source_id,
                    source_filename=src.filename if src else None,
                    locator=locator,
                    excerpt=ev.excerpt[:400],
                )
            )
            if len(out) >= limit:
                return out
    return out


def _serialize(db: Session, q: InterviewQuestion, user: CurrentUser, role: str, with_context: bool = True) -> QuestionResponse:
    claim = db.get(Claim, q.claim_id) if q.claim_id else None
    ctr = db.get(Contradiction, q.contradiction_id) if q.contradiction_id else None
    answerer = db.get(User, q.answered_by) if q.answered_by else None
    return QuestionResponse(
        id=q.id,
        project_id=q.project_id,
        claim_id=q.claim_id,
        contradiction_id=q.contradiction_id,
        module=q.module,
        gap_type=q.gap_type,
        priority=q.priority,
        question=q.question,
        status=q.status,
        text_source=q.text_source,
        target_person_id=q.target_person_id,
        target_label=q.target_label or "unassigned",
        answer=q.answer,
        answered_at=q.answered_at,
        answered_by_name=answerer.name if answerer else None,
        skip_reason=q.skip_reason,
        clearance_level=q.clearance_level,
        can_answer=_can_answer(q, user, role),
        claim=(
            {
                "id": claim.id,
                "title": claim.title or (claim.text or "")[:100],
                "verification_status": claim.verification_status,
                "review_status": claim.review_status,
            }
            if claim else None
        ),
        contradiction=(
            {"id": ctr.id, "rule_code": ctr.rule_code, "severity": ctr.severity, "status": ctr.status}
            if ctr else None
        ),
        context=_context(db, q, role) if with_context else [],
        created_at=q.created_at,
    )


def _load_question(db: Session, qid: str, user: CurrentUser) -> tuple[InterviewQuestion, Membership]:
    q = db.get(InterviewQuestion, qid)
    if not q:
        raise HTTPException(status_code=404, detail="Question not found.")
    _, membership = _get_scoped_project(q.project_id, user.id, db)
    if membership.role != "admin" and q.clearance_level == "restricted":
        raise HTTPException(status_code=404, detail="Question not found.")
    return q, membership


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/api/projects/{project_id}/interview/generate", response_model=GenerateResponse)
def generate(
    project_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, membership = _get_scoped_project(project_id, current_user.id, db)
    if membership.role != "admin":
        raise HTTPException(status_code=403, detail="Only the team lead (admin) can generate interview questions.")
    return GenerateResponse(**generate_questions(db, project))


@router.get("/api/projects/{project_id}/interview", response_model=InterviewResponse)
def list_interview(
    project_id: str,
    module: Optional[str] = Query(default=None),
    person: Optional[str] = Query(default=None, description="Target person name, or 'unassigned'"),
    status: Optional[str] = Query(default=None, pattern="^(answered|unanswered|skipped)$"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _, membership = _get_scoped_project(project_id, current_user.id, db)
    _check_role(membership)
    role = membership.role

    base = db.query(InterviewQuestion).filter(InterviewQuestion.project_id == project_id)
    if role != "admin":
        base = base.filter(InterviewQuestion.clearance_level != "restricted")
    visible = base.all()

    # Rail counts always reflect every visible question, not the current filter
    progress = {
        "total": len(visible),
        "answered": sum(1 for q in visible if q.status == "answered"),
        "skipped": sum(1 for q in visible if q.status == "skipped"),
        "open": sum(1 for q in visible if q.status == "open"),
    }

    def groups(key_fn, id_fn=None) -> List[GroupCount]:
        agg: Dict[str, Dict[str, Any]] = {}
        for q in visible:
            k = key_fn(q)
            g = agg.setdefault(k, {"total": 0, "answered": 0, "skipped": 0, "person_id": id_fn(q) if id_fn else None})
            g["total"] += 1
            g["answered"] += 1 if q.status == "answered" else 0
            g["skipped"] += 1 if q.status == "skipped" else 0
        return [GroupCount(name=k, **v) for k, v in sorted(agg.items())]

    by_module = groups(lambda q: q.module)
    by_person = groups(lambda q: q.target_label or "unassigned", lambda q: q.target_person_id)

    rows = visible
    if module:
        rows = [q for q in rows if q.module == module]
    if person:
        rows = [q for q in rows if (q.target_label or "unassigned").lower() == person.strip().lower()]
    if status == "answered":
        rows = [q for q in rows if q.status == "answered"]
    elif status == "unanswered":
        rows = [q for q in rows if q.status != "answered"]
    elif status == "skipped":
        rows = [q for q in rows if q.status == "skipped"]
    rows.sort(key=lambda q: (STATUS_RANK.get(q.status, 3), PRIORITY_RANK.get(q.priority, 3), q.module, q.id))

    return InterviewResponse(
        progress=progress,
        by_module=by_module,
        by_person=by_person,
        questions=[_serialize(db, q, current_user, role) for q in rows],
    )


@router.post("/api/interview/questions/{question_id}/answer", response_model=QuestionResponse)
def answer_question(
    question_id: str,
    body: AnswerRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q, membership = _load_question(db, question_id, current_user)
    _check_role(membership)
    if not _can_answer(q, current_user, membership.role):
        raise HTTPException(status_code=403, detail="You can only answer questions about your own items.")
    try:
        record_answer(db, q, current_user.user, body.answer)
        db.commit()
    except ReviewError as e:
        db.rollback()
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    db.refresh(q)
    return _serialize(db, q, current_user, membership.role)


@router.post("/api/interview/questions/{question_id}/skip", response_model=QuestionResponse)
def skip_question(
    question_id: str,
    body: SkipRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q, membership = _load_question(db, question_id, current_user)
    _check_role(membership)
    if not _can_answer(q, current_user, membership.role):
        raise HTTPException(status_code=403, detail="You can only skip questions about your own items.")
    try:
        record_skip(db, q, current_user.user, body.reason)
        db.commit()
    except ReviewError as e:
        db.rollback()
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    db.refresh(q)
    return _serialize(db, q, current_user, membership.role)
