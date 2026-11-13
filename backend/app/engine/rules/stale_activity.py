"""Rule 5: STALE_ACTIVITY.

Fires when an in-progress item has no related activity for N days (N configurable per project,
default 28), measured against the most recent event timestamp in the project (or UTC now if
only a single dated item exists).
"""

from datetime import datetime, timezone
from typing import Dict, List

from app.engine.rules.base import RuleClaim, RuleFinding, unique_ordered
from app.engine.types import SourceInfo, ensure_utc

RULE_CODE = "STALE_ACTIVITY"
REASON_TEMPLATE = (
    "In-progress item '{task_title}' in module '{module}' has had no recorded activity for "
    "{days} days (threshold: {stale_days} days; last update: {last_date})."
)
ACTION_TEMPLATE = (
    "Confirm whether '{task_title}' is still actively being worked on, blocked, or abandoned."
)


def evaluate(
    claims: List[RuleClaim],
    sources: Dict[str, SourceInfo],
    stale_days: int = 28,
) -> List[RuleFinding]:
    all_times = [ensure_utc(c.event_time) for c in claims if c.event_time is not None]
    all_times = [t for t in all_times if t is not None]
    reference_time = max(all_times) if len(all_times) >= 2 else datetime.now(timezone.utc)

    # Track latest activity per task_key
    latest_by_task: Dict[str, datetime] = {}
    for c in claims:
        t = ensure_utc(c.event_time)
        if t and c.task_key:
            prev = latest_by_task.get(c.task_key)
            if prev is None or t > prev:
                latest_by_task[c.task_key] = t

    findings: List[RuleFinding] = []
    for c in claims:
        if c.claim_type != "task_status":
            continue
        if c.attrs.get("status") != "in_progress":
            continue
        last_t = latest_by_task.get(c.task_key or "") or ensure_utc(c.event_time)
        if last_t is None:
            continue

        delta_days = (reference_time - last_t).days
        if delta_days >= stale_days:
            sev = "high" if delta_days >= stale_days * 2 else "medium"
            findings.append(
                RuleFinding(
                    rule_code=RULE_CODE,
                    severity=sev,
                    reason=REASON_TEMPLATE.format(
                        task_title=c.title,
                        module=c.module,
                        days=delta_days,
                        stale_days=stale_days,
                        last_date=last_t.date().isoformat(),
                    ),
                    suggested_action=ACTION_TEMPLATE.format(task_title=c.title),
                    claim_ids=[c.id],
                    source_ids=unique_ordered(c.source_ids),
                    mark_conflicting_claim_ids=[],
                    key=f"stale:{c.task_key or c.id}",
                )
            )

    return findings
