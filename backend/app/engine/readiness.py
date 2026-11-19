"""Readiness Verification engine (Round 3, Improvement B).

Generates evidence-based scenario questions ONLY from approved, non-restricted, non-stale claims
visible to the incoming member; scores deterministically (exact MCQ + heuristic short-answer
key-term coverage); aggregates weighted per-area readiness scores; computes baseline vs
re-assessment deltas; and links weak areas to the Exit Interview workflow.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy.orm import Session

from app.engine.clearance import APPROVED_CLAIM_STATUSES, effective_claim_clearance
from app.engine.interview.rephrase import llm_available, rephrase
from app.engine.plan import build_ranked_plan
from app.models import (
    AreaScore,
    Assessment,
    AssessmentAnswer,
    AssessmentAttempt,
    AssessmentQuestion,
    Claim,
    ClaimEvidence,
    Contradiction,
    Handover,
    InterviewQuestion,
    Project,
    Source,
    User,
)

WEAK_AREA_THRESHOLD = 70.0
_RATIONALE_RE = re.compile(
    r"\b(because|since|rationale|so that|in order to|to avoid|due to|chosen for|reason)\b",
    re.IGNORECASE,
)
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "about", "what", "which",
    "when", "where", "how", "why", "check", "first", "before", "after", "module", "task",
    "status", "should", "must", "will", "have", "been", "were", "are", "was", "not",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_list(raw: Any) -> List[Any]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            v = json.loads(raw)
            return v if isinstance(v, list) else []
        except Exception:
            return []
    return []


def _json_obj(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {}
        except Exception:
            return {}
    return {}


def _fp(parts: Sequence[str]) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def _extract_rationale(claim: Claim, ev_rows: Sequence[ClaimEvidence]) -> Optional[str]:
    attrs = _json_obj(claim.attrs_json)
    if isinstance(attrs.get("rationale"), str) and attrs["rationale"].strip():
        return attrs["rationale"].strip()
    if _RATIONALE_RE.search(claim.text or ""):
        m = _RATIONALE_RE.search(claim.text or "")
        if m:
            return claim.text[m.start():].strip()
    for ev in ev_rows:
        if ev.excerpt and _RATIONALE_RE.search(ev.excerpt):
            m = _RATIONALE_RE.search(ev.excerpt)
            if m:
                return ev.excerpt[m.start():].strip()[:220]
    return None


def _evidence_refs(ev_rows: Sequence[ClaimEvidence], sources_by_id: Dict[str, Source]) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for ev in ev_rows[:4]:
        src = sources_by_id.get(ev.source_id) if ev.source_id else None
        ch = getattr(ev, "chunk", None)
        refs.append({
            "evidence_id": ev.id,
            "source_id": ev.source_id,
            "source_name": src.filename if src else ("interview" if ev.evidence_type == "interview_answer" else None),
            "locator": ch.locator if ch else None,
            "excerpt": (ev.excerpt or "")[:200],
        })
    return refs


def _build_options(correct: str, pool: Sequence[str], *, include_not_recorded: bool = True) -> List[str]:
    opts: List[str] = [correct]
    for cand in pool:
        c = (cand or "").strip()
        if c and c.lower() != correct.lower() and all(c.lower() != o.lower() for o in opts):
            opts.append(c)
        if len(opts) >= (3 if include_not_recorded else 4):
            break
    if include_not_recorded and len(opts) < 4:
        nr = "Not recorded in the handover"
        if all(o.lower() != nr.lower() for o in opts):
            opts.append(nr)
    # Deterministic order (alphabetical by hash so answer isn't always first)
    return sorted(opts[:4], key=lambda x: hashlib.sha256(f"{correct}:{x}".encode("utf-8")).hexdigest())


def _terms_from_text(*texts: str) -> List[str]:
    seen: Set[str] = set()
    terms: List[str] = []
    for t in texts:
        for tok in re.findall(r"[A-Za-z0-9_.\-]{3,}", t or ""):
            low = tok.lower().strip(".-_")
            if len(low) >= 3 and low not in _STOPWORDS and low not in seen:
                seen.add(low)
                terms.append(low)
            if len(terms) >= 8:
                return terms
    return terms


def _visible_approved_claims(db: Session, handover: Handover) -> List[Claim]:
    """Return ONLY approved/edited, non-stale, non-restricted claims for this handover's project."""
    rows = (
        db.query(Claim)
        .filter(
            Claim.project_id == handover.project_id,
            Claim.review_status.in_(APPROVED_CLAIM_STATUSES),
            Claim.is_stale.is_(False),
        )
        .order_by(Claim.module.asc(), Claim.id.asc())
        .all()
    )
    return [c for c in rows if effective_claim_clearance(db, c) != "restricted"]


