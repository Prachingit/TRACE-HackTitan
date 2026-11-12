"""Claim extraction engine: deterministic rules + optional schema-validated LLM extractor."""

import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config import settings
from app.engine.types import (
    CLAIM_TYPES,
    NChunk,
    RawClaim,
    RawEvidence,
    module_name,
    norm_ws,
    slug,
)

# ── Status normalisation synonyms ────────────────────────────────────────────

STATUS_MAP: Dict[str, str] = {
    # completed
    "done": "completed",
    "completed": "completed",
    "complete": "completed",
    "closed": "completed",
    "resolved": "completed",
    "shipped": "completed",
    "merged": "completed",
    "finished": "completed",
    # in_progress
    "in progress": "in_progress",
    "in-progress": "in_progress",
    "in_progress": "in_progress",
    "wip": "in_progress",
    "active": "in_progress",
    "doing": "in_progress",
    "working": "in_progress",
    "ongoing": "in_progress",
    "started": "in_progress",
    "review": "in_progress",
    "in review": "in_progress",
    # pending
    "to do": "pending",
    "todo": "pending",
    "to-do": "pending",
    "pending": "pending",
    "open": "pending",
    "backlog": "pending",
    "planned": "pending",
    "queued": "pending",
    "not started": "pending",
    "new": "pending",
    # blocked
    "blocked": "blocked",
    "on hold": "blocked",
    "stalled": "blocked",
    "waiting": "blocked",
}

NONE_VALUES = {"none", "unassigned", "null", "n/a", "na", "-", "tbd", "nobody", ""}

GENERIC_PATH_PARTS = {
    "backend", "frontend", "app", "src", "lib", "pkg", "internal", "cmd",
    "services", "service", "models", "model", "routers", "router", "routes",
    "controllers", "views", "pages", "components", "styles", "utils", "helpers",
    "common", "core", "shared", "api", "tests", "test", "docs", "doc", "data",
    "scripts", "config", "public", "assets", "static", "main", "index", "init",
}


def normalise_task_status(raw: Optional[str]) -> str:
    if not raw:
        return "unknown"
    cleaned = raw.strip().lower()
    return STATUS_MAP.get(cleaned, "unknown")


def clean_person(val: Optional[str]) -> Optional[str]:
    if not val:
        return None
    v = val.strip()
    if v.lower() in NONE_VALUES:
        return None
    return v


def guess_module_from_text_or_paths(text: str, files: Optional[List[str]] = None) -> Optional[str]:
    """Guess a module name from conventional commit scope, file paths, or explicit mentions."""
    # 1. Conventional commit scope: feat(auth): ..., fix(frontend-dashboard): ...
    m = re.match(r"^(?:\[commit\]\s*)?[a-z]+\(([a-zA-Z0-9_\-]+)\)\s*:", text.strip(), re.I)
    if m:
        scoped = module_name(m.group(1))
        if scoped and scoped not in GENERIC_PATH_PARTS:
            return scoped

    # 2. File paths
    if files:
        for fp in files:
            parts = [p for p in re.split(r"[\\/]", fp.strip()) if p]
            # Look for frontend dashboard patterns
            if parts and parts[0].lower() == "frontend":
                return "frontend-dashboard"
            if parts and parts[0].lower() in ("docs", "doc"):
                return "api-docs"
            for part in parts:
                stem = re.sub(r"\.[a-zA-Z0-9]+$", "", part)
                stem = re.sub(r"^test_", "", stem)
                cand = module_name(stem)
                if cand and cand not in GENERIC_PATH_PARTS and len(cand) >= 3:
                    return cand

    # 3. Explicit "<name> module" or known domain keywords in text
    m_mod = re.search(r"\b([a-z][a-z0-9_\-]{2,24})\s+module\b", text, re.I)
    if m_mod:
        w = module_name(m_mod.group(1))
        if w and w not in {"the", "this", "that", "same", "each", "core", "active", "new"}:
            return w

    lower = text.lower()
    for kw, mod in [
        ("payment", "payments"),
        ("billing", "payments"),
        ("checkout", "payments"),
        ("jwt", "auth"),
        ("authentication", "auth"),
        ("password", "auth"),
        ("bcrypt", "auth"),
        ("login", "auth"),
        ("notification", "notifications"),
        ("smtp", "notifications"),
        ("webhook retry", "notifications"),
        ("openapi", "api-docs"),
        ("swagger", "api-docs"),
        ("curl example", "api-docs"),
        ("sidebar", "frontend-dashboard"),
        ("design token", "frontend-dashboard"),
        ("stat card", "frontend-dashboard"),
        ("role switcher", "frontend-dashboard"),
        ("sqlite", "database"),
        ("PostgreSQL".lower(), "database"),
        ("database", "database"),
        ("connection pool", "database"),
        ("repository pattern", "database"),
    ]:
        if kw in lower:
            return mod

    return None


