"""Central Clearance Engine (Phase 7).

Every endpoint touching sources, chunks, claims, evidence, handovers, exports, and assistant
answers routes through this module so permission filtering happens in the backend query/service layer.

Viewer profiles:
- team_lead (admin): everything in the workspace, including restricted, unreviewed, and rejected items.
- team_member: public and team items (never restricted).
- incoming: only human-approved claims (approved / edited) at public/team level, and only approved
  sections of a handover actively shared with that specific incoming user. Never restricted.
- departing: only their own contributions and items they were asked about in interviews, at
  public/team level. Never restricted. No access to handovers or full reports.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from sqlalchemy.orm import Session

from app.engine.types import max_clearance
from app.models import (
    Chunk,
    Claim,
    ClaimEvidence,
    Contradiction,
    Handover,
    HandoverSection,
    InterviewQuestion,
    Source,
    User,
)

VALID_VIEW_AS = ("incoming", "departing")
APPROVED_CLAIM_STATUSES = ("approved", "edited")
SHARED_HANDOVER_STATUSES = ("shared", "acknowledged")


class ClearanceError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class ViewerContext:
    user_id: str
    user_name: str
    actual_role: str
    profile: str  # team_lead | team_member | incoming | departing
    is_preview: bool = False
    preview_role: Optional[str] = None

    @property
    def is_admin(self) -> bool:
        return self.profile == "team_lead" and not self.is_preview

    @property
    def can_see_restricted(self) -> bool:
        return self.profile == "team_lead"


def resolve_viewer_profile(
    user_id: str,
    user_name: str,
    actual_role: str,
    view_as: Optional[str] = None,
) -> ViewerContext:
    """Resolve the effective viewer profile, enforcing that only admins may use read-only view_as preview."""
    if view_as is not None and view_as != "":
        if actual_role != "admin":
            raise ClearanceError(403, "Only workspace admins can preview another role.")
        if view_as not in VALID_VIEW_AS:
            raise ClearanceError(400, "view_as must be 'incoming' or 'departing'.")
        return ViewerContext(
            user_id=user_id,
            user_name=user_name,
            actual_role=actual_role,
            profile=view_as,
            is_preview=True,
            preview_role=view_as,
        )

    profile = "team_lead" if actual_role == "admin" else actual_role
    return ViewerContext(
        user_id=user_id,
        user_name=user_name,
        actual_role=actual_role,
        profile=profile,
        is_preview=False,
        preview_role=None,
    )


def effective_claim_clearance(db: Session, claim: Claim) -> str:
    """Strictest clearance across the claim and its supporting evidence sources, unless admin-overridden."""
    if claim.clearance_override_reason and claim.clearance_overridden_by:
        return claim.clearance_level or "team"

    levels = [claim.clearance_level or "team"]
    ev_rows = db.query(ClaimEvidence).filter(ClaimEvidence.claim_id == claim.id).all()
    src_ids = [ev.source_id for ev in ev_rows if ev.source_id]
    if src_ids:
        for src in db.query(Source).filter(Source.id.in_(src_ids)).all():
            levels.append(src.clearance_level or "team")
    return max_clearance(levels)


def override_claim_clearance(
    db: Session,
    claim: Claim,
    admin_user: User,
    target_level: str,
    reason: str,
) -> Claim:
    """Explicitly mark a restricted claim as team/public with a recorded reviewer reason and timestamp."""
    if target_level not in ("public", "team"):
        raise ClearanceError(400, "Clearance override target must be 'public' or 'team'.")
    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise ClearanceError(400, "A reason is required to override claim clearance.")
    claim.clearance_level = target_level
    claim.clearance_override_reason = clean_reason
    claim.clearance_overridden_by = admin_user.id
    claim.clearance_overridden_at = datetime.now(timezone.utc)
    return claim


def can_view_source(viewer: ViewerContext, source: Source) -> bool:
    if viewer.can_see_restricted:
        return True
    return source.clearance_level != "restricted"


def filter_sources(viewer: ViewerContext, sources: Sequence[Source]) -> List[Source]:
    return [s for s in sources if can_view_source(viewer, s)]


def can_view_chunk(viewer: ViewerContext, chunk: Chunk, source: Optional[Source]) -> bool:
    if viewer.can_see_restricted:
        return True
    if source is None:
        return False
    return can_view_source(viewer, source)


def filter_chunks(viewer: ViewerContext, chunks: Sequence[Chunk], source: Optional[Source]) -> List[Chunk]:
    if not can_view_source(viewer, source) if source else not viewer.can_see_restricted:
        return []
    return list(chunks)


def incoming_has_shared_handover(db: Session, project_id: str, viewer: ViewerContext) -> bool:
    """True if this incoming user has an actively shared handover in this project (or admin previewing)."""
    if viewer.is_preview and viewer.profile == "incoming":
        return True
    return (
        db.query(Handover)
        .filter(
            Handover.project_id == project_id,
            Handover.incoming_user_id == viewer.user_id,
            Handover.status.in_(SHARED_HANDOVER_STATUSES),
            Handover.share_revoked_at.is_(None),
        )
        .first()
        is not None
    )


def _departing_interview_claim_ids(db: Session, project_id: str, viewer: ViewerContext) -> Set[str]:
    rows = (
        db.query(InterviewQuestion)
        .filter(
            InterviewQuestion.project_id == project_id,
            InterviewQuestion.clearance_level != "restricted",
        )
        .all()
    )
    name_low = (viewer.user_name or "").strip().lower()
    out: Set[str] = set()
    for q in rows:
        matches_person = (
            q.target_person_id == viewer.user_id
            or (q.target_label and q.target_label.strip().lower() == name_low)
        )
        if matches_person and q.claim_id:
            out.add(q.claim_id)
    return out


def _is_departing_item(claim: Claim, viewer: ViewerContext, interview_claim_ids: Set[str]) -> bool:
    if claim.id in interview_claim_ids:
        return True
    if claim.owner_id and claim.owner_id == viewer.user_id:
        return True
    name_low = (viewer.user_name or "").strip().lower()
    if name_low:
        if claim.owner_name and claim.owner_name.strip().lower() == name_low:
            return True
        if claim.author and claim.author.strip().lower() == name_low:
            return True
    return False


def can_view_claim(
    db: Session,
    viewer: ViewerContext,
    claim: Claim,
    *,
    require_shared_handover_for_incoming: bool = True,
    _interview_claim_ids: Optional[Set[str]] = None,
) -> bool:
    if viewer.profile == "team_lead":
        return True

    if effective_claim_clearance(db, claim) == "restricted":
        return False

    if viewer.profile == "team_member":
        return True

    if viewer.profile == "incoming":
        if claim.review_status not in APPROVED_CLAIM_STATUSES:
            return False
        if require_shared_handover_for_incoming and not incoming_has_shared_handover(db, claim.project_id, viewer):
            return False
        return True

    if viewer.profile == "departing":
        ids = _interview_claim_ids if _interview_claim_ids is not None else _departing_interview_claim_ids(db, claim.project_id, viewer)
        return _is_departing_item(claim, viewer, ids)

    return False


def filter_claims(
    db: Session,
    viewer: ViewerContext,
    claims: Sequence[Claim],
    *,
    require_shared_handover_for_incoming: bool = True,
) -> List[Claim]:
    if viewer.profile == "team_lead":
        return list(claims)
    if not claims:
        return []
    project_id = claims[0].project_id
    if viewer.profile == "incoming" and require_shared_handover_for_incoming:
        if not incoming_has_shared_handover(db, project_id, viewer):
            return []
    interview_ids = (
        _departing_interview_claim_ids(db, project_id, viewer)
        if viewer.profile == "departing"
        else set()
    )
    return [
        c
        for c in claims
        if can_view_claim(
            db,
            viewer,
            c,
            require_shared_handover_for_incoming=require_shared_handover_for_incoming,
            _interview_claim_ids=interview_ids,
        )
    ]


def filter_evidence_for_viewer(
    db: Session,
    viewer: ViewerContext,
    ev_rows: Sequence[ClaimEvidence],
) -> List[ClaimEvidence]:
    if viewer.can_see_restricted:
        return list(ev_rows)
    out: List[ClaimEvidence] = []
    for ev in ev_rows:
        if ev.evidence_type == "interview_answer" or not ev.source_id:
            out.append(ev)
            continue
        src = db.get(Source, ev.source_id)
        if src and can_view_source(viewer, src):
            out.append(ev)
    return out


def can_view_contradiction(viewer: ViewerContext, ctr: Contradiction) -> bool:
    if viewer.can_see_restricted:
        return True
    if viewer.profile in ("incoming", "departing"):
        return False
    return ctr.clearance_level != "restricted"


def can_view_handover(viewer: ViewerContext, handover: Handover) -> bool:
    if viewer.profile == "team_lead":
        return True
    if viewer.profile == "incoming":
        if viewer.is_preview:
            return True
        return (
            handover.incoming_user_id == viewer.user_id
            and handover.status in SHARED_HANDOVER_STATUSES
            and handover.share_revoked_at is None
        )
    # departing and team_member have no access to full handover reports
    return False


def _filter_section_content(content: Dict[str, Any], viewer: ViewerContext) -> Dict[str, Any]:
    """Strip restricted or unapproved items from a handover section's JSON payload for incoming viewers."""
    if viewer.profile == "team_lead":
        return content

    filtered = dict(content)
    if "items" in filtered and isinstance(filtered["items"], list):
        safe_items = []
        for item in filtered["items"]:
            if item.get("clearance_level") == "restricted":
                continue
            # Incoming never sees unreviewed or rejected claims as established facts
            rstatus = item.get("review_status")
            if rstatus and rstatus not in APPROVED_CLAIM_STATUSES and not item.get("is_gap_summary"):
                continue
            safe_items.append(item)
        filtered["items"] = safe_items

    if "plan" in filtered and isinstance(filtered["plan"], list):
        filtered["plan"] = [
            p for p in filtered["plan"] if p.get("clearance_level") != "restricted"
        ]

    # Never expose admin-only needs_review / unapproved buffer to incoming
    filtered.pop("needs_review_items", None)
    filtered.pop("unapproved_plan_preview", None)
    for gap_list_key in ("open_contradictions", "unanswered_questions"):
        if gap_list_key in filtered and isinstance(filtered[gap_list_key], list):
            filtered[gap_list_key] = [
                g for g in filtered[gap_list_key] if g.get("clearance_level") != "restricted"
            ]
    return filtered


def filter_handover_sections(
    viewer: ViewerContext,
    handover: Handover,
    sections: Sequence[HandoverSection],
) -> List[Dict[str, Any]]:
    """Return viewer-safe section dicts. Incoming sees only approved sections with restricted/unapproved items stripped."""
    if not can_view_handover(viewer, handover):
        return []

    out: List[Dict[str, Any]] = []
    for sec in sorted(sections, key=lambda s: (s.ordinal, s.id)):
        if viewer.profile == "incoming" and sec.review_status not in ("approved", "approved_with_gaps"):
            continue
        try:
            content = json.loads(sec.content_json) if sec.content_json else {}
        except json.JSONDecodeError:
            content = {}
        safe_content = _filter_section_content(content, viewer)
        out.append(
            {
                "id": sec.id,
                "section_key": sec.section_key,
                "title": sec.title or sec.section_key.replace("_", " ").title(),
                "ordinal": sec.ordinal,
                "review_status": sec.review_status,
                "approved_with_gaps": sec.approved_with_gaps,
                "gap_note": sec.gap_note,
                "reviewed_by": sec.reviewed_by,
                "reviewed_at": sec.reviewed_at,
                "content": safe_content,
            }
        )
    return out
