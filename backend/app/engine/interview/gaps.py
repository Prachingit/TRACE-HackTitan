"""Gap identification from real claims and contradictions. Nothing here is keyed to any dataset."""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.engine.types import DOC_SOURCE_TYPES, GENERIC_MODULES, max_clearance
from app.models import (
    Claim,
    ClaimEvidence,
    Contradiction,
    ContradictionClaim,
    Membership,
    Project,
    Source,
    User,
)

RATIONALE_WORDS = ("because", "since ", "due to", "so that", "in order to", "reason", "to avoid", "to reduce", "to ensure")


@dataclass
class Gap:
    gap_type: str
    module: str
    priority: str  # high | medium | low
    fingerprint: str
    facts: Dict[str, Any]
    claim_id: Optional[str] = None
    contradiction_id: Optional[str] = None
    claim_ids: List[str] = field(default_factory=list)
    clearance: str = "team"
    target_person_id: Optional[str] = None
    target_label: str = "unassigned"


def _fp(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def _attrs(c: Claim) -> Dict[str, Any]:
    if not c.attrs_json:
        return {}
    try:
        return json.loads(c.attrs_json) or {}
    except json.JSONDecodeError:
        return {}


class _Ctx:
    """Preloaded project data so gap rules stay query-free and easy to test."""

    def __init__(self, db: Session, project: Project):
        self.project = project
        self.claims: List[Claim] = db.query(Claim).filter(Claim.project_id == project.id).all()
        self.claim_by_id = {c.id: c for c in self.claims}
        self.sources = {s.id: s for s in db.query(Source).filter(Source.project_id == project.id).all()}
        self.evidence: Dict[str, List[ClaimEvidence]] = {}
        if self.claims:
            ids = [c.id for c in self.claims]
            for ev in db.query(ClaimEvidence).filter(ClaimEvidence.claim_id.in_(ids)).all():
                self.evidence.setdefault(ev.claim_id, []).append(ev)
        self.open_ctrs: List[Contradiction] = (
            db.query(Contradiction)
            .filter(Contradiction.project_id == project.id, Contradiction.status == "open")
            .order_by(Contradiction.id)
            .all()
        )
        self.ctr_claims: Dict[str, List[str]] = {}
        for cc in db.query(ContradictionClaim).filter(
            ContradictionClaim.contradiction_id.in_([c.id for c in self.open_ctrs] or [""])
        ).all():
            self.ctr_claims.setdefault(cc.contradiction_id, []).append(cc.claim_id)

        rows = (
            db.query(Membership, User)
            .join(User, User.id == Membership.user_id)
            .filter(Membership.workspace_id == project.workspace_id)
            .all()
        )
        self.users_by_name = {u.name.strip().lower(): u for _, u in rows}
        self.departing = [u for m, u in rows if m.role == "departing"]

    def source_name(self, c: Claim) -> str:
        for ev in self.evidence.get(c.id, []):
            if ev.evidence_type != "interview_answer" and ev.source_id in self.sources:
                return self.sources[ev.source_id].filename
        return "the recorded evidence"

    def has_doc_evidence(self, c: Claim) -> bool:
        for ev in self.evidence.get(c.id, []):
            s = self.sources.get(ev.source_id) if ev.source_id else None
            if s and s.type in DOC_SOURCE_TYPES:
                return True
        return False

    def title(self, c: Claim) -> str:
        return (c.title or c.text or "")[:100]

    def target(self, claims: List[Claim], departing_first: bool) -> Tuple[Optional[str], str]:
        def owner_target() -> Optional[Tuple[Optional[str], str]]:
            for c in claims:
                if c.owner_id:
                    u = next((x for x in self.users_by_name.values() if x.id == c.owner_id), None)
                    return c.owner_id, (c.owner_name or (u.name if u else "unassigned"))
            for c in claims:
                if c.owner_name:
                    u = self.users_by_name.get(c.owner_name.strip().lower())
                    return (u.id if u else None), (u.name if u else c.owner_name)
            return None

        def departing_target() -> Optional[Tuple[Optional[str], str]]:
            if len(self.departing) == 1:
                return self.departing[0].id, self.departing[0].name
            return None

        order = (departing_target, owner_target) if departing_first else (owner_target, departing_target)
        for fn in order:
            t = fn()
            if t:
                return t
        return None, "unassigned"


def _claim_fp(c: Claim) -> str:
    return c.fingerprint or c.id


def _most_common_module(claims: List[Claim]) -> str:
    counts: Dict[str, int] = {}
    for c in claims:
        if c.module not in GENERIC_MODULES:
            counts[c.module] = counts.get(c.module, 0) + 1
    if counts:
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return claims[0].module if claims else "general"


def _claim_state(c: Claim) -> str:
    a = _attrs(c)
    if c.claim_type == "task_status":
        return str(a.get("raw_status") or a.get("status") or "unknown")
    if c.claim_type == "testing":
        return f"testing {a.get('testing_status') or 'unknown'}"
    if c.claim_type == "blocker":
        return "blocked"
    return c.claim_type


def _contradiction_gap(ctx: _Ctx, ctr: Contradiction) -> Gap:
    claims = [ctx.claim_by_id[i] for i in ctx.ctr_claims.get(ctr.id, []) if i in ctx.claim_by_id]
    claims.sort(key=lambda c: c.id)
    module = _most_common_module(claims) if claims else "general"
    rule = ctr.rule_code
    facts: Dict[str, Any] = {"contradiction_id": ctr.id, "rule_code": rule, "module": module, "reason": ctr.reason}

    if rule == "CONFLICTING_OWNERSHIP":
        seen: Dict[str, Dict[str, str]] = {}
        for c in claims:
            if c.owner_name:
                seen.setdefault(c.owner_name.strip().lower(), {"owner": c.owner_name.strip(), "source": ctx.source_name(c)})
        facts["owners"] = list(seen.values())[:2]
    elif rule == "STATUS_WITHOUT_EVIDENCE":
        c = next((x for x in claims if x.claim_type == "task_status"), claims[0] if claims else None)
        if c is not None:
            facts.update(title=ctx.title(c), raw_status=_claim_state(c), module=c.module)
    elif rule == "CONFLICTING_STATUS":
        topical = [c for c in claims if _attrs(c).get("topic") and _attrs(c).get("choice")]
        distinct = {str(_attrs(c)["choice"]) for c in topical}
        if len(distinct) >= 2:
            first, second = [], []
            for c in topical:
                (first if str(_attrs(c)["choice"]) == str(_attrs(topical[0])["choice"]) else second).append(c)
            a, b = first[0], second[0]
            facts.update(
                topic=str(_attrs(a)["topic"]),
                choices=[
                    {"choice": str(_attrs(a)["choice"]), "source": ctx.source_name(a)},
                    {"choice": str(_attrs(b)["choice"]), "source": ctx.source_name(b)},
                ],
            )
        else:
            picks: List[Claim] = []
            seen_src = set()
            for c in claims:
                sn = ctx.source_name(c)
                if sn not in seen_src and c.claim_type in ("task_status", "testing", "blocker"):
                    seen_src.add(sn)
                    picks.append(c)
            if len(picks) >= 2:
                facts["states"] = [
                    {"source": ctx.source_name(c), "title": ctx.title(c), "state": _claim_state(c)} for c in picks[:2]
                ]
    elif rule == "UNRESOLVED_DEPENDENCY":
        dep = next((c for c in claims if c.claim_type == "dependency" and _attrs(c).get("depends_on")), None)
        blk = next((c for c in claims if c.claim_type == "blocker"), None)
        if dep is not None:
            a = _attrs(dep)
            facts.update(depends_on=str(a["depends_on"]), from_task=str(a.get("from_task") or dep.task_key or ctx.title(dep)), module=dep.module)
        elif blk is not None:
            facts.update(blocker_text=(blk.text or "")[:140], module=blk.module)
    elif rule == "STALE_ACTIVITY":
        c = claims[0] if claims else None
        if c is not None and c.event_time is not None:
            facts.update(title=ctx.title(c), last_activity=c.event_time.date().isoformat(), module=c.module)
    elif rule == "UNASSIGNED_RESPONSIBILITY":
        c = next((x for x in claims if x.claim_type == "task_status" and not x.owner_name), None)
        if c is not None:
            facts.update(title=ctx.title(c), module=c.module)
    elif rule == "UNDOCUMENTED_WORK":
        facts["activity_count"] = len([c for c in claims if c.claim_type == "contribution"])
    elif rule == "MISSING_TEST_EVIDENCE":
        pend = next((c for c in claims if c.claim_type == "testing" and _attrs(c).get("testing_status") == "pending"), None)
        if pend is not None:
            facts["pending"] = True

    fp = _fp("contradiction", rule, ",".join(sorted(_claim_fp(c) for c in claims)) or (ctr.fingerprint or ctr.id))
    tid, tlabel = ctx.target(claims, departing_first=True)
    clearance = max_clearance([c.clearance_level for c in claims] + [ctr.clearance_level or "team"])
    return Gap(
        gap_type=rule.lower(),
        module=module,
        priority=ctr.severity if ctr.severity in ("high", "medium", "low") else "medium",
        fingerprint=fp,
        facts=facts,
        claim_id=claims[0].id if claims else None,
        contradiction_id=ctr.id,
        claim_ids=[c.id for c in claims],
        clearance=clearance,
        target_person_id=tid,
        target_label=tlabel,
    )


def _claim_gap(ctx: _Ctx, c: Claim) -> Optional[Gap]:
    a = _attrs(c)
    src = ctx.source_name(c)
    base = {"title": ctx.title(c), "module": c.module, "source": src, "text": (c.text or "")[:160]}
    gap_type: Optional[str] = None
    priority = "medium"

    if c.verification_status == "conflicting":
        gap_type, priority = "conflicting_claim", "high"
    elif c.claim_type == "task_status" and not c.owner_name:
        gap_type = "unassigned_task"
    elif c.claim_type == "testing" and a.get("testing_status") == "pending":
        gap_type = "pending_test"
    elif c.claim_type == "decision" and not any(w in (c.text or "").lower() for w in RATIONALE_WORDS):
        gap_type = "decision_rationale"
    elif c.claim_type == "blocker" and not a.get("resolved"):
        gap_type = "blocker_open"
    elif c.claim_type == "dependency":
        gap_type = "dependency_open"
    elif c.claim_type == "doc_gap":
        return None  # handled by the module documentation gap
    elif c.verification_status == "missing":
        gap_type = "missing_claim"
    elif c.verification_status == "inferred" and c.claim_type in ("task_status", "decision", "ownership"):
        gap_type, priority = "inferred_claim", "low"

    if gap_type is None:
        return None
    tid, tlabel = ctx.target([c], departing_first=False)
    return Gap(
        gap_type=gap_type,
        module=c.module,
        priority=priority,
        fingerprint=_fp("claim", gap_type, _claim_fp(c)),
        facts=base,
        claim_id=c.id,
        claim_ids=[c.id],
        clearance=c.clearance_level,
        target_person_id=tid,
        target_label=tlabel,
    )


def _module_doc_gaps(ctx: _Ctx) -> List[Gap]:
    by_mod: Dict[str, List[Claim]] = {}
    for c in ctx.claims:
        if c.module not in GENERIC_MODULES and c.review_status != "rejected":
            by_mod.setdefault(c.module, []).append(c)
    gaps: List[Gap] = []
    for mod, claims in sorted(by_mod.items()):
        documented = any(c.claim_type == "decision" or ctx.has_doc_evidence(c) for c in claims)
        if documented:
            continue
        gap_claim = next((c for c in claims if c.claim_type == "doc_gap"), None)
        tid, tlabel = ctx.target(claims, departing_first=False)
        gaps.append(
            Gap(
                gap_type="module_doc",
                module=mod,
                priority="medium",
                fingerprint=_fp("module_doc", mod),
                facts={"module": mod},
                claim_id=gap_claim.id if gap_claim else None,
                claim_ids=[gap_claim.id] if gap_claim else [],
                clearance=max_clearance([c.clearance_level for c in claims]),
                target_person_id=tid,
                target_label=tlabel,
            )
        )
    return gaps


def identify_gaps(db: Session, project: Project) -> List[Gap]:
    ctx = _Ctx(db, project)
    gaps: List[Gap] = []
    covered: set = set()

    for ctr in ctx.open_ctrs:
        g = _contradiction_gap(ctx, ctr)
        gaps.append(g)
        covered.update(g.claim_ids)

    for c in sorted(ctx.claims, key=lambda x: x.id):
        if c.id in covered or c.review_status in ("approved", "rejected") or c.extractor == "human":
            continue
        g = _claim_gap(ctx, c)
        if g:
            gaps.append(g)

    gaps.extend(_module_doc_gaps(ctx))

    # De-duplicate by fingerprint (two claims can share a fingerprint across re-runs)
    seen: set = set()
    unique: List[Gap] = []
    for g in gaps:
        if g.fingerprint in seen:
            continue
        seen.add(g.fingerprint)
        unique.append(g)
    return unique
