"""Handover generation, readiness scoring, review workflow, and PDF export (Phase 7)."""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from fpdf import FPDF
from sqlalchemy.orm import Session

from app.engine.clearance import (
    ViewerContext,
    can_view_claim,
    can_view_handover,
    filter_handover_sections,
    max_clearance,
)
from app.engine.plan import build_ranked_plan
from app.models import (
    Claim,
    ClaimEvidence,
    Contradiction,
    Handover,
    HandoverEvent,
    HandoverSection,
    InterviewQuestion,
    Project,
    Source,
    User,
)

SECTION_DEFS: List[Tuple[str, str]] = [
    ("overview", "1. Overview"),
    ("responsibilities_contributions", "2. Responsibilities and contributions"),
    ("completed_work", "3. Completed work"),
    ("work_in_progress", "4. Work in progress"),
    ("pending_tasks", "5. Pending tasks"),
    ("decisions_rationale", "6. Key decisions and rationale"),
    ("dependencies_ownership", "7. Dependencies and ownership"),
    ("bugs_blockers", "8. Known bugs and blockers"),
    ("knowledge_gaps", "9. Knowledge gaps and unverified items"),
    ("recommended_next_steps", "10. Recommended next steps"),
]

_RATIONALE_RE = re.compile(
    r"\b(because|since|rationale|so that|in order to|to avoid|due to|chosen for|reason)\b",
    re.IGNORECASE,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _is_approved_claim(claim: Claim) -> bool:
    return claim.review_status in ("approved", "edited")


def _parse_attrs(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            val = json.loads(raw)
            return val if isinstance(val, dict) else {}
        except Exception:
            return {}
    return {}


def _ev_locator(ev: ClaimEvidence) -> Optional[str]:
    ch = getattr(ev, "chunk", None)
    return ch.locator if ch else None


def _evidence_refs(
    ev_rows: Sequence[ClaimEvidence],
    sources_by_id: Dict[str, Source],
) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for ev in ev_rows[:6]:
        src = sources_by_id.get(ev.source_id) if ev.source_id else None
        refs.append(
            {
                "evidence_id": ev.id,
                "source_id": ev.source_id,
                "source_name": src.filename if src else None,
                "locator": _ev_locator(ev),
                "excerpt": (ev.excerpt or "")[:240],
                "evidence_type": ev.evidence_type,
                "author_name": ev.author,
            }
        )
    return refs


def _claim_item(
    claim: Claim,
    ev_rows: Sequence[ClaimEvidence],
    sources_by_id: Dict[str, Source],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "claim_id": claim.id,
        "claim_ids": [claim.id],
        "title": claim.title or claim.text[:90],
        "statement": claim.text,
        "claim_type": claim.claim_type,
        "module": claim.module,
        "owner": claim.owner_name,
        "verification_status": claim.verification_status,
        "review_status": claim.review_status,
        "clearance_level": claim.clearance_level,
        "evidence": _evidence_refs(ev_rows, sources_by_id),
    }
    if extra:
        item.update(extra)
    return item


def compute_readiness(
    in_scope_claims: Sequence[Claim],
    evidence_by_claim: Dict[str, List[ClaimEvidence]],
    open_contradictions: Sequence[Contradiction],
    open_questions: Sequence[InterviewQuestion],
) -> Dict[str, Any]:
    """Explainable readiness score (0-100) with explicit component breakdown."""
    total = len(in_scope_claims)
    if total == 0:
        return {
            "score": 0,
            "total_claims": 0,
            "evidence_coverage": 0.0,
            "verification_completeness": 0.0,
            "contradiction_penalty": 0,
            "question_penalty": 0,
            "open_contradictions_count": len(open_contradictions),
            "unanswered_questions_count": len(open_questions),
            "formula": "No claims in scope yet (score = 0).",
        }

    with_evidence = sum(1 for c in in_scope_claims if len(evidence_by_claim.get(c.id, [])) > 0)
    approved_count = sum(1 for c in in_scope_claims if _is_approved_claim(c))

    evidence_coverage = round(with_evidence / total, 4)
    verification_completeness = round(approved_count / total, 4)

    high_ctrs = sum(1 for ctr in open_contradictions if (ctr.severity or "").lower() == "high")
    other_ctrs = len(open_contradictions) - high_ctrs
    contradiction_penalty = min(30, high_ctrs * 10 + other_ctrs * 5)
    question_penalty = min(25, len(open_questions) * 4)

    raw_score = (
        (evidence_coverage * 40.0)
        + (verification_completeness * 60.0)
        - contradiction_penalty
        - question_penalty
    )
    score = max(0, min(100, int(round(raw_score))))

    return {
        "score": score,
        "total_claims": total,
        "claims_with_evidence": with_evidence,
        "approved_claims": approved_count,
        "evidence_coverage": evidence_coverage,
        "verification_completeness": verification_completeness,
        "contradiction_penalty": contradiction_penalty,
        "question_penalty": question_penalty,
        "open_contradictions_count": len(open_contradictions),
        "unanswered_questions_count": len(open_questions),
        "formula": (
            "score = clamp(round(40 * evidence_coverage + 60 * verification_completeness "
            "- contradiction_penalty - question_penalty), 0, 100)"
        ),
    }


def _has_rationale(claim: Claim, ev_rows: Sequence[ClaimEvidence]) -> Optional[str]:
    attrs = _parse_attrs(claim.attrs_json)
    if isinstance(attrs.get("rationale"), str) and attrs["rationale"].strip():
        return attrs["rationale"].strip()
    if _RATIONALE_RE.search(claim.text or ""):
        return claim.text
    for ev in ev_rows:
        if ev.excerpt and _RATIONALE_RE.search(ev.excerpt):
            return ev.excerpt[:260]
    return None


def _smooth_summary_with_llm(
    section_key: str,
    base_summary: str,
    valid_claim_ids: Set[str],
    llm_caller: Optional[Callable[[str], str]] = None,
) -> Tuple[str, str]:
    """Optionally smooth wording with LLM if configured; verify cited claim IDs strictly."""
    if not valid_claim_ids:
        return base_summary, "deterministic"
    if llm_caller is None and not os.getenv("LLM_API_KEY"):
        return base_summary, "deterministic"

    prompt = (
        f"Rewrite the handover section summary for '{section_key}' cleanly in plain English. "
        f"Every sentence MUST cite at least one existing claim ID in brackets like [claim_id] "
        f"drawn ONLY from: {sorted(valid_claim_ids)}. Do not invent facts.\n\nDraft:\n{base_summary}"
    )
    try:
        if llm_caller is not None:
            candidate = llm_caller(prompt)
        else:
            from app.engine.llm_client import call_llm_text  # type: ignore

            candidate = call_llm_text(prompt)
        if not candidate or not candidate.strip():
            return base_summary, "deterministic"
        cited = set(re.findall(r"\[([A-Za-z0-9\-]+)\]", candidate))
        if not cited or not cited.issubset(valid_claim_ids):
            return base_summary, "deterministic"
        return candidate.strip(), "llm"
    except Exception:
        return base_summary, "deterministic"


def record_handover_event(
    db: Session,
    handover_id: str,
    actor_user: Optional[User],
    action: str,
    section_key: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> HandoverEvent:
    ev = HandoverEvent(
        handover_id=handover_id,
        actor_id=actor_user.id if actor_user else None,
        action=action,
        section_key=section_key,
        detail=json.dumps(detail or {}),
    )
    db.add(ev)
    return ev


def generate_handover(
    db: Session,
    project: Project,
    created_by: User,
    *,
    departing_user_id: Optional[str] = None,
    target_user_id: Optional[str] = None,
    title: Optional[str] = None,
    period_label: Optional[str] = None,
    llm_caller: Optional[Callable[[str], str]] = None,
) -> Handover:
    """Assemble and persist a complete Handover draft with 10 structured sections."""
    claims_all = (
        db.query(Claim)
        .filter(Claim.project_id == project.id)
        .order_by(Claim.created_at.asc())
        .all()
    )
    sources_all = db.query(Source).filter(Source.project_id == project.id).all()
    sources_by_id = {s.id: s for s in sources_all}
    ev_all = (
        db.query(ClaimEvidence)
        .join(Claim, Claim.id == ClaimEvidence.claim_id)
        .filter(Claim.project_id == project.id)
        .all()
    )
    evidence_by_claim: Dict[str, List[ClaimEvidence]] = defaultdict(list)
    for ev in ev_all:
        evidence_by_claim[ev.claim_id].append(ev)

    ctrs_all = (
        db.query(Contradiction)
        .filter(Contradiction.project_id == project.id)
        .order_by(Contradiction.created_at.desc())
        .all()
    )
    open_ctrs = [c for c in ctrs_all if c.status == "open"]

    questions_all = (
        db.query(InterviewQuestion)
        .filter(InterviewQuestion.project_id == project.id)
        .order_by(InterviewQuestion.priority.asc())
        .all()
    )
    open_questions = [q for q in questions_all if q.status in ("unanswered", "open")]

    # Departing filter if a specific departing user name/id was provided
    departing_user: Optional[User] = (
        db.query(User).filter(User.id == departing_user_id).first() if departing_user_id else None
    )

    approved_claims = [c for c in claims_all if _is_approved_claim(c)]
    needs_review_claims = [c for c in claims_all if not _is_approved_claim(c)]

    # Build dependency graph / ranked continuation plan over all claims for admin visibility;
    # clearance engine filters restricted/unapproved items out when serving incoming viewers.
    plan_items, cycle_gaps = build_ranked_plan(
        approved_claims,
        open_ctrs,
        open_questions,
        evidence_by_claim,
        sources_by_id,
    )
    # Also compute admin-only unreviewed plan items for awareness in knowledge gaps.
    admin_plan_all, _ = build_ranked_plan(
        claims_all,
        open_ctrs,
        open_questions,
        evidence_by_claim,
        sources_by_id,
    )

    readiness = compute_readiness(claims_all, evidence_by_claim, open_ctrs, open_questions)

    # Categorize approved claims into sections
    modules = sorted({c.module for c in approved_claims if c.module})
    completed_items: List[Dict[str, Any]] = []
    wip_items: List[Dict[str, Any]] = []
    pending_items: List[Dict[str, Any]] = []
    decision_items: List[Dict[str, Any]] = []
    blocker_items: List[Dict[str, Any]] = []
    contribution_items: List[Dict[str, Any]] = []
    dep_items: List[Dict[str, Any]] = []
    dep_edges: List[Dict[str, str]] = []
    module_owners: Dict[str, Set[str]] = defaultdict(set)

    for c in approved_claims:
        evs = evidence_by_claim.get(c.id, [])
        attrs = _parse_attrs(c.attrs_json)
        status = str(attrs.get("status") or "").lower()
        if c.module and c.owner_name:
            module_owners[c.module].add(c.owner_name)

        if c.claim_type in ("contribution", "ownership"):
            if departing_user and c.owner_name and departing_user.name.lower() not in c.owner_name.lower():
                pass
            contribution_items.append(_claim_item(c, evs, sources_by_id))

        if c.claim_type == "task_status":
            if status == "completed" and c.verification_status == "verified" and evs:
                completed_items.append(_claim_item(c, evs, sources_by_id, {"status": "completed"}))
            elif status == "in_progress":
                wip_items.append(_claim_item(c, evs, sources_by_id, {"status": "in_progress"}))
            elif status in ("pending", "unknown", ""):
                pending_items.append(_claim_item(c, evs, sources_by_id, {"status": status or "pending"}))
            elif status == "blocked":
                blocker_items.append(_claim_item(c, evs, sources_by_id, {"status": "blocked"}))
        elif c.claim_type == "testing":
            pending_items.append(_claim_item(c, evs, sources_by_id, {"status": "testing_pending"}))
        elif c.claim_type == "decision":
            rationale = _has_rationale(c, evs)
            decision_items.append(
                _claim_item(
                    c,
                    evs,
                    sources_by_id,
                    {"rationale": rationale if rationale else "Rationale not recorded."},
                )
            )
        elif c.claim_type == "blocker":
            blocker_items.append(_claim_item(c, evs, sources_by_id, {"status": "blocked"}))
        elif c.claim_type == "dependency":
            dep_items.append(_claim_item(c, evs, sources_by_id))
            src_node = str(attrs.get("from_task") or c.module or c.title)
            tgt_node = str(attrs.get("depends_on") or "")
            if src_node and tgt_node:
                dep_edges.append({"from": src_node, "to": tgt_node, "claim_id": c.id})

        if c.claim_type == "ownership":
            dep_items.append(_claim_item(c, evs, sources_by_id))

    # Undocumented modules (modules present across any claim without an approved decision or doc note)
    all_modules = sorted({c.module for c in claims_all if c.module})
    documented_modules = {
        c.module for c in approved_claims if c.module and c.claim_type in ("decision", "contribution")
    }
    undocumented_modules = [m for m in all_modules if m not in documented_modules]

    needs_review_items = [
        _claim_item(c, evidence_by_claim.get(c.id, []), sources_by_id)
        for c in needs_review_claims
    ]
    open_ctr_items = [
        {
            "contradiction_id": ctr.id,
            "summary": ctr.reason,
            "severity": ctr.severity,
            "module": (ctr.claims[0].module if ctr.claims else None),
            "clearance_level": ctr.clearance_level,
        }
        for ctr in open_ctrs
    ]
    open_q_items = [
        {
            "question_id": q.id,
            "question_text": q.question,
            "module": q.module,
            "target_person": q.target_label or "unassigned",
            "clearance_level": q.clearance_level,
        }
        for q in open_questions
    ]

    approved_claim_ids = {c.id for c in approved_claims}

    overview_summary = (
        f"Project '{project.name}' handover covers {len(approved_claims)} human-approved claim(s) "
        f"across {len(modules)} module(s). Readiness score is {readiness['score']}/100."
    )
    if period_label:
        overview_summary += f" Period: {period_label}."

    sections_payload: Dict[str, Tuple[str, Dict[str, Any]]] = {
        "overview": (
            overview_summary,
            {
                "project_id": project.id,
                "project_name": project.name,
                "departing_user": departing_user.name if departing_user else None,
                "period_label": period_label,
                "modules": modules,
                "readiness": readiness,
                "approved_claim_count": len(approved_claims),
                "needs_review_count": len(needs_review_claims),
                "open_contradictions_count": len(open_ctrs),
                "unanswered_questions_count": len(open_questions),
            },
        ),
        "responsibilities_contributions": (
            f"{len(contribution_items)} approved ownership and contribution record(s).",
            {
                "items": contribution_items,
                "module_owners": {k: sorted(v) for k, v in sorted(module_owners.items())},
            },
        ),
        "completed_work": (
            f"{len(completed_items)} verified completed work item(s).",
            {"items": completed_items},
        ),
        "work_in_progress": (
            f"{len(wip_items)} approved in-progress item(s).",
            {"items": wip_items},
        ),
        "pending_tasks": (
            f"{len(pending_items)} approved pending task or testing item(s).",
            {"items": pending_items},
        ),
        "decisions_rationale": (
            f"{len(decision_items)} approved decision(s) recorded.",
            {"items": decision_items},
        ),
        "dependencies_ownership": (
            f"{len(dep_items)} dependency/ownership claim(s) across {len(all_modules)} module(s).",
            {
                "items": dep_items,
                "edges": dep_edges,
                "module_owners": {k: sorted(v) for k, v in sorted(module_owners.items())},
            },
        ),
        "bugs_blockers": (
            f"{len(blocker_items)} approved bug or blocker item(s).",
            {"items": blocker_items},
        ),
        "knowledge_gaps": (
            (
                f"{len(needs_review_items)} claim(s) awaiting review, "
                f"{len(open_ctr_items)} open contradiction(s), "
                f"{len(open_q_items)} unanswered interview question(s)."
            ),
            {
                "needs_review_items": needs_review_items,
                "open_contradictions": open_ctr_items,
                "unanswered_questions": open_q_items,
                "undocumented_modules": undocumented_modules,
                "cycle_gaps": cycle_gaps,
                "unapproved_plan_preview": admin_plan_all,
            },
        ),
        "recommended_next_steps": (
            f"{len(plan_items)} ranked continuation step(s) derived from approved evidence.",
            {"items": plan_items},
        ),
    }

    # Optional LLM smoothing per section (strict claim-id verification)
    dep_uid = departing_user_id or created_by.id
    inc_uid = target_user_id or created_by.id
    handover = Handover(
        project_id=project.id,
        departing_user_id=dep_uid,
        incoming_user_id=inc_uid,
        status="draft",
        readiness_score=float(readiness["score"]),
        readiness_json=json.dumps(readiness),
        snapshot_json=json.dumps(
            {
                "generated_at": _iso(_utcnow()),
                "project_id": project.id,
                "title": title or f"{project.name} Handover",
                "period_label": period_label,
                "approved_claims": [
                    {
                        "id": c.id,
                        "title": c.title or c.text[:90],
                        "review_status": c.review_status,
                        "verification_status": c.verification_status,
                        "clearance_level": c.clearance_level,
                    }
                    for c in approved_claims
                ],
                "source_ids": [s.id for s in sources_all],
            }
        ),
    )
    db.add(handover)
    db.flush()

    for idx, (sec_key, sec_title) in enumerate(SECTION_DEFS, start=1):
        summary_md, body_dict = sections_payload[sec_key]
        smoothed, _ = _smooth_summary_with_llm(sec_key, summary_md, approved_claim_ids, llm_caller)
        body_dict["summary"] = smoothed
        body_dict["summary_md"] = smoothed
        section = HandoverSection(
            handover_id=handover.id,
            section_key=sec_key,
            title=sec_title,
            ordinal=idx,
            content_json=json.dumps(body_dict),
            review_status="draft",
        )
        db.add(section)

    record_handover_event(
        db,
        handover.id,
        created_by,
        "generated",
        detail={"readiness_score": readiness["score"]},
    )
    db.commit()
    db.refresh(handover)
    return handover


def review_handover_section(
    db: Session,
    handover: Handover,
    section_key: str,
    reviewer: User,
    *,
    review_status: Optional[str] = None,
    content_md: Optional[str] = None,
    body_json: Optional[Dict[str, Any]] = None,
    approved_with_gaps: Optional[bool] = None,
    gap_note: Optional[str] = None,
) -> HandoverSection:
    sec = (
        db.query(HandoverSection)
        .filter(HandoverSection.handover_id == handover.id, HandoverSection.section_key == section_key)
        .first()
    )
    if sec is None:
        raise ValueError(f"Section '{section_key}' not found")

    old_json = sec.content_json
    try:
        cur_content = json.loads(sec.content_json) if sec.content_json else {}
    except Exception:
        cur_content = {}
    if body_json is not None:
        cur_content = dict(body_json)
    if content_md is not None:
        cur_content["summary"] = content_md
        cur_content["summary_md"] = content_md
    sec.content_json = json.dumps(cur_content)

    if approved_with_gaps is not None:
        sec.approved_with_gaps = bool(approved_with_gaps)
    if gap_note is not None:
        sec.gap_note = gap_note
    if review_status is not None:
        if review_status not in ("draft", "unreviewed", "approved", "approved_with_gaps", "flagged", "rejected"):
            raise ValueError("Invalid section review_status")
        if review_status == "approved_with_gaps":
            sec.approved_with_gaps = True
            if not (sec.gap_note and sec.gap_note.strip()):
                raise ValueError("gap_note is required when approving a section with gaps")
        sec.review_status = review_status

    sec.reviewed_by = reviewer.id
    sec.reviewed_at = _utcnow()
    sec.updated_at = _utcnow()
    handover.updated_at = _utcnow()

    ev = HandoverEvent(
        handover_id=handover.id,
        actor_id=reviewer.id,
        action="section_reviewed",
        section_key=section_key,
        detail=json.dumps(
            {
                "review_status": sec.review_status,
                "approved_with_gaps": sec.approved_with_gaps,
                "gap_note": sec.gap_note,
            }
        ),
        old_content_json=old_json,
        new_content_json=sec.content_json,
    )
    db.add(ev)
    db.commit()
    db.refresh(sec)
    return sec


def approve_handover(db: Session, handover: Handover, approver: User) -> Handover:
    sections = (
        db.query(HandoverSection)
        .filter(HandoverSection.handover_id == handover.id)
        .order_by(HandoverSection.ordinal.asc())
        .all()
    )
    unapproved = [
        s.section_key
        for s in sections
        if s.review_status not in ("approved", "approved_with_gaps")
    ]
    if unapproved:
        raise ValueError(
            "All sections must be approved or approved_with_gaps before approving handover: "
            + ", ".join(unapproved)
        )
    missing_notes = [
        s.section_key
        for s in sections
        if s.review_status == "approved_with_gaps" and not (s.gap_note and s.gap_note.strip())
    ]
    if missing_notes:
        raise ValueError("Sections approved_with_gaps require a gap_note: " + ", ".join(missing_notes))

    handover.status = "approved"
    handover.approved_by = approver.id
    handover.approved_at = _utcnow()
    handover.updated_at = _utcnow()

    record_handover_event(
        db,
        handover.id,
        approver,
        "approved",
        detail={"section_count": len(sections)},
    )
    db.commit()
    db.refresh(handover)
    return handover


def share_handover(
    db: Session,
    handover: Handover,
    actor: User,
    target_user_id: str,
) -> Handover:
    if handover.status not in ("approved", "shared", "acknowledged"):
        raise ValueError("Handover must be approved before sharing")
    handover.incoming_user_id = target_user_id
    handover.status = "shared"
    handover.shared_by = actor.id
    handover.shared_at = _utcnow()
    handover.share_revoked_at = None
    handover.updated_at = _utcnow()

    record_handover_event(
        db,
        handover.id,
        actor,
        "shared",
        detail={"incoming_user_id": target_user_id},
    )
    db.commit()
    db.refresh(handover)
    return handover


def revoke_handover_share(db: Session, handover: Handover, actor: User) -> Handover:
    handover.share_revoked_at = _utcnow()
    if handover.status == "shared":
        handover.status = "approved"
    handover.updated_at = _utcnow()

    record_handover_event(
        db,
        handover.id,
        actor,
        "share_revoked",
        detail={"previous_incoming_user_id": handover.incoming_user_id},
    )
    db.commit()
    db.refresh(handover)
    return handover


def acknowledge_handover(db: Session, handover: Handover, incoming_user: User) -> Handover:
    if handover.share_revoked_at is not None or handover.status not in ("shared", "acknowledged"):
        raise ValueError("Handover is not currently shared")
    if handover.incoming_user_id != incoming_user.id:
        raise PermissionError("Only the targeted incoming member can acknowledge this handover")
    handover.status = "acknowledged"
    handover.acknowledged_by = incoming_user.id
    handover.acknowledged_at = _utcnow()
    handover.updated_at = _utcnow()

    record_handover_event(
        db,
        handover.id,
        incoming_user,
        "acknowledged",
        detail={"acknowledged_by": incoming_user.id},
    )
    db.commit()
    db.refresh(handover)
    return handover


def _pdf_safe(text: str) -> str:
    return (text or "").encode("latin-1", "replace").decode("latin-1")


def render_handover_pdf(
    db: Session,
    handover: Handover,
    viewer: ViewerContext,
) -> bytes:
    """Render a clearance-filtered handover report to PDF bytes via fpdf2."""
    if not can_view_handover(viewer, handover):
        raise PermissionError("Handover not visible for current viewer profile")

    sections = (
        db.query(HandoverSection)
        .filter(HandoverSection.handover_id == handover.id)
        .order_by(HandoverSection.ordinal.asc())
        .all()
    )
    visible_sections = filter_handover_sections(viewer, handover, sections)

    # Filter item-level claims strictly by clearance engine as well
    all_claim_ids: Set[str] = set()
    for sec in visible_sections:
        body = sec.get("content") or {}
        for item in body.get("items") or []:
            for cid in item.get("claim_ids") or []:
                all_claim_ids.add(cid)
    claims_map: Dict[str, Claim] = {}
    if all_claim_ids:
        for c in db.query(Claim).filter(Claim.id.in_(list(all_claim_ids))).all():
            claims_map[c.id] = c

    snap = _parse_attrs(handover.snapshot_json)
    title_str = snap.get("title") or "TRACE Handover Report"

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _pdf_safe(title_str), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 10)
    meta_line = (
        f"Status: {handover.status}  |  "
        f"Readiness: {int(round(handover.readiness_score or 0))}/100  |  Viewer: {viewer.profile}"
    )
    pdf.cell(0, 6, _pdf_safe(meta_line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    for sec in visible_sections:
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(pdf.epw, 8, _pdf_safe(sec.get("title") or sec["section_key"]), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        body = sec.get("content") or {}
        summary = body.get("summary") or body.get("summary_md") or ""
        if summary:
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(pdf.epw, 5, _pdf_safe(summary), new_x="LMARGIN", new_y="NEXT")

        for item in body.get("items") or []:
            cids = item.get("claim_ids") or []
            if cids and not all(
                cid in claims_map and can_view_claim(db, viewer, claims_map[cid], require_shared_handover_for_incoming=False)
                for cid in cids
            ):
                continue
            badge = f"[{item.get('verification_status', 'unknown')}]"
            line = f"- {item.get('title', '')} {badge} (claims: {', '.join(cids)})"
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(pdf.epw, 5, _pdf_safe(line), new_x="LMARGIN", new_y="NEXT")
            if item.get("rationale"):
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(pdf.epw, 5, _pdf_safe(f"  Rationale: {item['rationale']}"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    out = pdf.output()
    return bytes(out)
