"""Rule 6: UNDOCUMENTED_WORK.

Fires when a module has substantial commits/chat activity (>= 2 contribution/activity claims)
but no documentation source or recorded decision claim.
"""

from typing import Dict, List

from app.engine.rules.base import RuleClaim, RuleFinding, unique_ordered
from app.engine.types import DOC_SOURCE_TYPES, GENERIC_MODULES, SourceInfo

RULE_CODE = "UNDOCUMENTED_WORK"
REASON_TEMPLATE = (
    "Module '{module}' has {count} implementation/activity record(s) in commits or chat, "
    "but no architecture documentation or recorded design decision."
)
ACTION_TEMPLATE = (
    "Add architecture notes or record key design decisions for '{module}' before handover."
)


def evaluate(
    claims: List[RuleClaim],
    sources: Dict[str, SourceInfo],
    stale_days: int = 28,
) -> List[RuleFinding]:
    by_mod: Dict[str, List[RuleClaim]] = {}
    for c in claims:
        if c.module not in GENERIC_MODULES:
            by_mod.setdefault(c.module, []).append(c)

    findings: List[RuleFinding] = []
    for mod, mclaims in sorted(by_mod.items()):
        has_docs_or_decisions = False
        activity: List[RuleClaim] = []
        gap_claims: List[RuleClaim] = []

        for c in mclaims:
            if c.claim_type == "doc_gap":
                gap_claims.append(c)
                continue
            if c.claim_type == "decision":
                has_docs_or_decisions = True
            if c.source_types & DOC_SOURCE_TYPES:
                has_docs_or_decisions = True
            if c.claim_type == "contribution" or ("chat_json" in c.source_types):
                activity.append(c)

        if len(activity) >= 2 and not has_docs_or_decisions:
            involved = activity + gap_claims
            involved_ids = unique_ordered(c.id for c in involved)
            src_ids = unique_ordered(s for c in involved for s in c.source_ids)
            sev = "high" if len(activity) >= 5 else "medium"
            findings.append(
                RuleFinding(
                    rule_code=RULE_CODE,
                    severity=sev,
                    reason=REASON_TEMPLATE.format(module=mod, count=len(activity)),
                    suggested_action=ACTION_TEMPLATE.format(module=mod),
                    claim_ids=involved_ids,
                    source_ids=src_ids,
                    mark_conflicting_claim_ids=[],
                    key=f"undoc:{mod}",
                )
            )

    return findings