def generate_assessment(
    db: Session,
    handover: Handover,
    created_by: User,
    *,
    llm_caller: Optional[Callable[[str], str]] = None,
) -> Assessment:
    """Idempotently generate scenario questions from approved, incoming-visible claims."""
    claims = _visible_approved_claims(db, handover)
    sources_by_id = {
        s.id: s
        for s in db.query(Source).filter(Source.project_id == handover.project_id, Source.clearance_level != "restricted").all()
    }
    ev_by_claim: Dict[str, List[ClaimEvidence]] = defaultdict(list)
    if claims:
        for ev in db.query(ClaimEvidence).filter(ClaimEvidence.claim_id.in_([c.id for c in claims])).all():
            if ev.source_id and ev.source_id not in sources_by_id:
                continue
            ev_by_claim[ev.claim_id].append(ev)

    open_ctrs = [
        c for c in db.query(Contradiction).filter(Contradiction.project_id == handover.project_id, Contradiction.status == "open").all()
        if c.clearance_level != "restricted"
    ]
    open_qs = [
        q for q in db.query(InterviewQuestion).filter(InterviewQuestion.project_id == handover.project_id, InterviewQuestion.status == "open").all()
        if q.clearance_level != "restricted"
    ]
    plan_items, _ = build_ranked_plan(claims, open_ctrs, open_qs, ev_by_claim, sources_by_id)
    plan_by_claim: Dict[str, Dict[str, Any]] = {}
    for p in plan_items:
        for cid in p.get("claim_ids") or []:
            plan_by_claim[cid] = p

    assessment = db.query(Assessment).filter(Assessment.handover_id == handover.id).first()
    if assessment is None:
        assessment = Assessment(
            handover_id=handover.id,
            project_id=handover.project_id,
            status="ready",
            text_source="template",
            created_by=created_by.id,
        )
        db.add(assessment)
        db.flush()

    existing_by_fp = {
        q.fingerprint: q
        for q in db.query(AssessmentQuestion).filter(AssessmentQuestion.assessment_id == assessment.id).all()
    }

    all_owners = sorted({(c.owner_name or "").strip() for c in claims if (c.owner_name or "").strip()})
    all_modules = sorted({c.module for c in claims if c.module})
    all_rationales = [
        r for c in claims if (r := _extract_rationale(c, ev_by_claim.get(c.id, [])))
    ]

    candidates: List[Dict[str, Any]] = []
    seen_mod_owner: Set[str] = set()

    # 1. Ownership MCQ per module
    for c in claims:
        owner = (c.owner_name or "").strip()
        if not owner or c.module in seen_mod_owner:
            continue
        seen_mod_owner.add(c.module)
        distractors = [o for o in all_owners if o.lower() != owner.lower()] + ["Shared / rotating", "External vendor"]
        opts = _build_options(owner, distractors)
        ev_rows = ev_by_claim.get(c.id, [])
        src_desc = ev_rows[0].excerpt[:140] if ev_rows else c.text[:140]
        candidates.append({
            "module": c.module,
            "question_type": "mcq",
            "prompt": f"Who owns the '{c.module}' module?",
            "options": opts,
            "correct_answer": owner,
            "answer_key": {"expected": owner},
            "explanation": f"Claim {c.id} states {owner} owns '{c.module}'. Evidence: \"{src_desc}\".",
            "source_claim_ids": [c.id],
            "evidence_refs": _evidence_refs(ev_rows, sources_by_id),
            "weight": 1.0,
            "facts": [c.module, owner],
            "fingerprint": _fp(["owner", c.module, owner]),
        })

    # 2. Task status MCQ
    status_pool = ["Completed with verified tests", "In progress", "Pending / not started", "Blocked on dependency"]
    for c in claims:
        if c.claim_type != "task_status":
            continue
        attrs = _json_obj(c.attrs_json)
        raw_st = str(attrs.get("status") or "").lower()
        task_name = (c.title or c.text[:70]).strip()
        ev_rows = ev_by_claim.get(c.id, [])
        src_hint = (ev_rows[0].excerpt[:100] if ev_rows else c.text[:100]).strip()
        if raw_st in ("completed", "done"):
            correct = f"Completed — supported by: {src_hint}"
            dists = [f"In progress — {src_hint}", "Blocked on external approval", "Pending — not started"]
        elif raw_st in ("blocked",):
            correct = f"Blocked — supported by: {src_hint}"
            dists = ["Completed and verified", "In progress without blockers", "Deprecated / cancelled"]
        elif raw_st in ("in_progress", "wip"):
            correct = f"In progress — supported by: {src_hint}"
            dists = ["Completed and verified", "Blocked on missing credentials", "Not started"]
        else:
            correct = f"{(raw_st or 'Recorded').replace('_', ' ').title()} — {src_hint}"
            dists = status_pool
        opts = _build_options(correct, dists, include_not_recorded=False)
        weight = 1.5 if raw_st == "blocked" or c.id in plan_by_claim else 1.0
        candidates.append({
            "module": c.module,
            "question_type": "mcq",
            "prompt": f"What is the status of '{task_name}' in '{c.module}' and what supports it?",
            "options": opts,
            "correct_answer": correct,
            "answer_key": {"expected": correct},
            "explanation": f"Claim {c.id} records this status: {c.text}",
            "source_claim_ids": [c.id],
            "evidence_refs": _evidence_refs(ev_rows, sources_by_id),
            "weight": weight,
            "facts": [task_name, c.module],
            "fingerprint": _fp(["task_status", c.id, raw_st]),
        })

    # 3. Decision rationale MCQ (ONLY when rationale evidence exists)
    for c in claims:
        if c.claim_type != "decision":
            continue
        rat = _extract_rationale(c, ev_by_claim.get(c.id, []))
        if not rat:
            continue
        dec_title = (c.title or c.text[:70]).strip()
        dists = [r for r in all_rationales if r != rat] + [
            "Temporary workaround pending legacy deprecation",
            "Chosen to satisfy an unrelated mobile client constraint",
        ]
        opts = _build_options(rat, dists)
        ev_rows = ev_by_claim.get(c.id, [])
        candidates.append({
            "module": c.module,
            "question_type": "mcq",
            "prompt": f"Why was the decision '{dec_title}' made in '{c.module}'?",
            "options": opts,
            "correct_answer": rat,
            "answer_key": {"expected": rat},
            "explanation": f"Claim {c.id} records the rationale: {rat}",
            "source_claim_ids": [c.id],
            "evidence_refs": _evidence_refs(ev_rows, sources_by_id),
            "weight": 1.25,
            "facts": [dec_title, c.module],
            "fingerprint": _fp(["decision", c.id]),
        })

    # 4. Dependency MCQ & Blocker/Dependency Short-Answer
    for c in claims:
        attrs = _json_obj(c.attrs_json)
        dep_on = attrs.get("depends_on") or attrs.get("blocked_by")
        is_blocker = c.claim_type in ("blocker", "dependency") or bool(dep_on)
        if not is_blocker:
            continue
        task_name = (c.title or c.text[:70]).strip()
        ev_rows = ev_by_claim.get(c.id, [])
        p_item = plan_by_claim.get(c.id)
        if dep_on and c.claim_type == "dependency":
            dep_str = ", ".join(dep_on) if isinstance(dep_on, list) else str(dep_on)
            dists = [m for m in all_modules if m != c.module] + ["No upstream dependency"]
            opts = _build_options(dep_str, dists)
            candidates.append({
                "module": c.module,
                "question_type": "mcq",
                "prompt": f"'{task_name}' depends on what?",
                "options": opts,
                "correct_answer": dep_str,
                "answer_key": {"expected": dep_str},
                "explanation": f"Claim {c.id} states '{task_name}' depends on {dep_str}.",
                "source_claim_ids": [c.id],
                "evidence_refs": _evidence_refs(ev_rows, sources_by_id),
                "weight": 1.5,
                "facts": [task_name, dep_str],
                "fingerprint": _fp(["dep_mcq", c.id]),
            })

        # Short-answer scenario grounded in blocker/dependency + ranked plan
        plan_hint = p_item.get("why_it_matters") if p_item else ""
        answer_summary = f"{c.text} {plan_hint}".strip()
        key_terms = _terms_from_text(
            str(dep_on or ""),
            c.text,
            c.owner_name or "",
            c.module or "",
            plan_hint or "",
        )
        if not key_terms:
            key_terms = _terms_from_text(c.title or c.text)
        if key_terms:
            candidates.append({
                "module": c.module,
                "question_type": "short_answer",
                "prompt": f"'{task_name}' in '{c.module}' is blocked or has prerequisites. What do you check first?",
                "options": None,
                "correct_answer": answer_summary,
                "answer_key": {"key_terms": key_terms, "expected_summary": answer_summary},
                "explanation": f"Based on Claim {c.id}: {answer_summary}",
                "source_claim_ids": [c.id],
                "evidence_refs": _evidence_refs(ev_rows, sources_by_id),
                "weight": 1.5,
                "facts": [task_name, c.module],
                "fingerprint": _fp(["short_blocker", c.id]),
            })

    use_llm = llm_available(llm_caller)
    any_llm = False
    ordinal = len(existing_by_fp) + 1
    for cand in candidates:
        if not cand["source_claim_ids"]:
            continue  # Never create a question without a source claim
        if cand["fingerprint"] in existing_by_fp:
            continue
        prompt_text = cand["prompt"]
        t_src = "template"
        if use_llm:
            rephrased = rephrase(prompt_text, cand["facts"], caller=llm_caller)
            if rephrased:
                prompt_text = rephrased
                t_src = "llm"
                any_llm = True
        db.add(
            AssessmentQuestion(
                assessment_id=assessment.id,
                ordinal=ordinal,
                module=cand["module"],
                question_type=cand["question_type"],
                prompt=prompt_text,
                options_json=json.dumps(cand["options"]) if cand["options"] is not None else None,
                correct_answer=cand["correct_answer"],
                answer_key_json=json.dumps(cand["answer_key"]),
                explanation=cand["explanation"],
                source_claim_ids_json=json.dumps(cand["source_claim_ids"]),
                evidence_refs_json=json.dumps(cand["evidence_refs"]),
                weight=float(cand["weight"]),
                clearance_level="team",
                fingerprint=cand["fingerprint"],
                text_source=t_src,
            )
        )
        ordinal += 1

    if any_llm:
        assessment.text_source = "llm"
    assessment.updated_at = _utcnow()
    db.commit()
    db.refresh(assessment)
    return assessment


