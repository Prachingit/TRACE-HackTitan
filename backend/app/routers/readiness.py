"""Round 3, Improvement B router: Readiness Verification assessments, attempts, and per-area scores."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.engine.clearance import ClearanceError, can_view_handover, resolve_viewer_profile
from app.engine.readiness import (
    _json_list,
    compute_readiness_report,
    generate_assessment,
    send_weak_areas_to_interview,
    serialize_attempt,
    submit_attempt,
)
from app.models import (
    Assessment,
    AssessmentAttempt,
    AssessmentQuestion,
    Handover,
    Membership,
    Project,
    User,
)

router = APIRouter(tags=["Readiness"])


def _scoped_handover(handover_id: str, user_id: str, db: Session) -> tuple[Handover, Membership]:
    h = db.get(Handover, handover_id)
    if not h:
        raise HTTPException(404, "Handover not found.")
    proj = db.get(Project, h.project_id)
    if not proj:
        raise HTTPException(404, "Handover not found.")
    mem = (
        db.query(Membership)
        .filter(Membership.workspace_id == proj.workspace_id, Membership.user_id == user_id)
        .first()
    )
    if not mem:
        raise HTTPException(404, "Handover not found.")
    return h, mem


def _resolve_viewer(user: CurrentUser, role: str, view_as: Optional[str]):
    try:
        return resolve_viewer_profile(user.id, user.name, role, view_as)
    except ClearanceError as exc:
        raise HTTPException(exc.status_code, str(exc))


def _serialize_question(q: AssessmentQuestion, *, include_answer_key: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "id": q.id,
        "ordinal": q.ordinal,
        "module": q.module,
        "question_type": q.question_type,
        "prompt": q.prompt,
        "options": _json_list(q.options_json) if q.options_json else None,
        "weight": q.weight,
        "source_claim_ids": _json_list(q.source_claim_ids_json),
        "evidence_refs": _json_list(q.evidence_refs_json),
        "text_source": q.text_source,
    }
    if include_answer_key:
        out["correct_answer"] = q.correct_answer
        out["explanation"] = q.explanation
    return out


def _serialize_assessment(db: Session, a: Assessment, *, include_answer_key: bool) -> Dict[str, Any]:
    qs = (
        db.query(AssessmentQuestion)
        .filter(AssessmentQuestion.assessment_id == a.id)
        .order_by(AssessmentQuestion.ordinal.asc())
        .all()
    )
    return {
        "id": a.id,
        "handover_id": a.handover_id,
        "project_id": a.project_id,
        "status": a.status,
        "text_source": a.text_source,
        "question_count": len(qs),
        "questions": [_serialize_question(q, include_answer_key=include_answer_key) for q in qs],
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


@router.post("/api/handovers/{handover_id}/assessment/generate", status_code=201)
def generate_handover_assessment(
    handover_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin only: idempotently generate evidence-based scenario questions for this handover."""
    handover, mem = _scoped_handover(handover_id, current_user.id, db)
    if mem.role != "admin":
        raise HTTPException(403, "Only workspace admins can generate readiness assessments.")
    actor = db.get(User, current_user.id)
    assessment = generate_assessment(db, handover, actor)
    return _serialize_assessment(db, assessment, include_answer_key=True)