def exact_excerpt_in_chunk(chunk_text: str, candidate: str) -> Optional[str]:
    """Verify candidate appears in chunk_text (allowing whitespace normalization) and return exact slice."""
    if not candidate or not chunk_text:
        return None
    cand_stripped = candidate.strip()
    if not cand_stripped:
        return None
    if cand_stripped in chunk_text:
        return cand_stripped

    # Build a regex that matches the tokens of candidate separated by any whitespace
    words = cand_stripped.split()
    if not words:
        return None
    pattern = r"\s+".join(re.escape(w) for w in words)
    m = re.search(pattern, chunk_text, flags=re.I)
    if m:
        return chunk_text[m.start():m.end()]
    return None


# ── Deterministic Extractors ─────────────────────────────────────────────────

def _extract_from_csv_chunk(chunk: NChunk) -> List[RawClaim]:
    """Parse a CSV row chunk into task_status, ownership, and dependency claims."""
    kv: Dict[str, str] = {}
    for part in chunk.text.split(" | "):
        if ":" in part:
            k, v = part.split(":", 1)
            kv[k.strip().lower()] = v.strip()

    if not kv:
        return []

    task_id = (
        kv.get("id")
        or kv.get("task_id")
        or kv.get("key")
        or kv.get("ticket")
        or kv.get("issue")
    )
    title = (
        kv.get("title")
        or kv.get("task")
        or kv.get("summary")
        or kv.get("name")
        or kv.get("item")
        or chunk.text[:100]
    )
    raw_owner = (
        kv.get("assignee")
        or kv.get("owner")
        or kv.get("assigned_to")
        or kv.get("responsible")
        or chunk.author
    )
    owner = clean_person(raw_owner)
    raw_status = kv.get("status") or kv.get("state") or kv.get("stage")
    norm_status = normalise_task_status(raw_status)
    raw_mod = kv.get("module") or kv.get("component") or kv.get("area") or kv.get("service")
    mod = module_name(raw_mod) or guess_module_from_text_or_paths(title) or "general"
    raw_deps = (
        kv.get("depends_on")
        or kv.get("dependency")
        or kv.get("dependencies")
        or kv.get("blocked_by")
        or kv.get("requires")
        or ""
    )
    deps = [d.strip() for d in re.split(r"[,;]+", raw_deps) if d.strip() and d.strip().lower() not in NONE_VALUES]

    t_key = (task_id or slug(title)).upper() if task_id else slug(title)
    verification = "verified" if norm_status != "unknown" else "missing"

    claims: List[RawClaim] = []
    label = f"{task_id}: {title}" if task_id else title
    status_display = raw_status if raw_status else "unknown"
    owner_display = owner if owner else "unassigned"

    claims.append(
        RawClaim(
            type="task_status",
            title=label,
            text=f"Task {label} is marked '{status_display}' (normalized: {norm_status}), assigned to {owner_display}.",
            evidence=[RawEvidence(chunk_id=chunk.id, excerpt=chunk.text)],
            module=mod,
            owner=owner,
            verification=verification,
            extractor="rule",
            author=owner or chunk.author,
            event_time=chunk.timestamp,
            task_key=t_key,
            attrs={
                "status": norm_status,
                "raw_status": raw_status or "",
                "task_id": task_id,
                "task_title": title,
                "depends_on": deps,
                "unassigned": owner is None,
            },
        )
    )

    if owner:
        claims.append(
            RawClaim(
                type="ownership",
                title=f"Owner of {mod} ({label}): {owner}",
                text=f"{owner} is assigned as owner of {label} in module {mod}.",
                evidence=[RawEvidence(chunk_id=chunk.id, excerpt=chunk.text)],
                module=mod,
                owner=owner,
                verification="verified",
                extractor="rule",
                author=owner,
                event_time=chunk.timestamp,
                task_key=t_key,
                attrs={"scope": "task", "task_id": task_id, "module": mod},
            )
        )

    for dep in deps:
        claims.append(
            RawClaim(
                type="dependency",
                title=f"{label} depends on {dep}",
                text=f"Task {label} depends on {dep}.",
                evidence=[RawEvidence(chunk_id=chunk.id, excerpt=chunk.text)],
                module=mod,
                owner=owner,
                verification="verified",
                extractor="rule",
                author=owner or chunk.author,
                event_time=chunk.timestamp,
                task_key=t_key,
                attrs={"from_task": t_key, "from_title": title, "depends_on": dep.upper()},
            )
        )

    return claims


