"""Shared data structures for deterministic Contradiction Radar rules (Phase 5).

Rules receive only normalised RuleClaim and SourceInfo objects — nothing hardcoded to any dataset.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from app.engine.types import SourceInfo


@dataclass
class RuleClaim:
    id: str
    claim_type: str
    title: str
    text: str
    module: str
    owner: Optional[str]
    verification_status: str
    review_status: str
    clearance_level: str
    event_time: Optional[datetime]
    task_key: Optional[str]
    attrs: Dict[str, Any] = field(default_factory=dict)
    source_ids: List[str] = field(default_factory=list)
    source_types: Set[str] = field(default_factory=set)


@dataclass
class RuleFinding:
    rule_code: str
    severity: str  # low | medium | high
    reason: str
    suggested_action: str
    claim_ids: List[str]
    source_ids: List[str]
    mark_conflicting_claim_ids: List[str] = field(default_factory=list)
    key: str = ""  # stable key within rule_code for fingerprint deduplication


def unique_ordered(seq) -> List[str]:
    seen = set()
    out = []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out
