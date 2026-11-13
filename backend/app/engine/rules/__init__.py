"""Contradiction Radar rule registry and runner (Phase 5)."""

import hashlib
import json
import secrets
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.engine.rules import (
    conflicting_ownership,
    conflicting_status,
    missing_test_evidence,
    stale_activity,
    status_without_evidence,
    unassigned_responsibility,
    undocumented_work,
    unresolved_dependency,
)
from app.engine.rules.base import RuleClaim, RuleFinding, unique_ordered
from app.engine.types import SourceInfo, max_clearance
from app.models import (
    Claim,
    ClaimEvidence,
    Contradiction,
    ContradictionClaim,
    Project,
    Source,
)

ALL_RULES = [
    status_without_evidence,
    conflicting_status,
    conflicting_ownership,
    unresolved_dependency,
    stale_activity,
    undocumented_work,
    unassigned_responsibility,
    missing_test_evidence,
]


def evaluate_all_rules(
    claims: List[RuleClaim],
    sources: Dict[str, SourceInfo],
    stale_days: int = 28,
) -> List[RuleFinding]:
    """Run all 8 deterministic Contradiction Radar rules over in-memory claims and sources."""
    out: List[RuleFinding] = []
    for rule_mod in ALL_RULES:
        out.extend(rule_mod.evaluate(claims, sources, stale_days=stale_days))
    return out


def _new_contradiction_id() -> str:
    return f"CTR-{secrets.token_hex(4).upper()}"


def _finding_fingerprint(finding: RuleFinding, clearance: str) -> str:
    raw = f"{finding.rule_code}|{finding.key}|{clearance}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _to_rule_claims(db: Session, project_id: str) -> tuple[List[RuleClaim], Dict[str, SourceInfo], Dict[str, Claim]]:
    src_rows = db.query(Source).filter(Source.project_id == project_id).all()
    sources = {s.id: SourceInfo(s.id, s.filename, s.type, s.clearance_level) for s in src_rows}

    claim_rows = db.query(Claim).filter(Claim.project_id == project_id).all()
    claim_by_id = {c.id: c for c in claim_rows}

    rule_claims: List[RuleClaim] = []
    for c in claim_rows:
        attrs = {}
        if c.attrs_json:
            try:
                attrs = json.loads(c.attrs_json)
            except json.JSONDecodeError:
                attrs = {}
        ev_rows = db.query(ClaimEvidence).filter(ClaimEvidence.claim_id == c.id).all()
        sids = unique_ordered(ev.source_id for ev in ev_rows)
        stypes = {sources[sid].type for sid in sids if sid in sources}
        rule_claims.append(
            RuleClaim(
                id=c.id,
                claim_type=c.claim_type,
                title=c.title or c.text[:100],
                text=c.text,
                module=c.module or "general",
                owner=c.owner_name,
                verification_status=c.verification_status,
                review_status=c.review_status,
                clearance_level=c.clearance_level,
                event_time=c.event_time,
                task_key=c.task_key,
                attrs=attrs,
                source_ids=sids,
                source_types=stypes,
            )
        )
    return rule_claims, sources, claim_by_id


def run_contradiction_radar(
    db: Session,
    project_id: str,
    run_id: Optional[str] = None,
) -> int:
    """Run all 8 rules on the project's claims, persist Contradictions, and mark conflicting claims.

    - NEVER auto-resolves an existing open contradiction.
    - Preserves manually resolved contradictions and their resolution notes across re-runs.
    - Marks involved unreviewed claims as 'conflicting' (so no unreviewed conflicting claim shows as Verified).
    """
    project = db.get(Project, project_id)
    stale_days = (project.stale_days if project and project.stale_days else 28)

    all_rule_claims, sources, claim_by_id = _to_rule_claims(db, project_id)
    non_restricted_claims = [c for c in all_rule_claims if c.clearance_level != "restricted"]
    non_restricted_sources = {k: v for k, v in sources.items() if v.clearance != "restricted"}

    # 1. Findings visible to all roles (computed strictly from non-restricted claims/sources)
    base_findings = evaluate_all_rules(non_restricted_claims, non_restricted_sources, stale_days=stale_days)
    # 2. Additional findings when restricted claims/sources are included
    full_findings = evaluate_all_rules(all_rule_claims, sources, stale_days=stale_days)

    existing_by_fp: Dict[str, Contradiction] = {
        c.fingerprint: c
        for c in db.query(Contradiction).filter(Contradiction.project_id == project_id).all()
        if c.fingerprint
    }

    combined: List[tuple[RuleFinding, str]] = []
    seen_base_keys = set()
    for f in base_findings:
        cl = max_clearance(
            claim_by_id[cid].clearance_level for cid in f.claim_ids if cid in claim_by_id
        ) if f.claim_ids else "team"
        seen_base_keys.add((f.rule_code, f.key))
        combined.append((f, cl))

    for f in full_findings:
        if (f.rule_code, f.key) in seen_base_keys:
            continue
        cl = max_clearance(
            claim_by_id[cid].clearance_level for cid in f.claim_ids if cid in claim_by_id
        ) if f.claim_ids else "restricted"
        combined.append((f, cl))

    for finding, cl_level in combined:
        fp = _finding_fingerprint(finding, cl_level)
        existing = existing_by_fp.get(fp)

        if existing is None:
            ctr = Contradiction(
                id=_new_contradiction_id(),
                project_id=project_id,
                rule_code=finding.rule_code,
                severity=finding.severity,
                reason=finding.reason,
                suggested_action=finding.suggested_action,
                status="open",
                conflicting_source_ids=json.dumps(finding.source_ids),
                fingerprint=fp,
                clearance_level=cl_level,
                run_id=run_id,
            )
            db.add(ctr)
            db.flush()
            existing_by_fp[fp] = ctr
            for cid in unique_ordered(finding.claim_ids):
                if cid in claim_by_id:
                    db.add(ContradictionClaim(contradiction_id=ctr.id, claim_id=cid))
        else:
            # Update reason/links for open contradictions; never flip resolved -> open or open -> resolved
            existing.run_id = run_id
            existing.conflicting_source_ids = json.dumps(finding.source_ids)
            db.query(ContradictionClaim).filter(
                ContradictionClaim.contradiction_id == existing.id
            ).delete()
            db.flush()
            for cid in unique_ordered(finding.claim_ids):
                if cid in claim_by_id:
                    db.add(ContradictionClaim(contradiction_id=existing.id, claim_id=cid))

        # Mark involved claims as 'conflicting' when the rule flags them (unless human-approved/edited)
        for cid in finding.mark_conflicting_claim_ids:
            clm = claim_by_id.get(cid)
            if clm and clm.review_status == "unreviewed":
                clm.verification_status = "conflicting"

    db.commit()
    return (
        db.query(Contradiction)
        .filter(Contradiction.project_id == project_id, Contradiction.status == "open")
        .count()
    )
