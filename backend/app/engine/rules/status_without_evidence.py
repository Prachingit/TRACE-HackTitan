"""Rule 1: STATUS_WITHOUT_EVIDENCE.

Fires when a task is marked 'completed' but no commit, documentation, or chat implementation
claim in the same module or work thread shows implementation.
"""

from typing import Dict, List

from app.engine.rules.base import RuleClaim, RuleFinding, unique_ordered
from app.engine.types import DOC_SOURCE_TYPES, SourceInfo

RULE_CODE = "STATUS_WITHOUT_EVIDENCE"
REASON_TEMPLATE = (
    "Task '{task_title}' in module '{module}' is marked completed, but no commit, "
    "documentation, or implementation evidence exists in '{module}'."
)
ACTION_TEMPLATE = (
    "Verify whether '{task_title}' was actually implemented and merged, or revert its task "
    "status from completed until implementation evidence is linked."
)


def evaluate(
    claims: List[RuleClaim],
    sources: Dict[str, SourceInfo],
    stale_days: int = 28,
) -> List[RuleFinding]:
    # Only evaluate cross-source missing implementation evidence when the project has at least
    # one non-CSV source (e.g. commits, markdown, PDF, DOCX, chat, or manual notes).
    if sources and all(s.type == "csv" for s in sources.values()):
        return []

    # Collect modules and task_keys that have implementation evidence (contributions, decisions, or doc/chat claims)
    implemented_modules = set()
    implemented_threads = set()

    for c in claims:
        if c.claim_type == "contribution":
            implemented_modules.add(c.module)
            if c.task_key:
                implemented_threads.add(c.task_key)

    findings: List[RuleFinding] = []
    for c in claims:
        if c.claim_type != "task_status":
            continue
        status = c.attrs.get("status")
        if status != "completed":
            continue

        has_impl = (c.module in implemented_modules) or (c.task_key and c.task_key in implemented_threads)
        if not has_impl:
            findings.append(
                RuleFinding(
                    rule_code=RULE_CODE,
                    severity="high",
                    reason=REASON_TEMPLATE.format(task_title=c.title, module=c.module),
                    suggested_action=ACTION_TEMPLATE.format(task_title=c.title),
                    claim_ids=[c.id],
                    source_ids=unique_ordered(c.source_ids),
                    mark_conflicting_claim_ids=[c.id],
                    key=f"{c.module}:{c.task_key or c.id}",
                )
            )

    return findings