def score_mcq(question: AssessmentQuestion, answer_text: str) -> Tuple[bool, float, str]:
    expected = (question.correct_answer or "").strip()
    given = (answer_text or "").strip()
    ok = given.lower() == expected.lower() and bool(given)
    return ok, (1.0 if ok else 0.0), ("Exact match against approved claim." if ok else "Did not match the recorded answer.")


def score_short_answer(
    question: AssessmentQuestion,
    answer_text: str,
    *,
    llm_scorer: Optional[Callable[[str, str], Optional[float]]] = None,
) -> Dict[str, Any]:
    """Deterministic key-term coverage with partial credit + low-confidence reviewer flag."""
    key_obj = _json_obj(question.answer_key_json)
    terms: List[str] = [str(t).lower() for t in (key_obj.get("key_terms") or []) if str(t).strip()]
    given_low = (answer_text or "").lower()
    if not given_low.strip() or not terms:
        return {
            "score": 0.0,
            "is_correct": False,
            "confidence": 1.0,
            "needs_reviewer_check": False,
            "rationale": "Heuristic check: empty response (0 key terms matched).",
            "llm_suggested_score": None,
        }
    matched = [t for t in terms if t in given_low]
    missed = [t for t in terms if t not in given_low]
    # Full credit at >= 60% key-term coverage; proportional partial credit below that.
    raw_cov = len(matched) / len(terms)
    score = round(min(1.0, raw_cov / 0.6), 2) if raw_cov < 0.6 else 1.0
    is_correct = score >= 0.7
    needs_check = (0.25 < score < 0.75) or (len(given_low.split()) >= 5 and score < 0.7)
    confidence = round(1.0 - (0.45 if needs_check else 0.1), 2)
    rationale = (
        f"Heuristic key-term coverage: matched {len(matched)}/{len(terms)} terms "
        f"({', '.join(matched[:4]) or 'none'}). "
        f"{'Needs reviewer check due to partial coverage.' if needs_check else 'Deterministic threshold applied.'}"
    )
    llm_score: Optional[float] = None
    if llm_scorer is not None:
        try:
            s = llm_scorer(question.correct_answer, answer_text)
            if isinstance(s, (int, float)) and 0.0 <= float(s) <= 1.0:
                llm_score = round(float(s), 2)
        except Exception:
            llm_score = None

    return {
        "score": score,
        "is_correct": is_correct,
        "confidence": confidence,
        "needs_reviewer_check": needs_check,
        "rationale": rationale,
        "llm_suggested_score": llm_score,
        "missed_terms": missed[:4],
    }


