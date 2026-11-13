"""Analysis run pipeline: orchestrates normalise -> extract -> correlate -> gaps/rules -> validate."""

import json
import secrets
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.engine.correlate import (
    compute_claim_fingerprint,
    correlate_claims,
    detect_doc_gap_claims,
)
from app.engine.extract import extract_all
from app.engine.normalise import load_chunks
from app.engine.types import NChunk, RawClaim, max_clearance
from app.engine.validation import validate_project_citations
from app.models import (
    Claim,
    ClaimEvidence,
    Membership,
    ModuleAlias,
    Project,
    Run,
    RunStage,
    User,
)

STAGE_DEFS = [
    (1, "reading_sources", "Reading sources"),
    (2, "extracting", "Extracting claims"),
    (3, "correlating", "Correlating modules and threads"),
    (4, "detecting_gaps", "Detecting gaps"),
    (5, "preparing", "Preparing knowledge base"),
]


def _new_claim_id() -> str:
    return f"CLM-{secrets.token_hex(4).upper()}"


def create_run_record(db: Session, project_id: str, user_id: Optional[str] = None) -> Run:
    """Create a Run row and its 5 RunStage rows in 'pending' state."""
    run = Run(
        project_id=project_id,
        status="running",
        started_by=user_id,
        llm_enabled=bool(settings.LLM_API_KEY),
    )
    db.add(run)
    db.flush()
    for ordinal, key, label in STAGE_DEFS:
        db.add(
            RunStage(
                run_id=run.id,
                ordinal=ordinal,
                key=key,
                label=label,
                status="pending",
            )
        )
    db.commit()
    db.refresh(run)
    return run


def _start_stage(db: Session, stage: RunStage) -> None:
    stage.status = "running"
    stage.started_at = datetime.now(timezone.utc)
    db.commit()


def _finish_stage(db: Session, stage: RunStage, count: int, detail: str = "") -> None:
    stage.status = "done"
    stage.count = count
    stage.detail = detail
    stage.finished_at = datetime.now(timezone.utc)
    db.commit()


def _resolve_owner_user_id(db: Session, workspace_id: str, owner_name: Optional[str]) -> Optional[str]:
    if not owner_name:
        return None
    name_low = owner_name.strip().lower()
    memberships = db.query(Membership).filter(Membership.workspace_id == workspace_id).all()
    for m in memberships:
        u = m.user or db.get(User, m.user_id)
        if not u:
            continue
        if u.name.strip().lower() == name_low or u.name.strip().lower().startswith(name_low + " "):
            return u.id
    return None


