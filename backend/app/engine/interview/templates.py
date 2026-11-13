"""Deterministic question templates. Every placeholder is filled from real values stored in Gap.facts."""

from typing import Any, Dict

from app.engine.interview.gaps import Gap


def _owner_conflict(f: Dict[str, Any]) -> str:
    owners = f.get("owners") or []
    if len(owners) >= 2:
        a, b = owners[0], owners[1]
        return (
            f"Who owns {f['module']}? {a['source']} names {a['owner']}, "
            f"{b['source']} names {b['owner']}."
        )
    return f"Who owns {f['module']}? Sources disagree on the owner."


def _status_conflict(f: Dict[str, Any]) -> str:
    if f.get("choices"):
        a, b = f["choices"][0], f["choices"][1]
        return (
            f"Which {f['topic']} approach is used in {f['module']}: {a['choice']} or {b['choice']}? "
            f"{a['source']} says {a['choice']}, {b['source']} says {b['choice']}."
        )
    if f.get("states"):
        a, b = f["states"][0], f["states"][1]
        return (
            f"What is the actual status in {f['module']}? {a['source']} records '{a['title']}' as {a['state']}, "
            f"while {b['source']} records '{b['title']}' as {b['state']}."
        )
    return f"What is the actual status in {f['module']}? Sources give conflicting statuses."


def _dependency(f: Dict[str, Any]) -> str:
    if f.get("depends_on"):
        return f"What is the status of {f['depends_on']}, which {f['from_task']} depends on in {f['module']}?"
    if f.get("blocker_text"):
        return f"Is the blocker in {f['module']} still active: \"{f['blocker_text']}\"? What would clear it?"
    return f"What is unresolved in {f['module']}? A dependency or blocker has no resolution recorded."


def _fallback(f: Dict[str, Any]) -> str:
    return f"Contradiction {f['contradiction_id']} ({f['rule_code']}): {f['reason']} What is the correct position?"


def _unassigned(f: Dict[str, Any]) -> str:
    if f.get("title"):
        return f"Who owns '{f['title']}'? No owner is recorded in {f['module']}."
    return f"Who owns {f['module']}? No owner is recorded in any source."


def _undocumented(f: Dict[str, Any]) -> str:
    return (
        f"Where is {f['module']} documented, and why was it built the way it is? "
        f"{f.get('activity_count', 0)} implementation records exist but no documentation or recorded decision."
    )


def _missing_tests(f: Dict[str, Any]) -> str:
    if f.get("pending"):
        return f"Testing for {f['module']} is recorded as pending. What testing remains and who will complete it?"
    return f"How was {f['module']} tested? No test evidence is recorded."


def render(gap: Gap) -> str:
    f = dict(gap.facts)
    t = gap.gap_type
    if gap.contradiction_id:
        if t == "conflicting_ownership":
            return _owner_conflict(f)
        if t == "status_without_evidence" and f.get("title"):
            return (
                f"Is {f['title']} complete? The task record says {f['raw_status']} "
                f"but no implementation was found in {f['module']}."
            )
        if t == "conflicting_status":
            return _status_conflict(f)
        if t == "unresolved_dependency":
            return _dependency(f)
        if t == "stale_activity" and f.get("title"):
            return f"Is {f['title']} still in progress? The last recorded activity was {f['last_activity']}."
        if t == "unassigned_responsibility":
            return _unassigned(f)
        if t == "undocumented_work":
            return _undocumented(f)
        if t == "missing_test_evidence":
            return _missing_tests(f)
        return _fallback(f)

    if t == "conflicting_claim":
        return f"What is the correct position on '{f['title']}' in {f['module']}? The record in {f['source']} conflicts with other records."
    if t == "unassigned_task":
        return f"Who owns '{f['title']}' in {f['module']}? No owner is recorded in {f['source']}."
    if t == "pending_test":
        return f"Testing for {f['module']} is recorded as pending in {f['source']}. What testing remains and who will complete it?"
    if t == "decision_rationale":
        return f"Why was this decision made: \"{f['text']}\"? No rationale is recorded in {f['source']}."
    if t == "blocker_open":
        return f"Is the blocker in {f['module']} still active: \"{f['text']}\"? What would clear it?"
    if t == "dependency_open":
        return f"Has this dependency in {f['module']} been resolved: \"{f['text']}\"?"
    if t == "missing_claim":
        return f"What is the missing information for '{f['title']}' in {f['module']}? {f['source']} does not state it plainly."
    if t == "inferred_claim":
        return f"Can you confirm '{f['title']}' in {f['module']}? It was inferred from {f['source']} and not stated directly."
    if t == "module_doc":
        return (
            f"Where is {f['module']} documented, and why was it built the way it is? "
            f"No documentation or recorded decision exists for it."
        )
    return f"What should be recorded about {f.get('module', 'this item')}?"
