"""Ranked continuation plan engine (Phase 7).

Builds a deterministic, dependency-aware continuation plan from project claims,
open contradictions, unanswered interview questions, and source evidence.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.engine.clearance import max_clearance
from app.models import Claim, ClaimEvidence, Contradiction, InterviewQuestion, Source

_FILE_PATH_RE = re.compile(
    r"(?:[A-Za-z0-9_.\-]+/)+[A-Za-z0-9_.\-]+\.[A-Za-z0-9]{1,8}"
    r"|\b[A-Za-z0-9_\-]+\.(?:py|js|jsx|ts|tsx|sql|md|csv|json|yml|yaml|toml)\b"
)


def _parse_attrs(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            val = json.loads(raw)
            return val if isinstance(val, dict) else {}
        except Exception:
            return {}
    return {}


def _norm_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _ev_locator(ev: ClaimEvidence) -> Optional[str]:
    ch = getattr(ev, "chunk", None)
    return ch.locator if ch else None


def _extract_relevant_files(
    ev_rows: Sequence[ClaimEvidence],
    sources_by_id: Dict[str, Source],
) -> List[str]:
    found: List[str] = []
    seen: Set[str] = set()
    for ev in ev_rows:
        src = sources_by_id.get(ev.source_id) if ev.source_id else None
        if src and src.filename:
            if src.filename not in seen:
                seen.add(src.filename)
                found.append(src.filename)
        for text in (ev.excerpt or "", _ev_locator(ev) or ""):
            for match in _FILE_PATH_RE.findall(text):
                if match not in seen:
                    seen.add(match)
                    found.append(match)
    return found[:8]


def _evidence_refs(
    ev_rows: Sequence[ClaimEvidence],
    sources_by_id: Dict[str, Source],
) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for ev in ev_rows[:5]:
        src = sources_by_id.get(ev.source_id) if ev.source_id else None
        refs.append(
            {
                "evidence_id": ev.id,
                "source_id": ev.source_id,
                "source_name": src.filename if src else None,
                "locator": _ev_locator(ev),
                "excerpt": (ev.excerpt or "")[:220],
                "evidence_type": ev.evidence_type,
            }
        )
    return refs


def _build_dependency_graph(
    claims: Sequence[Claim],
) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]], Dict[str, List[Claim]]]:
    """Return (prereq_to_dependents, dependent_to_prereqs, claims_by_node)."""
    prereq_to_deps: Dict[str, Set[str]] = defaultdict(set)
    dep_to_prereqs: Dict[str, Set[str]] = defaultdict(set)
    claims_by_node: Dict[str, List[Claim]] = defaultdict(list)

    for c in claims:
        attrs = _parse_attrs(c.attrs_json)
        if c.claim_type == "dependency":
            from_task = _norm_key(str(attrs.get("from_task") or c.title or ""))
            depends_on = _norm_key(str(attrs.get("depends_on") or ""))
            if from_task and depends_on and from_task != depends_on:
                prereq_to_deps[depends_on].add(from_task)
                dep_to_prereqs[from_task].add(depends_on)
                claims_by_node[from_task].append(c)
                claims_by_node[depends_on].append(c)
        elif c.claim_type == "task_status":
            task_key = _norm_key(str(attrs.get("task_name") or c.title or ""))
            dep_raw = attrs.get("depends_on")
            if isinstance(dep_raw, str) and dep_raw.strip():
                dep_key = _norm_key(dep_raw)
                if task_key and dep_key and task_key != dep_key:
                    prereq_to_deps[dep_key].add(task_key)
                    dep_to_prereqs[task_key].add(dep_key)
                    claims_by_node[task_key].append(c)
            elif isinstance(dep_raw, list):
                for item in dep_raw:
                    dep_key = _norm_key(str(item))
                    if task_key and dep_key and task_key != dep_key:
                        prereq_to_deps[dep_key].add(task_key)
                        dep_to_prereqs[task_key].add(dep_key)
                        claims_by_node[task_key].append(c)

    return prereq_to_deps, dep_to_prereqs, claims_by_node


def _detect_cycles(prereq_to_deps: Dict[str, Set[str]]) -> List[List[str]]:
    """Detect directed cycles via DFS; return unique cycle paths."""
    state: Dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=done
    stack: List[str] = []
    cycles: List[List[str]] = []
    seen_sigs: Set[Tuple[str, ...]] = set()

    nodes = sorted(set(prereq_to_deps.keys()) | {d for deps in prereq_to_deps.values() for d in deps})

    def dfs(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for nxt in sorted(prereq_to_deps.get(node, ())):
            st = state.get(nxt, 0)
            if st == 1:
                idx = stack.index(nxt)
                cyc = stack[idx:] + [nxt]
                sig = tuple(sorted(set(cyc)))
                if sig not in seen_sigs:
                    seen_sigs.add(sig)
                    cycles.append(cyc)
            elif st == 0:
                dfs(nxt)
        stack.pop()
        state[node] = 2

    for n in nodes:
        if state.get(n, 0) == 0:
            dfs(n)
    return cycles


def _topological_ranks(
    nodes: Sequence[str],
    prereq_to_deps: Dict[str, Set[str]],
    dep_to_prereqs: Dict[str, Set[str]],
    base_priority: Dict[str, Tuple[int, str]],
) -> List[str]:
    """Kahn's topological sort breaking ties by base priority; breaks cycles deterministically."""
    node_set = set(nodes)
    in_degree: Dict[str, int] = {
        n: len([p for p in dep_to_prereqs.get(n, set()) if p in node_set]) for n in node_set
    }
    ready = sorted([n for n, deg in in_degree.items() if deg == 0], key=lambda n: base_priority[n])
    ordered: List[str] = []
    remaining = set(node_set)

    while remaining:
        if not ready:
            # Cycle fallback: pick highest priority remaining node to break cycle cleanly.
            pick = min(remaining, key=lambda n: base_priority[n])
            ready = [pick]
        curr = ready.pop(0)
        if curr not in remaining:
            continue
        remaining.remove(curr)
        ordered.append(curr)
        for dep in sorted(prereq_to_deps.get(curr, ())):
            if dep in remaining:
                in_degree[dep] = max(0, in_degree[dep] - 1)
                if in_degree[dep] == 0:
                    ready.append(dep)
        ready.sort(key=lambda n: base_priority[n])

    return ordered