def submit_attempt(
    db: Session,
    attempt: AssessmentAttempt,
    answers: Sequence[Dict[str, str]],
    *,
    llm_scorer: Optional[Callable[[str, str], Optional[float]]] = None,
) -> AssessmentAttempt:
    if attempt.status == "submitted":
        raise ValueError("This attempt has already been submitted.")
    questions = (
        db.query(AssessmentQuestion)
        .filter(AssessmentQuestion.assessment_id == attempt.assessment_id)
        .order_by(AssessmentQuestion.ordinal.asc())
        .all()
    )
    q_by_id = {q.id: q for q in questions}
    ans_map = {str(a.get("question_id")): str(a.get("answer_text") or "") for a in answers if a.get("question_id")}

    # Idempotent clear if somehow re-called before submit committed
    db.query(AssessmentAnswer).filter(AssessmentAnswer.attempt_id == attempt.id).delete()
    db.query(AreaScore).filter(AreaScore.attempt_id == attempt.id).delete()
    db.flush()

    by_module: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"correct": 0, "count": 0, "wp": 0.0, "max_wp": 0.0, "missed": []}
    )
    total_wp = 0.0
    total_max_wp = 0.0
    correct_count = 0
    needs_review_count = 0

    for q in questions:
        given = ans_map.get(q.id, "")
        w = float(q.weight or 1.0)
        if q.question_type == "mcq":
            ok, sc, rat = score_mcq(q, given)
            conf, needs_chk, llm_sc = 1.0, False, None
        else:
            res = score_short_answer(q, given, llm_scorer=llm_scorer)
            ok = res["is_correct"]
            sc = res["score"]
            rat = res["rationale"]
            conf = res["confidence"]
            needs_chk = res["needs_reviewer_check"]
            llm_sc = res["llm_suggested_score"]

        if ok:
            correct_count += 1
        if needs_chk:
            needs_review_count += 1

        db.add(
            AssessmentAnswer(
                attempt_id=attempt.id,
                question_id=q.id,
                answer_text=given,
                is_correct=ok,
                score=sc,
                confidence=conf,
                needs_reviewer_check=needs_chk,
                heuristic_rationale=rat,
                llm_suggested_score=llm_sc,
                answered_at=_utcnow(),
            )
        )

        m = by_module[q.module]
        m["count"] += 1
        m["correct"] += 1 if ok else 0
        m["wp"] += sc * w
        m["max_wp"] += w
        total_wp += sc * w
        total_max_wp += w
        if not ok:
            for cid in _json_list(q.source_claim_ids_json):
                if cid not in m["missed"]:
                    m["missed"].append(cid)

    for mod, m in sorted(by_module.items()):
        pct = round((m["wp"] / m["max_wp"]) * 100.0, 1) if m["max_wp"] > 0 else 0.0
        status = "ready" if pct >= WEAK_AREA_THRESHOLD else "needs_more_handover"
        db.add(
            AreaScore(
                attempt_id=attempt.id,
                module=mod,
                score=pct,
                correct_count=m["correct"],
                question_count=m["count"],
                weight=round(m["max_wp"] / m["count"], 2) if m["count"] else 1.0,
                weighted_points=round(m["wp"], 2),
                max_weighted_points=round(m["max_wp"], 2),
                status=status,
                missed_claim_ids_json=json.dumps(m["missed"]),
            )
        )

    attempt.overall_score = round((total_wp / total_max_wp) * 100.0, 1) if total_max_wp > 0 else 0.0
    attempt.correct_count = correct_count
    attempt.total_questions = len(questions)
    attempt.needs_review_count = needs_review_count
    attempt.status = "submitted"
    attempt.submitted_at = _utcnow()
    db.commit()
    db.refresh(attempt)
    return attempt