@router.get("/api/handovers/{handover_id}/assessment")
def get_handover_assessment(
    handover_id: str,
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return assessment questions. Answer keys are NEVER returned to incoming viewers."""
    handover, mem = _scoped_handover(handover_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, mem.role, view_as)
    if not can_view_handover(viewer, handover):
        raise HTTPException(403, "You do not have access to this handover's assessment.")

    assessment = db.query(Assessment).filter(Assessment.handover_id == handover.id).first()
    if assessment is None:
        return {"handover_id": handover.id, "project_id": handover.project_id, "question_count": 0, "questions": []}

    include_keys = viewer.profile == "team_lead"
    return _serialize_assessment(db, assessment, include_answer_key=include_keys)


class CreateAttemptRequest(BaseModel):
    handover_id: str


@router.post("/api/assessment-attempts", status_code=201)
def create_assessment_attempt(
    body: CreateAttemptRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start a new baseline or reassessment attempt for an incoming member (or admin testing)."""
    handover, mem = _scoped_handover(body.handover_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, mem.role, None)
    if not can_view_handover(viewer, handover):
        raise HTTPException(403, "You do not have access to take this handover's assessment.")

    assessment = db.query(Assessment).filter(Assessment.handover_id == handover.id).first()
    if assessment is None:
        raise HTTPException(400, "No assessment has been generated for this handover yet.")
    q_count = db.query(AssessmentQuestion).filter(AssessmentQuestion.assessment_id == assessment.id).count()
    if q_count == 0:
        raise HTTPException(400, "No approved handover claims are available to generate assessment questions yet.")

    prior_count = (
        db.query(AssessmentAttempt)
        .filter(AssessmentAttempt.assessment_id == assessment.id, AssessmentAttempt.user_id == current_user.id)
        .count()
    )
    attempt_num = prior_count + 1
    kind = "baseline" if attempt_num == 1 else "reassessment"
    attempt = AssessmentAttempt(
        assessment_id=assessment.id,
        handover_id=handover.id,
        project_id=handover.project_id,
        user_id=current_user.id,
        attempt_number=attempt_num,
        attempt_kind=kind,
        status="in_progress",
        total_questions=q_count,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    # Never return answer keys on attempt creation
    qs = (
        db.query(AssessmentQuestion)
        .filter(AssessmentQuestion.assessment_id == assessment.id)
        .order_by(AssessmentQuestion.ordinal.asc())
        .all()
    )
    return {
        **serialize_attempt(db, attempt, include_answer_keys=False),
        "questions": [_serialize_question(q, include_answer_key=False) for q in qs],
    }


class AnswerSubmissionItem(BaseModel):
    question_id: str
    answer_text: str


class SubmitAttemptRequest(BaseModel):
    answers: List[AnswerSubmissionItem]


@router.post("/api/assessment-attempts/{attempt_id}/submit")
def submit_assessment_attempt(
    attempt_id: str,
    body: SubmitAttemptRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Score an attempt deterministically and return per-area scores and source-cited explanations."""
    attempt = db.get(AssessmentAttempt, attempt_id)
    if not attempt:
        raise HTTPException(404, "Assessment attempt not found.")
    _, mem = _scoped_handover(attempt.handover_id, current_user.id, db)
    if attempt.user_id != current_user.id and mem.role != "admin":
        raise HTTPException(403, "You cannot submit another user's assessment attempt.")

    try:
        updated = submit_attempt(
            db,
            attempt,
            [{"question_id": a.question_id, "answer_text": a.answer_text} for a in body.answers],
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))

    return serialize_attempt(db, updated, include_answer_keys=(mem.role == "admin"))


@router.get("/api/handovers/{handover_id}/readiness")
def get_handover_readiness(
    handover_id: str,
    view_as: Optional[str] = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return per-area readiness scores, before/after delta, and weak areas."""
    handover, mem = _scoped_handover(handover_id, current_user.id, db)
    viewer = _resolve_viewer(current_user, mem.role, view_as)
    if not can_view_handover(viewer, handover):
        raise HTTPException(403, "You do not have access to this handover's readiness report.")

    is_lead = viewer.profile == "team_lead"
    return compute_readiness_report(
        db,
        handover,
        user_id_filter=None if is_lead else current_user.id,
        include_answer_keys=is_lead,
    )


@router.post("/api/handovers/{handover_id}/readiness/send-to-interview")
def send_readiness_weak_areas(
    handover_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin only: send weak-area missed claims into the Exit Interview workflow."""
    handover, mem = _scoped_handover(handover_id, current_user.id, db)
    if mem.role != "admin":
        raise HTTPException(403, "Only workspace admins can send weak areas to Exit Interview.")
    return send_weak_areas_to_interview(db, handover)