def _downstream_count(node: str, prereq_to_deps: Dict[str, Set[str]]) -> int:
    visited: Set[str] = set()
    q = deque(prereq_to_deps.get(node, ()))
    while q:
        cur = q.popleft()
        if cur in visited:
            continue
        visited.add(cur)
        for nxt in prereq_to_deps.get(cur, ()):
            if nxt not in visited:
                q.append(nxt)
    return len(visited)


def build_ranked_plan(
    claims: Sequence[Claim],
    contradictions: Sequence[Contradiction],
    questions: Sequence[InterviewQuestion],
    evidence_by_claim: Dict[str, List[ClaimEvidence]],
    sources_by_id: Dict[str, Source],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build (plan_items, cycle_gaps) deterministically from verified/visible evidence.

    Never emits a plan item without real evidence.
    Priority buckets:
      1: Critical blockers
      2: Items blocking downstream tasks/modules
      3: Incomplete implementations (in_progress / pending)
      4: Pending testing
      5: Documentation / knowledge gaps
    """
    prereq_to_deps, dep_to_prereqs, _ = _build_dependency_graph(claims)
    cycles = _detect_cycles(prereq_to_deps)
    cycle_gaps: List[Dict[str, Any]] = []
    for idx, cyc in enumerate(cycles, start=1):
        cycle_gaps.append(
            {
                "id": f"cycle-{idx}",
                "kind": "dependency_cycle",
                "title": "Circular dependency detected: " + " -> ".join(cyc),
                "nodes": cyc,
                "description": (
                    "Dependency claims form a cycle (" + " -> ".join(cyc) + "). "
                    "Review and break the cycle before scheduling dependent work."
                ),
            }
        )

    # Candidate actionable claims (must have at least 1 real evidence row).
    candidates: List[Tuple[str, Claim, int, str]] = []
    seen_claim_ids: Set[str] = set()

    for c in claims:
        ev_rows = evidence_by_claim.get(c.id, [])
        if not ev_rows:
            continue

        attrs = _parse_attrs(c.attrs_json)
        status = str(attrs.get("status") or "").lower()
        node_key = _norm_key(str(attrs.get("task_name") or c.module or c.title or c.id))
        downstream = _downstream_count(node_key, prereq_to_deps)

        bucket: Optional[int] = None
        reason = ""
        if c.claim_type == "blocker" or status == "blocked":
            bucket = 1
            reason = "Active blocker halting progress"
        elif downstream > 0 and (
            c.claim_type in ("task_status", "dependency")
            and status in ("in_progress", "pending", "blocked", "")
        ):
            bucket = 2
            reason = f"Blocks {downstream} downstream task(s)"
        elif c.claim_type == "task_status" and status in ("in_progress", "pending", "unknown"):
            bucket = 3
            reason = f"Task is {status.replace('_', ' ')}"
        elif c.claim_type == "testing":
            bucket = 4
            reason = "Testing pending or incomplete"
        elif c.claim_type == "doc_gap":
            bucket = 5
            reason = "Documentation gap recorded"

        if bucket is not None and c.id not in seen_claim_ids:
            seen_claim_ids.add(c.id)
            candidates.append((node_key, c, bucket, reason))

    # Build item records keyed by unique step id so multiple claims on same node preserve DAG ordering.
    # For DAG ordering, group by node_key and keep per-node best bucket.
    node_items: Dict[str, List[Tuple[Claim, int, str]]] = defaultdict(list)
    for node_key, c, bucket, reason in candidates:
        node_items[node_key].append((c, bucket, reason))

    # Ensure testing items for a task/module come after implementation items on the same node_key.
    node_priority: Dict[str, Tuple[int, str]] = {}
    for node_key, entries in node_items.items():
        best_bucket = min(b for _, b, _ in entries)
        node_priority[node_key] = (best_bucket, node_key)

    ordered_nodes = _topological_ranks(
        list(node_items.keys()),
        prereq_to_deps,
        dep_to_prereqs,
        node_priority,
    )

    plan_items: List[Dict[str, Any]] = []
    priority_counter = 1
    for node_key in ordered_nodes:
        entries = sorted(node_items[node_key], key=lambda e: (e[1], e[0].title or ""))
        for claim, bucket, reason in entries:
            ev_rows = evidence_by_claim.get(claim.id, [])
            if not ev_rows:
                continue
            attrs = _parse_attrs(claim.attrs_json)
            downstream = _downstream_count(node_key, prereq_to_deps)
            prereqs = sorted(dep_to_prereqs.get(node_key, ()))
            if downstream > 0 and "Blocks" not in reason:
                why = f"{reason}; blocks {downstream} downstream task(s)."
            elif prereqs:
                why = f"{reason}; depends on {', '.join(prereqs[:3])}."
            else:
                why = reason

            ev_refs = _evidence_refs(ev_rows, sources_by_id)
            files = _extract_relevant_files(ev_rows, sources_by_id)
            clearance = claim.clearance_level or max_clearance(
                [sources_by_id[e.source_id].clearance_level for e in ev_rows if e.source_id in sources_by_id]
            )
            plan_items.append(
                {
                    "id": f"plan-{claim.id}",
                    "priority": priority_counter,
                    "bucket": bucket,
                    "title": claim.title or claim.text[:90],
                    "description": claim.text,
                    "why_it_matters": why,
                    "module": claim.module,
                    "owner": claim.owner_name,
                    "status": attrs.get("status") or claim.verification_status,
                    "dependencies": prereqs,
                    "downstream_count": downstream,
                    "relevant_files": files,
                    "claim_ids": [claim.id],
                    "verification_status": claim.verification_status,
                    "review_status": claim.review_status,
                    "evidence": ev_refs,
                    "clearance_level": clearance,
                }
            )
            priority_counter += 1

    # Append high-severity unresolved contradictions if they have underlying evidence and aren't already represented.
    for ctr in contradictions:
        if ctr.status != "open":
            continue
        linked_claims = [c for c in (ctr.claims or [])]
        if not linked_claims:
            continue
        ev_all: List[ClaimEvidence] = []
        for lc in linked_claims:
            ev_all.extend(evidence_by_claim.get(lc.id, []))
        if not ev_all:
            continue
        plan_items.append(
            {
                "id": f"plan-ctr-{ctr.id}",
                "priority": priority_counter,
                "bucket": 1 if ctr.severity == "high" else 5,
                "title": f"Resolve contradiction: {ctr.summary[:90]}",
                "description": ctr.summary,
                "why_it_matters": f"{ctr.severity.capitalize()} severity conflict requires verification before relying on this area.",
                "module": ctr.module,
                "owner": None,
                "status": "open_conflict",
                "dependencies": [],
                "downstream_count": 0,
                "relevant_files": _extract_relevant_files(ev_all, sources_by_id),
                "claim_ids": [lc.id for lc in linked_claims],
                "verification_status": "conflicting",
                "review_status": "unreviewed",
                "evidence": _evidence_refs(ev_all, sources_by_id),
                "clearance_level": ctr.clearance_level or "team",
            }
        )
        priority_counter += 1

    # Re-number priority 1..N sorted by (bucket, original topological order) while keeping prereqs ahead of dependents.
    # Since topological order already put prereqs before dependents, preserve that order cleanly.
    return plan_items, cycle_gaps