def serialize_attempt(db: Session, attempt: AssessmentAttempt, *, include_answer_keys: bool) -> Dict[str, Any]:
    usr = db.get(User, attempt.user_id)
    areas = db.query(AreaScore).filter(AreaScore.attempt_id == attempt.id).order_by(AreaScore.module.asc()).all()
    answers = db.query(AssessmentAnswer).filter(AssessmentAnswer.attempt_id == attempt.id).all()
    q_by_id = {
        q.id: q
        for q in db.query(AssessmentQuestion).filter(AssessmentQuestion.assessment_id == attempt.assessment_id).all()
    }
    feedback = []
    for a in answers:
        q = q_by_id.get(a.question_id)
        item: Dict[str, Any] = {
            "question_id": a.question_id,
            "module": q.module if q else None,
            "question_type": q.question_type if q else None,
            "prompt": q.prompt if q else None,
            "answer_text": a.answer_text,
            "is_correct": a.is_correct,
            "score": a.score,
            "confidence": a.confidence,
            "needs_reviewer_check": a.needs_reviewer_check,
            "heuristic_rationale": a.heuristic_rationale,
            "explanation": q.explanation if q else None,
            "source_claim_ids": _json_list(q.source_claim_ids_json) if q else [],
            "evidence_refs": _json_list(q.evidence_refs_json) if q else [],
        }
        if include_answer_keys and q is not None:
            item["correct_answer"] = q.correct_answer
        feedback.append(item)

    return {
        "id": attempt.id,
        "assessment_id": attempt.assessment_id,
        "handover_id": attempt.handover_id,
        "user_id": attempt.user_id,
        "user_name": usr.name if usr else attempt.user_id,
        "attempt_number": attempt.attempt_number,
        "attempt_kind": attempt.attempt_kind,
        "status": attempt.status,
        "overall_score": attempt.overall_score,
        "correct_count": attempt.correct_count,
        "total_questions": attempt.total_questions,
        "needs_review_count": attempt.needs_review_count,
        "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        "area_scores": [
            {
                "id": ar.id,
                "module": ar.module,
                "score": ar.score,
                "correct_count": ar.correct_count,
                "question_count": ar.question_count,
                "weight": ar.weight,
                "weighted_points": ar.weighted_points,
                "max_weighted_points": ar.max_weighted_points,
                "status": ar.status,
                "missed_claim_ids": _json_list(ar.missed_claim_ids_json),
                "sent_to_interview_at": ar.sent_to_interview_at.isoformat() if ar.sent_to_interview_at else None,
            }
            for ar in areas
        ],
        "answers": feedback,
    }