def _extract_from_commit_chunk(chunk: NChunk) -> List[RawClaim]:
    """Extract contribution (and test presence) claims from commit/PR/issue chunks.

    NEVER marks a task or feature as completed from a commit alone.
    """
    lines = chunk.text.splitlines()
    msg_line = lines[0].strip() if lines else chunk.text.strip()
    files: List[str] = []
    for ln in lines[1:]:
        if ln.startswith("Files:"):
            files = [f.strip() for f in ln.replace("Files:", "", 1).split(",") if f.strip()]

    mod = guess_module_from_text_or_paths(msg_line, files) or "general"
    clean_msg = re.sub(r"^\[commit\]\s*", "", msg_line).strip()
    sha = (chunk.locator or "").replace("sha:", "")

    # Check if PR is open/blocked
    if (chunk.locator or "").startswith("pr:"):
        pr_Match = re.match(r"^\[PR #(\d+)\]\s*(.+?)\s*\((open|closed)(?:,\s*merged)?\)", msg_line, re.I)
        state = pr_Match.group(3).lower() if pr_Match else "open"
        merged = "merged" in msg_line.lower()
        claims = [
            RawClaim(
                type="contribution",
                title=f"PR by {chunk.author or 'contributor'}: {clean_msg[:90]}",
                text=f"Pull request in {mod}: {clean_msg}",
                evidence=[RawEvidence(chunk_id=chunk.id, excerpt=msg_line)],
                module=mod,
                owner=clean_person(chunk.author),
                verification="verified",
                extractor="rule",
                author=chunk.author,
                event_time=chunk.timestamp,
                attrs={"kind": "pr", "state": "merged" if merged else state, "locator": chunk.locator},
            )
        ]
        if state == "open" and not merged:
            claims.append(
                RawClaim(
                    type="task_status",
                    title=f"Open PR in {mod}: {clean_msg[:80]}",
                    text=f"Pull request remains open/unmerged: {clean_msg}",
                    evidence=[RawEvidence(chunk_id=chunk.id, excerpt=msg_line)],
                    module=mod,
                    owner=clean_person(chunk.author),
                    verification="inferred",
                    extractor="rule",
                    author=chunk.author,
                    event_time=chunk.timestamp,
                    attrs={"status": "in_progress", "from_open_pr": True},
                )
            )
        return claims

    claims = [
        RawClaim(
            type="contribution",
            title=f"Commit {sha[:7]} by {chunk.author or 'contributor'}",
            text=f"{chunk.author or 'Contributor'} committed in {mod}: {clean_msg}",
            evidence=[RawEvidence(chunk_id=chunk.id, excerpt=msg_line)],
            module=mod,
            owner=clean_person(chunk.author),
            verification="verified",
            extractor="rule",
            author=chunk.author,
            event_time=chunk.timestamp,
            attrs={"kind": "commit", "sha": sha, "files": files},
        )
    ]

    # Detect explicit test commits
    is_test = bool(
        re.match(r"^test\b", clean_msg, re.I)
        or any("test" in f.lower() for f in files)
        or re.search(r"\b(unit tests?|test suite)\b", clean_msg, re.I)
    )
    if is_test:
        claims.append(
            RawClaim(
                type="testing",
                title=f"Tests committed for {mod}",
                text=f"Test commit by {chunk.author or 'contributor'} in {mod}: {clean_msg}",
                evidence=[RawEvidence(chunk_id=chunk.id, excerpt=msg_line)],
                module=mod,
                owner=clean_person(chunk.author),
                verification="verified",
                extractor="rule",
                author=chunk.author,
                event_time=chunk.timestamp,
                attrs={"testing_status": "present", "sha": sha},
            )
        )

    return claims


