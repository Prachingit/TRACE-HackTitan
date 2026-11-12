"""Correlation engine: module canonicalisation, thread grouping, deduplication & gap detection."""

import hashlib
import re
from typing import Dict, List, Set, Tuple

from app.engine.types import (
    DOC_SOURCE_TYPES,
    GENERIC_MODULES,
    NChunk,
    RawClaim,
    module_name,
    norm_ws,
    slug,
    tokens,
)


def apply_module_aliases(claims: List[RawClaim], aliases: Dict[str, str]) -> None:
    """Apply user-defined module renames/merges in-place."""
    if not aliases:
        return
    norm_map = {module_name(k) or k: module_name(v) or v for k, v in aliases.items()}
    for c in claims:
        m = module_name(c.module) or "general"
        while m in norm_map and norm_map[m] != m:
            m = norm_map[m]
        c.module = m


def correlate_claims(
    claims: List[RawClaim],
    chunks: List[NChunk],
    aliases: Dict[str, str] | None = None,
) -> List[RawClaim]:
    """Correlate claims by module, keyword/path overlap, and work-thread similarity; deduplicate."""
    aliases = aliases or {}
    apply_module_aliases(claims, aliases)

    # 1. Collect known non-generic modules and their characteristic token vocabulary
    mod_vocab: Dict[str, Set[str]] = {}
    for c in claims:
        m = module_name(c.module) or "general"
        c.module = m
        if m not in GENERIC_MODULES:
            vocab = mod_vocab.setdefault(m, set())
            vocab.update(tokens(m))
            vocab.update(tokens(c.title))

    # 2. Reassign 'general' claims if they strongly overlap a known module's vocabulary
    if mod_vocab:
        for c in claims:
            if c.module in GENERIC_MODULES:
                ctoks = tokens(c.title + " " + c.text)
                best_mod = None
                best_score = 0
                for mod, vocab in mod_vocab.items():
                    mod_stem_toks = tokens(mod)
                    # Direct mention of the module's name stem wins immediately
                    if mod_stem_toks and mod_stem_toks.issubset(ctoks):
                        best_mod = mod
                        best_score = 100
                        break
                    overlap = len(ctoks & vocab)
                    if overlap > best_score and overlap >= 2:
                        best_score = overlap
                        best_mod = mod
                if best_mod:
                    c.module = best_mod

    # 3. Correlate task threads: link prose/commit claims to known CSV task keys when they share
    # explicit task IDs (e.g. TSK-002, T-15) or high title token overlap within the same module
    known_tasks: List[Tuple[str, str, Set[str]]] = []
    for c in claims:
        if c.type == "task_status" and c.attrs.get("task_id"):
            tid = str(c.attrs["task_id"]).upper()
            t_title = str(c.attrs.get("task_title") or c.title)
            known_tasks.append((tid, c.module or "general", tokens(t_title)))

    for c in claims:
        # Explicit task ID mention in text or title
        for tid, tmod, ttoks in known_tasks:
            if re.search(rf"\b{re.escape(tid)}\b", c.title + " " + c.text, re.I):
                c.task_key = tid
                if c.module in GENERIC_MODULES:
                    c.module = tmod
                break
        if not c.task_key and c.type in ("task_status", "ownership", "testing", "blocker"):
            ctoks = tokens(c.title + " " + c.text)
            for tid, tmod, ttoks in known_tasks:
                if tmod == c.module and ttoks and len(ctoks & ttoks) >= max(2, len(ttoks)):
                    c.task_key = tid
                    break
        if not c.task_key:
            c.task_key = f"{c.module}:{slug(c.title[:50])}"

    # 4. Deduplicate claims by deterministic fingerprint and merge evidence
    apply_module_aliases(claims, aliases)
    merged: Dict[str, RawClaim] = {}
    for c in claims:
        fp = compute_claim_fingerprint(c)
        c.attrs["fingerprint"] = fp
        if fp not in merged:
            merged[fp] = c
        else:
            existing = merged[fp]
            seen_ev = {(e.chunk_id, e.excerpt) for e in existing.evidence}
            for ev in c.evidence:
                if (ev.chunk_id, ev.excerpt) not in seen_ev:
                    existing.evidence.append(ev)
                    seen_ev.add((ev.chunk_id, ev.excerpt))
    return list(merged.values())


def detect_doc_gap_claims(
    claims: List[RawClaim],
    chunks: List[NChunk],
    aliases: Dict[str, str] | None = None,
) -> List[RawClaim]:
    """Emit explicit 'doc_gap' claims (verification='missing') for modules with activity but no docs/decisions."""
    aliases = aliases or {}
    chunk_by_id = {ch.id: ch for ch in chunks}
    by_mod: Dict[str, List[RawClaim]] = {}
    for c in claims:
        m = module_name(c.module) or "general"
        if m not in GENERIC_MODULES:
            by_mod.setdefault(m, []).append(c)

    doc_gaps: List[RawClaim] = []
    for mod, mclaims in sorted(by_mod.items()):
        has_doc_or_decision = False
        activity_claims: List[RawClaim] = []
        for mc in mclaims:
            if mc.type == "decision":
                has_doc_or_decision = True
            for ev in mc.evidence:
                ch = chunk_by_id.get(ev.chunk_id)
                if ch and ch.source_type in DOC_SOURCE_TYPES:
                    has_doc_or_decision = True
            if mc.type == "contribution":
                activity_claims.append(mc)

        if len(activity_claims) >= 2 and not has_doc_or_decision:
            sample_ev = activity_claims[0].evidence[:1]
            if sample_ev:
                gap = RawClaim(
                    type="doc_gap",
                    title=f"Missing documentation for module '{mod}'",
                    text=(
                        f"Module '{mod}' has {len(activity_claims)} activity/contribution records "
                        f"but no architecture documentation or recorded design decision."
                    ),
                    evidence=list(sample_ev),
                    module=mod,
                    owner=activity_claims[0].owner,
                    verification="missing",
                    extractor="rule",
                    author=activity_claims[0].author,
                    event_time=activity_claims[0].event_time,
                    task_key=f"{mod}:doc-gap",
                    attrs={"activity_count": len(activity_claims)},
                )
                gap.attrs["fingerprint"] = compute_claim_fingerprint(gap)
                doc_gaps.append(gap)

    apply_module_aliases(doc_gaps, aliases)
    return doc_gaps


def compute_claim_fingerprint(c: RawClaim) -> str:
    """Stable hash for idempotent re-analysis across runs."""
    first_chunk = c.evidence[0].chunk_id if c.evidence else ""
    key_str = "|".join([
        c.type,
        module_name(c.module) or "general",
        (c.owner or "").lower(),
        norm_ws(c.title).lower(),
        norm_ws(c.text).lower()[:200],
        first_chunk,
    ])
    return hashlib.sha256(key_str.encode("utf-8")).hexdigest()[:32]