def compute_readiness_report(
    db: Session,
    handover: Handover,
    *,
    user_id_filter: Optional[str] = None,
    include_answer_keys: bool = False,
) -> Dict[str, Any]:
    """Per-user and per-area readiness summary with baseline vs latest re-assessment delta."""
    q = db.query(AssessmentAttempt).filter(
        AssessmentAttempt.handover_id == handover.id,
        AssessmentAttempt.status == "submitted",
    )
    if user_id_filter:
        q = q.filter(AssessmentAttempt.user_id == user_id_filter)
    attempts = q.order_by(AssessmentAttempt.user_id.asc(), AssessmentAttempt.attempt_number.asc()).all()

    by_user: Dict[str, List[AssessmentAttempt]] = defaultdict(list)
    for att in attempts:
        by_user[att.user_id].append(att)

    participants: List[Dict[str, Any]] = []
    weak_areas: List[Dict[str, Any]] = []
    for uid, u_atts in by_user.items():
        usr = db.get(User, uid)
        baseline = u_atts[0]
        latest = u_atts[-1]
        base_areas = {a.module: a for a in db.query(AreaScore).filter(AreaScore.attempt_id == baseline.id).all()}
        lat_areas = {a.module: a for a in db.query(AreaScore).filter(AreaScore.attempt_id == latest.id).all()}
        area_deltas = []
        for mod in sorted(set(base_areas) | set(lat_areas)):
            b_sc = base_areas[mod].score if mod in base_areas else 0.0
            l_sc = lat_areas[mod].score if mod in lat_areas else 0.0
            cur = lat_areas.get(mod) or base_areas.get(mod)
            area_deltas.append({
                "module": mod,
                "baseline_score": b_sc,
                "latest_score": l_sc,
                "delta": round(l_sc - b_sc, 1) if len(u_atts) > 1 else 0.0,
                "correct_count": cur.correct_count if cur else 0,
                "question_count": cur.question_count if cur else 0,
                "weight": cur.weight if cur else 1.0,
                "status": cur.status if cur else "needs_more_handover",
                "missed_claim_ids": _json_list(cur.missed_claim_ids_json) if cur else [],
            })
            if cur and cur.status == "needs_more_handover":
                weak_areas.append({
                    "user_id": uid,
                    "user_name": usr.name if usr else uid,
                    "module": mod,
                    "score": cur.score,
                    "missed_claim_ids": _json_list(cur.missed_claim_ids_json),
                    "sent_to_interview_at": cur.sent_to_interview_at.isoformat() if cur.sent_to_interview_at else None,
                })

        delta_overall = round((latest.overall_score or 0.0) - (baseline.overall_score or 0.0), 1) if len(u_atts) > 1 else 0.0
        participants.append({
            "user_id": uid,
            "user_name": usr.name if usr else uid,
            "attempt_count": len(u_atts),
            "baseline_score": baseline.overall_score,
            "latest_score": latest.overall_score,
            "delta_overall": delta_overall,
            "needs_help": (latest.overall_score or 0.0) < WEAK_AREA_THRESHOLD or any(a["status"] == "needs_more_handover" for a in area_deltas),
            "areas": area_deltas,
            "attempts": [serialize_attempt(db, a, include_answer_keys=include_answer_keys) for a in u_atts],
        })

    return {
        "handover_id": handover.id,
        "threshold": WEAK_AREA_THRESHOLD,
        "participants": participants,
        "weak_areas": weak_areas,
        "who_needs_help": [
            {"user_id": p["user_id"], "user_name": p["user_name"], "latest_score": p["latest_score"]}
            for p in participants if p["needs_help"]
        ],
    }