_DECISION_PATTERNS = [
    re.compile(r"\b(?:decided|decision recorded|agreed to|agreed that|we will use|switched from)\b", re.I),
    re.compile(r"\b(?:active strategy|using sqlite|using postgresql|switched .* to (?:redis|sqlite|postgres))\b", re.I),
    re.compile(r"\b(?:will implement .* using)\b", re.I),
]

_BLOCKER_PATTERNS = [
    re.compile(r"\b(?:blocked by|blocked on|waiting on|waiting for|cannot be approved until|do not mark [a-z0-9_\- ]+ complete)\b", re.I),
]

_TESTING_PENDING_PATTERNS = [
    re.compile(r"\b(?:testing remains[a-z ]*pending|testing is pending|testing pending|security review is still pending|outstanding test coverage|pending security validation|payment testing is dependent on|untested)\b", re.I),
]

_TESTING_PRESENT_PATTERNS = [
    re.compile(r"\b(?:added unit tests|added tests for|logic tested)\b", re.I),
]

_DEPENDENCY_PATTERNS = [
    re.compile(r"\b(?:depends on|is dependent on|dependent on|before we wire up)\b", re.I),
]

_OWNERSHIP_PATTERNS = [
    # "Ankit Rao is the designated owner for the payments integration stream"
    re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+is\s+the\s+(?:designated\s+)?owner\s+(?:for|of)\s+(?:the\s+)?([a-zA-Z0-9_\- ]+)", re.I),
    # "Ankit will take ownership of the payments module" / "Ankit is taking over the payments integration"
    re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:will\s+take\s+ownership\s+of|is\s+taking\s+over|will\s+handle|owns)\s+(?:the\s+)?([a-zA-Z0-9_\- ]+)", re.I),
    # "designated owner in meeting notes: Ankit Rao" / "owner: Ankit Rao" / "assigned to Ankit Rao"
    re.compile(r"(?:designated\s+owner[^:]*:|owner\s*:|assigned\s+to)\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)"),
]

_UNASSIGNED_PATTERN = re.compile(
    r"\b([A-Za-z0-9_\- ]+?)\s+(?:task\s+)?is\s+(?:currently\s+)?unassigned\b", re.I
)

_ACTION_ITEM_PATTERN = re.compile(
    r"^\s*[-*]\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*:\s+(.{10,})$"
)


