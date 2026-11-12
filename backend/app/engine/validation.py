"""Citation validation service for the Evidence Ledger (Phase 4)."""

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.engine.types import HIDDEN_ROLES, norm_ws
from app.models import Chunk, Claim, ClaimEvidence


def is_valid_excerpt(chunk_text: str, excerpt: str) -> bool:
    """Return True if excerpt is a non-empty substring of chunk_text (exact or whitespace-normalised)."""
    if not chunk_text or not excerpt or not excerpt.strip():
        return False
    if excerpt in chunk_text:
        return True
    return norm_ws(excerpt) in norm_ws(chunk_text)


def validate_project_citations(
    db: Session,
    project_id: str,
    role: str = "admin",
    enforce: bool = True,
) -> Dict[str, Any]:
    """Validate every claim's evidence rows against the stored Chunk rows.

    - Confirms each ClaimEvidence references an existing Chunk in the DB.
    - Confirms ClaimEvidence.excerpt is a substring of Chunk.text.
    - Enforces rule: claims with no valid evidence cannot be 'verified' (downgrades to 'missing').
    - Respects role clearance: incoming/departing roles only see non-restricted claims.
    """
    q = db.query(Claim).filter(Claim.project_id == project_id)
    if role in HIDDEN_ROLES:
        q = q.filter(Claim.clearance_level != "restricted")
    claims = q.all()

    total_claims = len(claims)
    total_citations = 0
    valid_citations = 0
    invalid_citations = 0
    invalid_details: List[Dict[str, Any]] = []
    downgraded_claims: List[str] = []

    for clm in claims:
        ev_rows = db.query(ClaimEvidence).filter(ClaimEvidence.claim_id == clm.id).all()
        valid_for_claim = 0

        for ev in ev_rows:
            total_citations += 1
            ch = db.get(Chunk, ev.chunk_id) if ev.chunk_id else None
            if ch is None:
                invalid_citations += 1
                invalid_details.append({
                    "claim_id": clm.id,
                    "evidence_id": ev.id,
                    "chunk_id": ev.chunk_id,
                    "reason": "Referenced chunk does not exist.",
                })
                continue

            if not is_valid_excerpt(ch.text, ev.excerpt):
                invalid_citations += 1
                invalid_details.append({
                    "claim_id": clm.id,
                    "evidence_id": ev.id,
                    "chunk_id": ev.chunk_id,
                    "reason": "Excerpt is not a substring of the cited chunk text.",
                })
                continue

            valid_citations += 1
            valid_for_claim += 1

        # Claims with no valid evidence cannot be 'verified'
        if valid_for_claim == 0 and clm.verification_status == "verified":
            if enforce:
                clm.verification_status = "missing"
                downgraded_claims.append(clm.id)

    if enforce and downgraded_claims:
        db.commit()

    return {
        "project_id": project_id,
        "total_claims": total_claims,
        "total_citations": total_citations,
        "valid_citations": valid_citations,
        "invalid_citation_count": invalid_citations,
        "invalid_citations": invalid_details,
        "downgraded_claim_ids": downgraded_claims,
    }