def execute_run(
    db: Session,
    run_id: str,
    llm_caller: Optional[Callable[[List[NChunk]], str]] = None,
) -> Run:
    """Execute all stages for an existing Run row and persist claims, evidence, and validation."""
    run = db.get(Run, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found.")

    project = db.get(Project, run.project_id)
    if not project:
        raise ValueError(f"Project {run.project_id} not found.")

    stages = {s.key: s for s in run.stages}
    current_stage: Optional[RunStage] = None

    try:
        # ── Stage 1: reading_sources ─────────────────────────────────────────
        current_stage = stages["reading_sources"]
        _start_stage(db, current_stage)
        chunks, sources_map, norm_stats = load_chunks(db, project.id)
        chunk_by_id = {c.id: c for c in chunks}
        _finish_stage(
            db,
            current_stage,
            count=len(chunks),
            detail=f"Read {norm_stats['sources_parsed']} parsed source(s), {len(chunks)} chunk(s).",
        )

        # ── Stage 2: extracting ──────────────────────────────────────────────
        current_stage = stages["extracting"]
        _start_stage(db, current_stage)
        raw_claims, ext_meta = extract_all(chunks, llm_caller=llm_caller)
        run.llm_enabled = bool(ext_meta.get("llm_enabled"))
        _finish_stage(
            db,
            current_stage,
            count=len(raw_claims),
            detail=f"Extracted {len(raw_claims)} raw claim candidate(s).",
        )

        # ── Stage 3: correlating ─────────────────────────────────────────────
        current_stage = stages["correlating"]
        _start_stage(db, current_stage)
        aliases = {
            a.alias: a.target
            for a in db.query(ModuleAlias).filter(ModuleAlias.project_id == project.id).all()
        }
        correlated = correlate_claims(raw_claims, chunks, aliases=aliases)
        modules_found = sorted({c.module for c in correlated if c.module})
        _finish_stage(
            db,
            current_stage,
            count=len(modules_found),
            detail=f"Correlated {len(correlated)} claim(s) across {len(modules_found)} module(s).",
        )

        # ── Stage 4: detecting_gaps ──────────────────────────────────────────
        current_stage = stages["detecting_gaps"]
        _start_stage(db, current_stage)
        doc_gaps = detect_doc_gap_claims(correlated, chunks, aliases=aliases)
        all_candidates: List[RawClaim] = correlated + doc_gaps
        _finish_stage(
            db,
            current_stage,
            count=len(doc_gaps),
            detail=f"Identified {len(doc_gaps)} documentation gap(s).",
        )

        # ── Stage 5: preparing (persist claims, preserve reviewed, validate) ─
        current_stage = stages["preparing"]
        _start_stage(db, current_stage)

        # Preserve human work (reviewed, flagged, human-authored, or carrying interview answers); remove only
        # untouched machine-extracted claims.
        existing_claims = db.query(Claim).filter(Claim.project_id == project.id).all()
        answered_claim_ids = {
            row[0]
            for row in db.query(ClaimEvidence.claim_id)
            .filter(ClaimEvidence.evidence_type == "interview_answer")
            .all()
        }
        reviewed_fingerprints = set()
        for ec in existing_claims:
            keep = (
                ec.review_status != "unreviewed"
                or ec.extractor == "human"
                or ec.id in answered_claim_ids
            )
            if keep:
                if ec.fingerprint:
                    reviewed_fingerprints.add(ec.fingerprint)
            else:
                db.delete(ec)
        db.flush()

        persisted_count = 0
        for rc in all_candidates:
            fp = rc.attrs.get("fingerprint") or compute_claim_fingerprint(rc)
            if fp in reviewed_fingerprints:
                # Never overwrite or duplicate a claim a human has already reviewed
                continue

            # Resolve cited chunks and compute clearance strictly from cited sources
            valid_ev: List[tuple[NChunk, str]] = []
            for ev in rc.evidence:
                ch = chunk_by_id.get(ev.chunk_id)
                if ch and ev.excerpt and ev.excerpt in ch.text:
                    valid_ev.append((ch, ev.excerpt))

            if not valid_ev:
                continue

            cl_level = max_clearance(ch.clearance for ch, _ in valid_ev)
            owner_uid = _resolve_owner_user_id(db, project.workspace_id, rc.owner)

            clm = Claim(
                id=_new_claim_id(),
                project_id=project.id,
                claim_type=rc.type,
                title=rc.title[:255],
                text=rc.text,
                module=rc.module or "general",
                owner_id=owner_uid,
                owner_name=rc.owner,
                author=rc.author,
                verification_status=rc.verification,
                review_status="unreviewed",
                confidence=rc.confidence,
                clearance_level=cl_level,
                extractor=rc.extractor,
                event_time=rc.event_time,
                task_key=rc.task_key,
                fingerprint=fp,
                run_id=run.id,
                attrs_json=json.dumps(rc.attrs),
            )
            db.add(clm)
            db.flush()

            for ch, excerpt in valid_ev:
                db.add(
                    ClaimEvidence(
                        claim_id=clm.id,
                        source_id=ch.source_id,
                        chunk_id=ch.id,
                        excerpt=excerpt,
                        author=ch.author,
                        timestamp=ch.timestamp,
                    )
                )
            persisted_count += 1

        db.commit()

        # Run Contradiction Radar rules if available (Phase 5)
        contradictions_opened = 0
        try:
            from app.engine.rules import run_contradiction_radar
            contradictions_opened = run_contradiction_radar(db, project.id, run_id=run.id)
        except ImportError:
            pass

        # Run citation validation service (Phase 4)
        val_report = validate_project_citations(db, project.id, role="admin", enforce=True)

        total_active_claims = db.query(Claim).filter(Claim.project_id == project.id).count()
        _finish_stage(
            db,
            current_stage,
            count=total_active_claims,
            detail=(
                f"Prepared {total_active_claims} claim(s) "
                f"({val_report['invalid_citation_count']} invalid citation(s))."
            ),
        )

        run.status = "completed"
        run.finished_at = datetime.now(timezone.utc)
        run.summary_json = json.dumps({
            **norm_stats,
            **ext_meta,
            "claims_total": total_active_claims,
            "claims_created": persisted_count,
            "modules_count": len(modules_found),
            "doc_gaps_count": len(doc_gaps),
            "contradictions_open": contradictions_opened,
            "invalid_citation_count": val_report["invalid_citation_count"],
        })
        db.commit()
        db.refresh(run)
        return run

    except Exception as exc:
        db.rollback()
        run = db.get(Run, run_id)
        if run:
            for s in run.stages:
                if s.status == "running":
                    s.status = "failed"
                    s.detail = str(exc)[:500]
                    s.finished_at = datetime.now(timezone.utc)
            run.status = "failed"
            run.error_message = str(exc)[:1000]
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(run)
        raise


def run_analysis_sync(
    db: Session,
    project_id: str,
    user_id: Optional[str] = None,
    llm_caller: Optional[Callable[[List[NChunk]], str]] = None,
) -> Run:
    """Create and execute a full analysis run synchronously (used by tests and background jobs)."""
    run = create_run_record(db, project_id=project_id, user_id=user_id)
    return execute_run(db, run.id, llm_caller=llm_caller)


def run_analysis_background_job(run_id: str) -> None:
    """BackgroundTasks entry point that opens its own DB session."""
    from app import db as db_module

    session = db_module.SessionLocal()
    try:
        execute_run(session, run_id)
    finally:
        session.close()
