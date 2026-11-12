"""Plain data types and helpers shared by every engine module (no DB access here)."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

CLEARANCE_ORDER = {"public": 0, "team": 1, "restricted": 2}
HIDDEN_ROLES = ("incoming", "departing")  # roles that never see restricted material
GENERIC_MODULES = {"general", ""}
DOC_SOURCE_TYPES = {"markdown", "txt", "pdf", "docx", "manual"}

CLAIM_TYPES = (
    "task_status", "decision", "ownership", "blocker",
    "dependency", "contribution", "testing", "doc_gap",
)
TASK_STATUSES = ("completed", "in_progress", "pending", "blocked", "unknown")


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes; treat them as UTC so comparisons never mix naive and aware."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def max_clearance(levels) -> str:
    best = "public"
    for lv in levels:
        if CLEARANCE_ORDER.get(lv, 2) > CLEARANCE_ORDER[best]:
            best = lv if lv in CLEARANCE_ORDER else "restricted"
    return best


def norm_ws(s: str) -> str:
    return " ".join((s or "").split())


def slug(s: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def module_name(s: Optional[str]) -> Optional[str]:
    """Canonical module name: lower-case words joined with hyphens."""
    out = slug(s)
    return out or None


_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with", "is", "are", "was", "be",
    "this", "that", "it", "as", "at", "by", "from", "will", "has", "have", "not", "all", "new", "add",
    "feat", "fix", "chore", "docs", "task", "tasks",
}


def tokens(s: str) -> set:
    """Significant lower-case tokens, with trailing plural 's' stripped, for fuzzy matching."""
    out = set()
    for t in re.findall(r"[a-z0-9]+", (s or "").lower()):
        if len(t) < 3 or t in _STOP:
            continue
        out.add(t[:-1] if t.endswith("s") and len(t) > 3 else t)
    return out


@dataclass
class SourceInfo:
    id: str
    filename: str
    type: str
    clearance: str


@dataclass
class NChunk:
    id: str
    source_id: str
    source_type: str
    filename: str
    clearance: str
    text: str
    author: Optional[str]
    timestamp: Optional[datetime]  # aware UTC, may be inherited (see ts_inferred)
    locator: Optional[str]
    ordinal: int
    ts_inferred: bool = False


@dataclass
class RawEvidence:
    chunk_id: str
    excerpt: str


@dataclass
class RawClaim:
    type: str
    title: str
    text: str
    evidence: List[RawEvidence]
    module: Optional[str] = None
    owner: Optional[str] = None
    verification: str = "inferred"
    confidence: Optional[float] = None
    extractor: str = "rule"  # rule | llm
    author: Optional[str] = None
    event_time: Optional[datetime] = None
    task_key: Optional[str] = None
    attrs: Dict[str, Any] = field(default_factory=dict)
