"""Rule 8: MISSING_TEST_EVIDENCE.

Fires when implementation exists in a module (contribution claims or completed tasks)
but no positive testing claim exists, or testing is explicitly marked pending.
"""

from typing import Dict, List

from app.engine.rules.base import RuleClaim, RuleFinding, unique_ordered
from app.engine.types import GENERIC_MODULES, SourceInfo

RULE_CODE = "MISSING_TEST_EVIDENCE"
REASON_TEMPLATE = (
    "Missing or pending test coverage in module '{module}': {detail}"
)
ACTION_TEMPLATE = (
    "Add automated tests or complete pending validation for '{module}' before handover approval."
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
        impl_claims = [
            c for c in mclaims
            if c.claim_type == "contribution"
            or (c.claim_type == "task_status" and c.attrs.get("status") in ("completed", "in_progress"))
        ]
        pending_tests = [
            c for c in mclaims
            if c.claim_type == "testing" and c.attrs.get("testing_status") == "pending"
        ]
        present_tests = [
            c for c in mclaims
            if c.claim_type == "testing" and c.attrs.get("testing_status") == "present"
        ]

        if pending_tests:
            involved = unique_ordered([c.id for c in pending_tests + impl_claims[:2]])
            srcs = unique_ordered(s for c in (pending_tests + impl_claims[:2]) for s in c.source_ids)
            findings.append(
                RuleFinding(
                    rule_code=RULE_CODE,
                    severity="high",
                    reason=REASON_TEMPLATE.format(
                        module=mod,
                        detail=f"Testing is explicitly marked pending ({pending_tests[0].text[:120]}).",
                    ),
                    suggested_action=ACTION_TEMPLATE.format(module=mod),
                    claim_ids=involved,
                    source_ids=srcs,
                    mark_conflicting_claim_ids=[],
                    key=f"test-pending:{mod}",
                )
            )
        elif impl_claims and not present_tests:
            involved = unique_ordered(c.id for c in impl_claims[:3])
            srcs = unique_ordered(s for c in impl_claims[:3] for s in c.source_ids)
            findings.append(
                RuleFinding(
                    rule_code=RULE_CODE,
                    severity="low",
                    reason=REASON_TEMPLATE.format(
                        module=mod,
                        detail=f"Module '{mod}' has {len(impl_claims)} implementation record(s) but no recorded test evidence.",
                    ),
                    suggested_action=ACTION_TEMPLATE.format(module=mod),
                    claim_ids=involved,
                    source_ids=srcs,
                    mark_conflicting_claim_ids=[],
                    key=f"test-absent:{mod}",
                )
            )

    return findings
