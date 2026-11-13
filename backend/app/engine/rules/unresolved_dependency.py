"""Rule 4: UNRESOLVED_DEPENDENCY.

Fires when:
1. A task depends on another task that is not 'completed' or does not exist; OR
2. A blocker claim has no resolution claim in the same module/thread.
"""

from typing import Dict, List

from app.engine.rules.base import RuleClaim, RuleFinding, unique_ordered
from app.engine.types import SourceInfo

RULE_CODE = "UNRESOLVED_DEPENDENCY"
REASON_TEMPLATE = (
    "Unresolved dependency or blocker in module '{module}': {detail}"
)
ACTION_TEMPLATE = (
    "Resolve or unblock the prerequisite before proceeding with dependent work in '{module}'."
)


def evaluate(
    claims: List[RuleClaim],
    sources: Dict[str, SourceInfo],
    stale_days: int = 28,
) -> List[RuleFinding]:
    findings: List[RuleFinding] = []

    # Map known task IDs / task_keys to their RuleClaim
    tasks_by_id: Dict[str, RuleClaim] = {}
    for c in claims:
        if c.claim_type == "task_status":
            tid = str(c.attrs.get("task_id") or "").upper()
            if tid:
                tasks_by_id[tid] = c
            if c.task_key:
                tasks_by_id[c.task_key.upper()] = c

    # 1. Explicit task dependency where target is missing or not completed
    for c in claims:
        if c.claim_type != "dependency":
            continue
        dep_target = str(c.attrs.get("depends_on") or "").upper()
        from_task = str(c.attrs.get("from_task") or c.task_key or c.title)
        if dep_target:
            target_claim = tasks_by_id.get(dep_target)
            if target_claim is None:
                findings.append(
                    RuleFinding(
                        rule_code=RULE_CODE,
                        severity="high",
                        reason=REASON_TEMPLATE.format(
                            module=c.module,
                            detail=f"Task '{from_task}' depends on '{dep_target}', which does not exist in tracked tasks.",
                        ),
                        suggested_action=ACTION_TEMPLATE.format(module=c.module),
                        claim_ids=[c.id],
                        source_ids=unique_ordered(c.source_ids),
                        mark_conflicting_claim_ids=[c.id],
                        key=f"dep-missing:{from_task}->{dep_target}",
                    )
                )
            else:
                target_status = target_claim.attrs.get("status", "unknown")
                from_claim = tasks_by_id.get(from_task.upper())
                from_status = from_claim.attrs.get("status") if from_claim else None
                if target_status != "completed":
                    sev = "high" if from_status in ("completed", "in_progress") else "medium"
                    involved = unique_ordered([c.id, target_claim.id] + ([from_claim.id] if from_claim else []))
                    srcs = unique_ordered(c.source_ids + target_claim.source_ids)
                    findings.append(
                        RuleFinding(
                            rule_code=RULE_CODE,
                            severity=sev,
                            reason=REASON_TEMPLATE.format(
                                module=c.module,
                                detail=(
                                    f"Task '{from_task}' ({from_status or 'dependent'}) depends on "
                                    f"'{dep_target}' which is currently '{target_status}'."
                                ),
                            ),
                            suggested_action=ACTION_TEMPLATE.format(module=c.module),
                            claim_ids=involved,
                            source_ids=srcs,
                            mark_conflicting_claim_ids=involved if from_status == "completed" else [c.id],
                            key=f"dep-incomplete:{from_task}->{dep_target}",
                        )
                    )

    # 2. Unresolved blocker claims
    for c in claims:
        if c.claim_type == "blocker" and not c.attrs.get("resolved"):
            findings.append(
                RuleFinding(
                    rule_code=RULE_CODE,
                    severity="high",
                    reason=REASON_TEMPLATE.format(
                        module=c.module,
                        detail=f"Active blocker recorded with no resolution: {c.text[:140]}",
                    ),
                    suggested_action=ACTION_TEMPLATE.format(module=c.module),
                    claim_ids=[c.id],
                    source_ids=unique_ordered(c.source_ids),
                    mark_conflicting_claim_ids=[],
                    key=f"blocker:{c.module}:{c.id}",
                )
            )

    return findings