def send_weak_areas_to_interview(db: Session, handover: Handover) -> Dict[str, Any]:
    """Create exit-interview follow-up questions for weak areas' missed claims (idempotent)."""
    attempts = (
        db.query(AssessmentAttempt)
        .filter(AssessmentAttempt.handover_id == handover.id, AssessmentAttempt.status == "submitted")
        .all()
    )
    weak_rows = (
        db.query(AreaScore)
        .filter(
            AreaScore.attempt_id.in_([a.id for a in attempts]),
            AreaScore.status == "needs_more_handover",
        )
        .all()
        if attempts else []
    )
    created = 0
    now = _utcnow()
    for ar in weak_rows:
        for cid in _json_list(ar.missed_claim_ids_json):
            claim = db.get(Claim, cid)
            if claim is None or effective_claim_clearance(db, claim) == "restricted":
                continue
            fp = _fp(["readiness_followup", handover.project_id, ar.module, cid])
            exists = db.query(InterviewQuestion).filter(
                InterviewQuestion.project_id == handover.project_id,
                InterviewQuestion.fingerprint == fp,
            ).first()
            if exists is None:
                db.add(
                    InterviewQuestion(
                        project_id=handover.project_id,
                        claim_id=claim.id,
                        module=ar.module,
                        target_person_id=handover.departing_user_id,
                        target_label=claim.owner_name or "unassigned",
                        question=(
                            f"Incoming readiness verification flagged '{ar.module}' as needing more handover "
                            f"around '{claim.title or claim.text[:70]}'. Can you clarify the missing context?"
                        ),
                        gap_type="readiness_weak_area",
                        priority="high",
                        status="open",
                        fingerprint=fp,
                        clearance_level=claim.clearance_level or "team",
                        text_source="template",
                    )
                )
                created += 1
        ar.sent_to_interview_at = now
    db.commit()
    return {"created_interview_questions": created, "weak_areas_processed": len(weak_rows)}
