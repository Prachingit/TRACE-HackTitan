"""Secondary 'Ask project knowledge' assistant (Phase 7).

Strictly clearance-filtered, citation-verified, and secondary to the Handover Center.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy.orm import Session

from app.engine.clearance import (
    ViewerContext,
    can_view_claim,
    can_view_source,
    filter_chunks,
    filter_claims,
    filter_evidence_for_viewer,
    filter_sources,
)
from app.models import Chunk, Claim, ClaimEvidence, Source

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "what", "who", "when", "where",
    "why", "how", "are", "was", "were", "have", "has", "had", "does", "did",
    "about", "from", "into", "is", "in", "on", "at", "to", "of", "a", "an",
}


def _tokens(text: str) -> Set[str]:
    words = re.findall(r"[a-z0-9_]+", (text or "").lower())
    return {w for w in words if len(w) >= 2 and w not in _STOPWORDS}


def _score_text(q_tokens: Set[str], text: str) -> int:
    if not q_tokens:
        return 0
    t_tokens = _tokens(text)
    return len(q_tokens & t_tokens)


def ask_project_knowledge(
    db: Session,
    project_id: str,
    viewer: ViewerContext,
    question: str,
    *,
    llm_caller: Optional[Callable[[str], str]] = None,
) -> Dict[str, Any]:
    """Answer a question strictly from clearance-filtered claims and chunks."""
    q_clean = (question or "").strip()
    if not q_clean:
        return {
            "answer": "Please enter a question.",
            "citations": [],
            "mode": "deterministic",
            "viewer_profile": viewer.profile,
        }

    q_tokens = _tokens(q_clean)
    all_claims = db.query(Claim).filter(Claim.project_id == project_id).all()
    visible_claims = filter_claims(db, viewer, all_claims)

    all_sources = db.query(Source).filter(Source.project_id == project_id).all()
    visible_sources = filter_sources(viewer, all_sources)
    sources_by_id = {s.id: s for s in visible_sources}

    visible_chunks: List[Chunk] = []
    if visible_sources:
        raw_chunks = (
            db.query(Chunk)
            .filter(Chunk.source_id.in_(list(sources_by_id.keys())))
            .all()
        )
        for ch in raw_chunks:
            src = sources_by_id.get(ch.source_id)
            if src:
                visible_chunks.extend(filter_chunks(viewer, [ch], src))

    # Rank visible claims
    scored_claims: List[Tuple[int, Claim]] = []
    for c in visible_claims:
        blob = f"{c.title or ''} {c.text} {c.module or ''} {c.owner_name or ''}"
        sc = _score_text(q_tokens, blob)
        if sc > 0:
            scored_claims.append((sc, c))
    scored_claims.sort(key=lambda item: (-item[0], item[1].title or item[1].text))
    top_claims = [c for _, c in scored_claims[:5]]

    # Rank visible chunks
    scored_chunks: List[Tuple[int, Chunk]] = []
    for ch in visible_chunks:
        sc = _score_text(q_tokens, ch.text)
        if sc > 0:
            scored_chunks.append((sc, ch))
    scored_chunks.sort(key=lambda item: (-item[0], item[1].ordinal))
    top_chunks = [ch for _, ch in scored_chunks[:4]]

    if not top_claims and not top_chunks:
        not_found_msg = (
            "This isn't recorded in the approved handover."
            if viewer.profile == "incoming"
            else "No recorded evidence matches that question."
        )
        return {
            "answer": not_found_msg,
            "citations": [],
            "mode": "deterministic",
            "viewer_profile": viewer.profile,
        }

    # Build verified citations from visible claims + visible chunks
    citations: List[Dict[str, Any]] = []
    valid_claim_ids: Set[str] = set()
    valid_source_ids: Set[str] = set()

    if top_claims:
        ev_rows = (
            db.query(ClaimEvidence)
            .filter(ClaimEvidence.claim_id.in_([c.id for c in top_claims]))
            .all()
        )
        ev_filtered = filter_evidence_for_viewer(db, viewer, ev_rows)
        ev_by_claim: Dict[str, List[ClaimEvidence]] = defaultdict(list)
        for ev in ev_filtered:
            ev_by_claim[ev.claim_id].append(ev)

        for c in top_claims:
            if not can_view_claim(db, viewer, c):
                continue
            evs = ev_by_claim.get(c.id, [])
            first_ev = evs[0] if evs else None
            src = sources_by_id.get(first_ev.source_id) if first_ev and first_ev.source_id else None
            if src and not can_view_source(viewer, src):
                continue
            valid_claim_ids.add(c.id)
            if src:
                valid_source_ids.add(src.id)
            ev_locator = first_ev.chunk.locator if (first_ev and getattr(first_ev, "chunk", None)) else None
            citations.append(
                {
                    "kind": "claim",
                    "claim_id": c.id,
                    "title": c.title or c.text[:90],
                    "statement": c.text,
                    "verification_status": c.verification_status,
                    "review_status": c.review_status,
                    "source_id": src.id if src else None,
                    "source_name": src.filename if src else None,
                    "locator": ev_locator,
                    "excerpt": (first_ev.excerpt[:200] if first_ev and first_ev.excerpt else None),
                }
            )

    for ch in top_chunks:
        src = sources_by_id.get(ch.source_id)
        if not src or not can_view_source(viewer, src):
            continue
        valid_source_ids.add(src.id)
        citations.append(
            {
                "kind": "chunk",
                "chunk_id": ch.id,
                "source_id": src.id,
                "source_name": src.filename,
                "locator": ch.locator,
                "excerpt": ch.text[:200],
            }
        )

    if not citations:
        not_found_msg = (
            "This isn't recorded in the approved handover."
            if viewer.profile == "incoming"
            else "No recorded evidence matches that question."
        )
        return {
            "answer": not_found_msg,
            "citations": [],
            "mode": "deterministic",
            "viewer_profile": viewer.profile,
        }

    # Deterministic synthesis
    lines: List[str] = []
    for cit in citations[:4]:
        if cit["kind"] == "claim":
            lines.append(
                f"- {cit['statement']} [claim:{cit['claim_id']}] ({cit['verification_status']})"
            )
        else:
            lines.append(
                f"- From {cit['source_name']} ({cit['locator']}): \"{cit['excerpt']}\" [source:{cit['source_id']}]"
            )
    det_answer = "Based on recorded project evidence:\n" + "\n".join(lines)

    # Optional LLM phrasing with strict citation validation
    mode = "deterministic"
    final_answer = det_answer
    if llm_caller is not None or os.getenv("LLM_API_KEY"):
        prompt = (
            "Answer the user question using ONLY the facts below. "
            "Every factual statement MUST cite [claim:<id>] or [source:<id>] from the allowed IDs. "
            f"Allowed claim IDs: {sorted(valid_claim_ids)}. Allowed source IDs: {sorted(valid_source_ids)}.\n\n"
            f"Question: {q_clean}\n\nFacts:\n{det_answer}"
        )
        try:
            candidate = (
                llm_caller(prompt)
                if llm_caller is not None
                else __import__("app.engine.llm_client", fromlist=["call_llm_text"]).call_llm_text(prompt)
            )
            if candidate and candidate.strip():
                cited_claims = set(re.findall(r"\[claim:([A-Za-z0-9\-]+)\]", candidate))
                cited_sources = set(re.findall(r"\[source:([A-Za-z0-9\-]+)\]", candidate))
                if (cited_claims or cited_sources) and cited_claims.issubset(valid_claim_ids) and cited_sources.issubset(valid_source_ids):
                    final_answer = candidate.strip()
                    mode = "llm"
        except Exception:
            final_answer = det_answer
            mode = "deterministic"

    return {
        "answer": final_answer,
        "citations": citations,
        "mode": mode,
        "viewer_profile": viewer.profile,
    }
