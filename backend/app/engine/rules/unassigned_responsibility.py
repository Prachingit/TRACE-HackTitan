"""Rule 7: UNASSIGNED_RESPONSIBILITY.

Fires when a task or module has no assigned owner.
"""

from typing import Dict, List

from app.engine.rules.base import RuleClaim, RuleFinding, unique_ordered
from app.engine.types import GENERIC_MODULES, SourceInfo

RULE_CODE = "UNASSIGNED_RESPONSIBILITY"
REASON_TEMPLATE = (
    "Unassigned responsibility in module '{module}': {detail}"
)
ACTION_TEMPLATE = (
    "Assign a clear owner for '{target}' in module '{module}' before handover sign-off."
)


def evaluate(
    claims: List[RuleClaim],
    sources: Dict[str, SourceInfo],
    stale_days: int = 28,
) -> List[RuleFinding]:
    findings: List[RuleFinding] = []
    seen_keys = set()

    # 1. Task with no owner
    for c in claims:
        if c.claim_type == "task_status" and (not c.owner or c.attrs.get("unassigned")):
            tkey = c.task_key or c.id
            fk = f"unassigned-task:{c.module}:{tkey}"
            if fk in seen_keys:
                continue
            seen_keys.add(fk)
            findings.append(
                RuleFinding(
                    rule_code=RULE_CODE,
                    severity="medium",
                    reason=REASON_TEMPLATE.format(
                        module=c.module,
                        detail=f"Task '{c.title}' has no assigned owner.",
                    ),
                    suggested_action=ACTION_TEMPLATE.format(target=c.title, module=c.module),
                    claim_ids=[c.id],
                    source_ids=unique_ordered(c.source_ids),
                    mark_conflicting_claim_ids=[],
                    key=fk,
                )
            )

    # 2. Module with claims/work but zero owners across all claims in that module
    by_mod: Dict[str, List[RuleClaim]] = {}
    for c in claims:
        if c.module not in GENERIC_MODULES:
            by_mod.setdefault(c.module, []).append(c)

    for mod, mclaims in sorted(by_mod.items()):
        owners = [c.owner for c in mclaims if c.owner]
        if not owners and mclaims:
            fk = f"unassigned-mod:{mod}"
            if fk not in seen_keys:
                seen_keys.add(fk)
                involved_ids = unique_ordered(c.id for c in mclaims)
                src_ids = unique_ordered(s for c in mclaims for s in c.source_ids)
                findings.append(
                    RuleFinding(
                        rule_code=RULE_CODE,
                        severity="medium",
                        reason=REASON_TEMPLATE.format(
                            module=mod,
                            detail=f"Module '{mod}' has {len(mclaims)} claim(s) but no assigned owner.",
                        ),
                        suggested_action=ACTION_TEMPLATE.format(target=mod, module=mod),
                        claim_ids=involved_ids,
                        source_ids=src_ids,
                        mark_conflicting_claim_ids=[],
                        key=fk,
                    )
                )

    return findings