def _detect_tech_topic(line: str) -> Dict[str, str]:
    """Detect structured topic/choice in architecture or chat decisions (e.g. cache: lru vs redis, db: sqlite vs postgres)."""
    low = line.lower()
    attrs: Dict[str, str] = {}
    if "redis" in low and ("cache" in low or "session" in low or "switched" in low):
        attrs["topic"] = "caching"
        attrs["choice"] = "redis"
    elif ("in-memory" in low or "lru" in low) and "cache" in low:
        attrs["topic"] = "caching"
        attrs["choice"] = "in-memory-lru"
    elif "postgresql" in low or "postgres" in low:
        attrs["topic"] = "database-engine"
        attrs["choice"] = "postgresql"
    elif "sqlite" in low and ("using" in low or "switched" in low or "persistence" in low or "database" in low):
        attrs["topic"] = "database-engine"
        attrs["choice"] = "sqlite"
    return attrs


def _split_Candidate_Segments(text: str) -> List[str]:
    """Split markdown/chat/doc text into clean line or sentence segments that are exact substrings of text."""
    segments: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if len(line) < 8 or line.startswith("#") or line.startswith("---"):
            continue
        # Strip leading markdown list markers while keeping exact substring of raw_line
        m = re.match(r"^(?:[-*]|\d+\.)\s+(.*)$", line)
        cand = m.group(1).strip() if m else line
        if cand and cand in text:
            segments.append(cand)
            # Also split multi-sentence lines on ". " so individual sentences can be matched cleanly
            if ". " in cand:
                for sent in cand.split(". "):
                    s = sent.strip()
                    if len(s) >= 12 and s in text:
                        segments.append(s)
    # Deduplicate preserving order
    seen = set()
    out = []
    for s in segments:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _extract_from_prose_chunk(chunk: NChunk) -> List[RawClaim]:
    """Pattern-based extraction over markdown, PDF, DOCX, TXT, manual, and chat chunks."""
    claims: List[RawClaim] = []
    default_mod = guess_module_from_text_or_paths(chunk.text) or "general"

    # Check action items line by line first
    for raw_line in chunk.text.splitlines():
        m_act = _ACTION_ITEM_PATTERN.match(raw_line)
        if m_act:
            actor = clean_person(m_act.group(1))
            action_text = m_act.group(2).strip()
            excerpt = raw_line.strip()
            mod = guess_module_from_text_or_paths(action_text) or default_mod
            claims.append(
                RawClaim(
                    type="task_status",
                    title=f"Action item ({actor}): {action_text[:70]}",
                    text=f"Action item for {actor}: {action_text}",
                    evidence=[RawEvidence(chunk_id=chunk.id, excerpt=excerpt)],
                    module=mod,
                    owner=actor,
                    verification="inferred",
                    extractor="rule",
                    author=chunk.author or actor,
                    event_time=chunk.timestamp,
                    task_key=slug(action_text[:50]),
                    attrs={"status": "pending", "action_item": True},
                )
            )

    segments = _split_Candidate_Segments(chunk.text)
    used_types_per_seg: set = set()

    for seg in segments:
        mod = guess_module_from_text_or_paths(seg) or default_mod

        # 1. Explicit unassigned responsibility in prose
        m_un = _UNASSIGNED_PATTERN.search(seg)
        if m_un and ("unassigned", seg) not in used_types_per_seg:
            used_types_per_seg.add(("unassigned", seg))
            subj = m_un.group(1).strip(" -*:,.")
            subj_mod = guess_module_from_text_or_paths(subj) or mod
            claims.append(
                RawClaim(
                    type="task_status",
                    title=f"Unassigned task: {subj[:70]}",
                    text=seg,
                    evidence=[RawEvidence(chunk_id=chunk.id, excerpt=seg)],
                    module=subj_mod,
                    owner=None,
                    verification="verified",
                    extractor="rule",
                    author=chunk.author,
                    event_time=chunk.timestamp,
                    task_key=slug(subj),
                    attrs={"status": "pending", "unassigned": True, "task_title": subj},
                )
            )

        # 2. Ownership
        for pat in _OWNERSHIP_PATTERNS:
            m_own = pat.search(seg)
            if m_own:
                person = clean_person(m_own.group(1))
                scope_raw = m_own.group(2) if m_own.lastindex and m_own.lastindex >= 2 else seg
                own_mod = guess_module_from_text_or_paths(scope_raw) or guess_module_from_text_or_paths(seg) or mod
                key = ("ownership", person, own_mod)
                if person and key not in used_types_per_seg:
                    used_types_per_seg.add(key)
                    claims.append(
                        RawClaim(
                            type="ownership",
                            title=f"Owner of {own_mod}: {person}",
                            text=seg,
                            evidence=[RawEvidence(chunk_id=chunk.id, excerpt=seg)],
                            module=own_mod,
                            owner=person,
                            verification="verified",
                            extractor="rule",
                            author=chunk.author,
                            event_time=chunk.timestamp,
                            attrs={"scope": "module", "module": own_mod},
                        )
                    )
                break

        # 3. Testing pending / present
        if any(p.search(seg) for p in _TESTING_PENDING_PATTERNS):
            key = ("testing_pending", mod, seg[:40])
            if key not in used_types_per_seg:
                used_types_per_seg.add(key)
                claims.append(
                    RawClaim(
                        type="testing",
                        title=f"Testing pending in {mod}",
                        text=seg,
                        evidence=[RawEvidence(chunk_id=chunk.id, excerpt=seg)],
                        module=mod,
                        owner=clean_person(chunk.author),
                        verification="verified",
                        extractor="rule",
                        author=chunk.author,
                        event_time=chunk.timestamp,
                        attrs={"testing_status": "pending"},
                    )
                )
                # If a note explicitly states testing/review is pending or not complete for a module,
                # also record a task_status claim so status contradictions are surfaced
                claims.append(
                    RawClaim(
                        type="task_status",
                        title=f"{mod} status: pending validation/testing",
                        text=seg,
                        evidence=[RawEvidence(chunk_id=chunk.id, excerpt=seg)],
                        module=mod,
                        owner=clean_person(chunk.author),
                        verification="verified",
                        extractor="rule",
                        author=chunk.author,
                        event_time=chunk.timestamp,
                        task_key=slug(f"{mod}-validation"),
                        attrs={"status": "pending", "testing_pending": True},
                    )
                )
        elif any(p.search(seg) for p in _TESTING_PRESENT_PATTERNS):
            key = ("testing_present", mod, seg[:40])
            if key not in used_types_per_seg:
                used_types_per_seg.add(key)
                claims.append(
                    RawClaim(
                        type="testing",
                        title=f"Tests recorded for {mod}",
                        text=seg,
                        evidence=[RawEvidence(chunk_id=chunk.id, excerpt=seg)],
                        module=mod,
                        owner=clean_person(chunk.author),
                        verification="verified",
                        extractor="rule",
                        author=chunk.author,
                        event_time=chunk.timestamp,
                        attrs={"testing_status": "present"},
                    )
                )

        # 4. Blockers
        if any(p.search(seg) for p in _BLOCKER_PATTERNS):
            key = ("blocker", mod, seg[:40])
            if key not in used_types_per_seg:
                used_types_per_seg.add(key)
                claims.append(
                    RawClaim(
                        type="blocker",
                        title=f"Blocker in {mod}: {seg[:70]}",
                        text=seg,
                        evidence=[RawEvidence(chunk_id=chunk.id, excerpt=seg)],
                        module=mod,
                        owner=clean_person(chunk.author),
                        verification="verified",
                        extractor="rule",
                        author=chunk.author,
                        event_time=chunk.timestamp,
                        attrs={"resolved": False},
                    )
                )

        # 5. Dependencies
        if any(p.search(seg) for p in _DEPENDENCY_PATTERNS):
            key = ("dependency", mod, seg[:40])
            if key not in used_types_per_seg:
                used_types_per_seg.add(key)
                claims.append(
                    RawClaim(
                        type="dependency",
                        title=f"Dependency in {mod}: {seg[:70]}",
                        text=seg,
                        evidence=[RawEvidence(chunk_id=chunk.id, excerpt=seg)],
                        module=mod,
                        owner=clean_person(chunk.author),
                        verification="inferred",
                        extractor="rule",
                        author=chunk.author,
                        event_time=chunk.timestamp,
                        attrs={"prose_dependency": True, "unresolved_open_loop": "will confirm" in seg.lower()},
                    )
                )

        # 6. Decisions
        tech_attrs = _detect_tech_topic(seg)
        if any(p.search(seg) for p in _DECISION_PATTERNS) or tech_attrs:
            key = ("decision", mod, seg[:40])
            if key not in used_types_per_seg:
                used_types_per_seg.add(key)
                dec_mod = "database" if tech_attrs.get("topic") == "database-engine" else mod
                ver = "inferred" if chunk.source_type == "chat_json" else "verified"
                claims.append(
                    RawClaim(
                        type="decision",
                        title=f"Decision ({dec_mod}): {seg[:75]}",
                        text=seg,
                        evidence=[RawEvidence(chunk_id=chunk.id, excerpt=seg)],
                        module=dec_mod,
                        owner=clean_person(chunk.author),
                        verification=ver,
                        extractor="rule",
                        author=chunk.author,
                        event_time=chunk.timestamp,
                        attrs={"source_type": chunk.source_type, **tech_attrs},
                    )
                )

    return claims


