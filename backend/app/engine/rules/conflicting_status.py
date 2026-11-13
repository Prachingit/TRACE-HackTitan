"""Rule 2: CONFLICTING_STATUS.

Fires when sources give conflicting statuses for the same task or module (e.g. CSV 'Done' vs
notes/PR 'testing pending' / 'in_progress' / 'blocked'), or conflicting technical choices
for the same architectural topic.
"""

from typing import Dict, List

from app.engine.rules.base import RuleClaim, RuleFinding, unique_ordered
from app.engine.types import SourceInfo

RULE_CODE = "CONFLICTING_STATUS"
REASON_TEMPLATE = (
    "Conflicting status or state in module '{module}': {summary}."
)
ACTION_TEMPLATE = (
    "Reconcile the conflicting sources ({sources}) for '{module}' and confirm the true current state."
)


def evaluate(
    claims: List[RuleClaim],
    sources: Dict[str, SourceInfo],
    stale_days: int = 28,
) -> List[RuleFinding]:
    findings: List[RuleFinding] = []
    seen_keys = set()

    # 1. Task/module status conflict: a task in a module is marked 'completed', while another
    # source in the same task_key or module states testing/validation is pending, blocked, or open PR
    by_module: Dict[str, List[RuleClaim]] = {}
    by_task: Dict[str, List[RuleClaim]] = {}
    for c in claims:
        by_module.setdefault(c.module, []).append(c)
        if c.task_key:
            by_task.setdefault(c.task_key, []).append(c)

    # Check same task_key with distinct normalized statuses across sources
    for tkey, tclaims in by_task.items():
        task_claims = [c for c in tclaims if c.claim_type == "task_status" and c.attrs.get("status") not in (None, "unknown")]
        statuses = {c.attrs.get("status") for c in task_claims}
        if len(statuses) >= 2:
            involved_ids = [c.id for c in task_claims]
            src_ids = unique_ordered(s for c in task_claims for s in c.source_ids)
            fk = f"task:{tkey}"
            seen_keys.add(fk)
            mod = task_claims[0].module
            desc = " vs ".join(f"'{c.title}' ({c.attrs.get('status')})" for c in task_claims[:3])
            findings.append(
                RuleFinding(
                    rule_code=RULE_CODE,
                    severity="high",
                    reason=REASON_TEMPLATE.format(module=mod, summary=desc),
                    suggested_action=ACTION_TEMPLATE.format(
                        sources=", ".join(src_ids) or "multiple sources", module=mod
                    ),
                    claim_ids=involved_ids,
                    source_ids=src_ids,
                    mark_conflicting_claim_ids=involved_ids,
                    key=fk,
                )
            )

    # Check module-level conflict: completed task(s) vs explicit pending testing / blocker / open PR in another source
    for mod, mclaims in by_module.items():
        completed = [
            c for c in mclaims
            if c.claim_type == "task_status" and c.attrs.get("status") == "completed"
        ]
        contradicting = [
            c for c in mclaims
            if (
                (c.claim_type == "testing" and c.attrs.get("testing_status") == "pending")
                or (c.claim_type == "task_status" and (c.attrs.get("testing_pending") or c.attrs.get("from_open_pr")))
                or c.claim_type == "blocker"
            )
        ]
        if completed and contradicting:
            comp_srcs = {s for c in completed for s in c.source_ids}
            cont_srcs = {s for c in contradicting for s in c.source_ids}
            if len(comp_srcs | cont_srcs) >= 2 or comp_srcs != cont_srcs:
                fk = f"mod-status:{mod}"
                if fk not in seen_keys:
                    seen_keys.add(fk)
                    involved = completed + contradicting
                    involved_ids = unique_ordered(c.id for c in involved)
                    src_ids = unique_ordered(s for c in involved for s in c.source_ids)
                    findings.append(
                        RuleFinding(
                            rule_code=RULE_CODE,
                            severity="high",
                            reason=REASON_TEMPLATE.format(
                                module=mod,
                                summary=(
                                    f"'{completed[0].title}' is marked completed, while "
                                    f"'{contradicting[0].title}' states work/testing is still pending or blocked"
                                ),
                            ),
                            suggested_action=ACTION_TEMPLATE.format(
                                sources=", ".join(src_ids) or "sources", module=mod
                            ),
                            claim_ids=involved_ids,
                            source_ids=src_ids,
                            mark_conflicting_claim_ids=involved_ids,
                            key=fk,
                        )
                    )

    # 2. Architectural / technical decision conflict on the same topic (e.g. caching: lru vs redis, db: postgres vs sqlite)
    by_topic: Dict[str, List[RuleClaim]] = {}
    for c in claims:
        topic = c.attrs.get("topic")
        choice = c.attrs.get("choice")
        if topic and choice:
            by_topic.setdefault(topic, []).append(c)

    for topic, tclaims in by_topic.items():
        choices = {c.attrs.get("choice") for c in tclaims}
        if len(choices) >= 2:
            fk = f"topic:{topic}"
            if fk not in seen_keys:
                seen_keys.add(fk)
                involved_ids = unique_ordered(c.id for c in tclaims)
                src_ids = unique_ordered(s for c in tclaims for s in c.source_ids)
                mod = tclaims[0].module
                choices_str = " vs ".join(sorted(str(ch) for ch in choices if ch))
                findings.append(
                    RuleFinding(
                        rule_code=RULE_CODE,
                        severity="medium",
                        reason=REASON_TEMPLATE.format(
                            module=mod,
                            summary=f"sources disagree on {topic} ({choices_str})",
                        ),
                        suggested_action=ACTION_TEMPLATE.format(
                            sources=", ".join(src_ids) or "sources", module=mod
                        ),
                        claim_ids=involved_ids,
                        source_ids=src_ids,
                        mark_conflicting_claim_ids=involved_ids,
                        key=fk,
                    )
                )

    return findings
