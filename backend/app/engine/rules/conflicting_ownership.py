"""Rule 3: CONFLICTING_OWNERSHIP.

Fires when two or more sources name different owners for the same module or task.
"""

from typing import Dict, List

from app.engine.rules.base import RuleClaim, RuleFinding, unique_ordered
from app.engine.types import GENERIC_MODULES, SourceInfo

RULE_CODE = "CONFLICTING_OWNERSHIP"
REASON_TEMPLATE = (
    "Conflicting ownership for '{scope}': sources name different owners ({owners})."
)
ACTION_TEMPLATE = (
    "Clarify whether {owners} is the active owner of '{scope}' and update the task board and documentation."
)


def evaluate(
    claims: List[RuleClaim],
    sources: Dict[str, SourceInfo],
    stale_days: int = 28,
) -> List[RuleFinding]:
    findings: List[RuleFinding] = []
    seen_scopes = set()

    # 1. Task-level ownership mismatch (e.g. task T-15 assigned to Person A in CSV, but commits/ownership on T-15 by Person B)
    by_task: Dict[str, List[RuleClaim]] = {}
    for c in claims:
        if c.task_key and c.owner and c.claim_type in ("task_status", "ownership", "contribution"):
            by_task.setdefault(c.task_key, []).append(c)

    for tkey, tclaims in by_task.items():
        # Only compare if at least one explicit ownership/task_status claim is present
        if not any(c.claim_type in ("task_status", "ownership") for c in tclaims):
            continue
        owners_by_norm: Dict[str, str] = {}
        for c in tclaims:
            if c.owner:
                owners_by_norm.setdefault(c.owner.strip().lower(), c.owner.strip())
        if len(owners_by_norm) >= 2:
            src_ids = unique_ordered(s for c in tclaims for s in c.source_ids)
            if len(src_ids) >= 2:
                seen_scopes.add(f"task:{tkey}")
                owners_list = sorted(owners_by_norm.values())
                involved_ids = unique_ordered(c.id for c in tclaims)
                findings.append(
                    RuleFinding(
                        rule_code=RULE_CODE,
                        severity="high",
                        reason=REASON_TEMPLATE.format(scope=tkey, owners=" vs ".join(owners_list)),
                        suggested_action=ACTION_TEMPLATE.format(owners=" or ".join(owners_list), scope=tkey),
                        claim_ids=involved_ids,
                        source_ids=src_ids,
                        mark_conflicting_claim_ids=involved_ids,
                        key=f"task:{tkey}",
                    )
                )

    # 2. Module-level ownership mismatch across explicit ownership / task_status claims
    by_mod: Dict[str, List[RuleClaim]] = {}
    for c in claims:
        if c.module not in GENERIC_MODULES and c.owner and c.claim_type in ("ownership", "task_status"):
            by_mod.setdefault(c.module, []).append(c)

    for mod, mclaims in by_mod.items():
        # Trigger when there is an explicit module-level ownership statement or conflicting task/module owners across sources
        has_explicit_ownership = any(c.claim_type == "ownership" and c.attrs.get("scope") == "module" for c in mclaims)
        owners_by_norm: Dict[str, str] = {}
        sources_by_owner: Dict[str, set] = {}
        for c in mclaims:
            if c.owner:
                k = c.owner.strip().lower()
                owners_by_norm.setdefault(k, c.owner.strip())
                sources_by_owner.setdefault(k, set()).update(c.source_ids)

        if len(owners_by_norm) >= 2:
            all_srcs = unique_ordered(s for c in mclaims for s in c.source_ids)
            # Fire if an explicit module owner conflicts with another owner in a different source,
            # or if all claims for the module are ownership claims from different sources
            only_ownership = [c for c in mclaims if c.claim_type == "ownership"]
            own_names = {c.owner.strip().lower() for c in only_ownership if c.owner}
            if (has_explicit_ownership or len(own_names) >= 2) and len(all_srcs) >= 2:
                owners_list = sorted(owners_by_norm.values())
                involved = only_ownership if len(own_names) >= 2 else mclaims
                involved_ids = unique_ordered(c.id for c in involved)
                src_ids = unique_ordered(s for c in involved for s in c.source_ids)
                findings.append(
                    RuleFinding(
                        rule_code=RULE_CODE,
                        severity="high",
                        reason=REASON_TEMPLATE.format(scope=mod, owners=" vs ".join(owners_list)),
                        suggested_action=ACTION_TEMPLATE.format(owners=" or ".join(owners_list), scope=mod),
                        claim_ids=involved_ids,
                        source_ids=src_ids,
                        mark_conflicting_claim_ids=involved_ids,
                        key=f"module:{mod}",
                    )
                )

    return findings