def extract_deterministic_for_chunks(chunks: List[NChunk]) -> List[RawClaim]:
    """Run the deterministic rule extractor across a list of normalised chunks."""
    out: List[RawClaim] = []
    for ch in chunks:
        loc = ch.locator or ""
        if ch.source_type == "csv":
            out.extend(_extract_from_csv_chunk(ch))
        elif ch.source_type == "github_commits" or loc.startswith(("sha:", "pr:", "issue:")):
            out.extend(_extract_from_commit_chunk(ch))
        else:
            out.extend(_extract_from_prose_chunk(ch))
    return out


# ── Optional LLM Extractor with Pydantic schema & excerpt verification ───────

class LLMEvidenceItem(BaseModel):
    chunk_id: str
    excerpt: str


class LLMClaimItem(BaseModel):
    claim_type: str
    title: str
    text: str
    module: Optional[str] = "general"
    owner: Optional[str] = None
    verification_status: str = "inferred"
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    status: Optional[str] = None
    evidence: List[LLMEvidenceItem]


class LLMExtractionPayload(BaseModel):
    claims: List[LLMClaimItem]


def _default_llm_call(chunks: List[NChunk]) -> str:
    """Call OpenAI-compatible JSON endpoint with schema instructions."""
    prompt_chunks = [
        {"chunk_id": c.id, "source_type": c.source_type, "author": c.author, "text": c.text}
        for c in chunks
    ]
    sys_msg = (
        "Extract factual project claims as strict JSON matching schema: "
        '{"claims": [{"claim_type": "task_status|decision|ownership|blocker|dependency|contribution|testing|doc_gap", '
        '"title": "...", "text": "...", "module": "...", "owner": null, '
        '"verification_status": "verified|inferred|missing", "confidence": 0.85, '
        '"status": "completed|in_progress|pending|blocked|unknown|null", '
        '"evidence": [{"chunk_id": "...", "excerpt": "exact substring from chunk text"}]}]}. '
        "Every excerpt MUST be copied verbatim from the chunk text. "
        "Never infer completed status from a commit alone."
    )
    url = f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.LLM_MODEL,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": json.dumps({"chunks": prompt_chunks})},
        ],
        "temperature": 0.0,
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def extract_with_llm_for_source(
    source_id: str,
    chunks: List[NChunk],
    llm_caller: Optional[Callable[[List[NChunk]], str]] = None,
) -> Tuple[List[RawClaim], Optional[str], int]:
    """Run LLM extraction for one source's chunks, validating schema and excerpts.

    Returns (claims, fallback_reason_or_None, dropped_hallucinated_count).
    If the call fails or JSON is invalid, falls back to deterministic extraction and records reason.
    """
    caller = llm_caller or _default_llm_call
    chunk_map = {c.id: c for c in chunks}
    dropped = 0

    try:
        raw_json = caller(chunks)
        parsed = json.loads(raw_json)
        payload = LLMExtractionPayload.model_validate(parsed)
    except ( Exception, json.JSONDecodeError, ValidationError) as exc:
        fallback_claims = extract_deterministic_for_chunks(chunks)
        return fallback_claims, f"Source {source_id}: LLM failed ({type(exc).__name__}: {str(exc)[:180]}); used rule fallback.", 0

    valid_claims: List[RawClaim] = []
    for item in payload.claims:
        if item.claim_type not in CLAIM_TYPES:
            dropped += 1
            continue
        verified_ev: List[RawEvidence] = []
        cited_chunks: List[NChunk] = []
        for ev in item.evidence:
            ch = chunk_map.get(ev.chunk_id)
            if not ch:
                dropped += 1
                continue
            exact = exact_excerpt_in_chunk(ch.text, ev.excerpt)
            if not exact:
                dropped += 1
                continue
            verified_ev.append(RawEvidence(chunk_id=ch.id, excerpt=exact))
            cited_chunks.append(ch)

        if not verified_ev:
            # Drop claim whose excerpt failed verification
            continue

        # Never allow a commit alone to mark a task completed
        all_commits = all(
            c.source_type == "github_commits" or (c.locator or "").startswith("sha:")
            for c in cited_chunks
        )
        attrs: Dict[str, Any] = {}
        if item.claim_type == "task_status":
            st = normalise_task_status(item.status)
            if all_commits and st == "completed":
                st = "unknown"
            attrs["status"] = st

        ver = item.verification_status if item.verification_status in ("verified", "inferred", "missing") else "inferred"
        if all_commits and item.claim_type == "task_status":
            ver = "inferred"

        first_ch = cited_chunks[0]
        valid_claims.append(
            RawClaim(
                type=item.claim_type,
                title=item.title.strip()[:250],
                text=item.text.strip(),
                evidence=verified_ev,
                module=module_name(item.module) or "general",
                owner=clean_person(item.owner),
                verification=ver,
                confidence=item.confidence,
                extractor="llm",
                author=first_ch.author,
                event_time=first_ch.timestamp,
                task_key=slug(item.title[:60]),
                attrs=attrs,
            )
        )

    return valid_claims, None, dropped


def extract_all(
    chunks: List[NChunk],
    llm_caller: Optional[Callable[[List[NChunk]], str]] = None,
) -> Tuple[List[RawClaim], Dict[str, Any]]:
    """Extract claims across all chunks. Uses LLM if LLM_API_KEY is configured (or llm_caller is passed)."""
    use_llm = bool(settings.LLM_API_KEY) or (llm_caller is not None)
    meta: Dict[str, Any] = {
        "llm_enabled": use_llm,
        "llm_fallbacks": [],
        "dropped_unverified_excerpts": 0,
    }

    if not use_llm:
        return extract_deterministic_for_chunks(chunks), meta

    by_source: Dict[str, List[NChunk]] = {}
    for ch in chunks:
        by_source.setdefault(ch.source_id, []).append(ch)

    all_claims: List[RawClaim] = []
    for sid, src_chunks in by_source.items():
        claims, fb_reason, dropped = extract_with_llm_for_source(sid, src_chunks, llm_caller=llm_caller)
        all_claims.extend(claims)
        meta["dropped_unverified_excerpts"] += dropped
        if fb_reason:
            meta["llm_fallbacks"].append(fb_reason)

    return all_claims, meta
