"""SQLAlchemy 2.x Database Models for TRACE.

Comprehensive schema defined for Phase 1 to prevent migrations in subsequent phases.
"""

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import relationship

from app.db import Base


def generate_uuid() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=True)  # Nullable for demo users
    role_default = Column(String(64), nullable=False, default="team_member")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    memberships = relationship("Membership", back_populates="user", cascade="all, delete-orphan")


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    memberships = relationship("Membership", back_populates="workspace", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="workspace", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(
        String(32),
        CheckConstraint("role IN ('admin', 'team_member', 'incoming', 'departing')", name="check_membership_role"),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="memberships")
    workspace = relationship("Workspace", back_populates="memberships")


class Project(Base):
    __tablename__ = "projects"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(128), nullable=True)
    team_size = Column(Integer, nullable=False, default=1)
    technologies = Column(Text, nullable=True)
    start_date = Column(DateTime(timezone=True), nullable=True)
    is_synthetic = Column(Boolean, nullable=False, default=False)
    stale_days = Column(Integer, nullable=False, default=28, server_default="28")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    workspace = relationship("Workspace", back_populates="projects")
    sources = relationship("Source", back_populates="project", cascade="all, delete-orphan")
    claims = relationship("Claim", back_populates="project", cascade="all, delete-orphan")
    contradictions = relationship("Contradiction", back_populates="project", cascade="all, delete-orphan")
    handovers = relationship("Handover", back_populates="project", cascade="all, delete-orphan")


class Source(Base):
    __tablename__ = "sources"

    id = Column(String(64), primary_key=True)  # E.g. SRC-001
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(
        String(32),
        CheckConstraint(
            "type IN ('github_commits', 'markdown', 'pdf', 'csv', 'chat_json', 'manual', 'docx', 'txt', 'json')",
            name="check_source_type",
        ),
        nullable=False,
    )
    filename = Column(String(255), nullable=False)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    source_timestamp = Column(DateTime(timezone=True), nullable=True)
    clearance_level = Column(
        String(32),
        CheckConstraint("clearance_level IN ('public', 'team', 'restricted')", name="check_source_clearance"),
        nullable=False,
        index=True,
    )
    status = Column(
        String(32),
        CheckConstraint("status IN ('registered', 'queued', 'parsing', 'parsed', 'failed')", name="check_source_status"),
        nullable=False,
        default="registered",
    )
    error_message = Column(Text, nullable=True)
    content_hash = Column(String(128), nullable=True)
    file_path = Column(String(512), nullable=True)  # Stored path under DATA_DIR

    project = relationship("Project", back_populates="sources")
    chunks = relationship("Chunk", back_populates="source", cascade="all, delete-orphan")
    evidences = relationship("ClaimEvidence", back_populates="source", cascade="all, delete-orphan")
    versions = relationship(
        "SourceVersion", back_populates="source", cascade="all, delete-orphan", order_by="SourceVersion.version_number"
    )
    changes = relationship("SourceChange", back_populates="source", cascade="all, delete-orphan")


class Invite(Base):
    __tablename__ = "invites"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(
        String(32),
        CheckConstraint("role IN ('admin', 'team_member', 'incoming', 'departing')", name="check_invite_role"),
        nullable=False,
    )
    token = Column(String(128), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_used = Column(Boolean, nullable=False, default=False)
    is_revoked = Column(Boolean, nullable=False, default=False)
    created_by = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    workspace = relationship("Workspace")
    creator = relationship("User", foreign_keys=[created_by])


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    source_id = Column(String(64), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    ordinal = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    author = Column(String(128), nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=True)
    locator = Column(String(255), nullable=True)

    source = relationship("Source", back_populates="chunks")
    evidences = relationship("ClaimEvidence", back_populates="chunk")


class Claim(Base):
    __tablename__ = "claims"

    id = Column(String(64), primary_key=True)  # E.g. CLM-001
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_type = Column(
        String(32),
        CheckConstraint(
            "claim_type IN ('task_status', 'decision', 'ownership', 'blocker', 'dependency', 'contribution', 'testing', 'doc_gap')",
            name="check_claim_type",
        ),
        nullable=False,
    )
    text = Column(Text, nullable=False)
    module = Column(String(64), nullable=False)
    owner_id = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    verification_status = Column(
        String(32),
        CheckConstraint(
            "verification_status IN ('verified', 'inferred', 'conflicting', 'missing')",
            name="check_claim_verification_status",
        ),
        nullable=False,
    )
    review_status = Column(
        String(32),
        CheckConstraint(
            "review_status IN ('unreviewed', 'needs_review', 'approved', 'edited', 'rejected')",
            name="check_claim_review_status",
        ),
        nullable=False,
        default="unreviewed",
    )
    confidence = Column(Float, nullable=True)
    clearance_level = Column(
        String(32),
        CheckConstraint("clearance_level IN ('public', 'team', 'restricted')", name="check_claim_clearance"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Phase 3/4 additions
    title = Column(String(255), nullable=True)
    owner_name = Column(String(128), nullable=True)
    author = Column(String(128), nullable=True)
    extractor = Column(String(16), nullable=False, default="rule", server_default="rule")  # rule | llm
    event_time = Column(DateTime(timezone=True), nullable=True)
    task_key = Column(String(255), nullable=True)
    fingerprint = Column(String(64), nullable=True, index=True)
    run_id = Column(String(64), nullable=True)
    attrs_json = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    # Phase 6 additions
    original_text = Column(Text, nullable=True)  # text before the first human edit
    reviewed_by = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_note = Column(Text, nullable=True)
    # Phase 7 additions: admin clearance override with recorded reason
    clearance_override_reason = Column(Text, nullable=True)
    clearance_overridden_by = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    clearance_overridden_at = Column(DateTime(timezone=True), nullable=True)
    # Round 3 (Living Handover): staleness is a flag separate from verification/review status.
    is_stale = Column(Boolean, nullable=False, default=False, server_default=false())
    stale_reason = Column(Text, nullable=True)
    stale_change_ids = Column(Text, nullable=True)  # JSON list of SourceChange ids
    stale_since = Column(DateTime(timezone=True), nullable=True)
    possibly_affected = Column(Boolean, nullable=False, default=False, server_default=false())
    affected_reason = Column(Text, nullable=True)

    project = relationship("Project", back_populates="claims")
    owner = relationship("User", foreign_keys=[owner_id])
    evidences = relationship("ClaimEvidence", back_populates="claim", cascade="all, delete-orphan")
    contradictions = relationship("Contradiction", secondary="contradiction_claims", back_populates="claims")
    review_events = relationship("ReviewEvent", back_populates="claim", cascade="all, delete-orphan")


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    claim_id = Column(String(64), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True)
    # Nullable: interview answers are authored by a person and have no source document.
    source_id = Column(String(64), ForeignKey("sources.id", ondelete="CASCADE"), nullable=True, index=True)
    chunk_id = Column(String(64), ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True, index=True)
    excerpt = Column(Text, nullable=False)
    author = Column(String(128), nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=True)
    # Phase 6 additions
    evidence_type = Column(String(32), nullable=False, default="document", server_default="document")  # document | interview_answer
    author_id = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    question_id = Column(String(64), nullable=True, index=True)

    claim = relationship("Claim", back_populates="evidences")
    source = relationship("Source", back_populates="evidences")
    chunk = relationship("Chunk", back_populates="evidences")


class Contradiction(Base):
    __tablename__ = "contradictions"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_code = Column(String(64), nullable=False)
    severity = Column(
        String(16),
        CheckConstraint("severity IN ('low', 'medium', 'high')", name="check_contradiction_severity"),
        nullable=False,
    )
    reason = Column(Text, nullable=False)
    suggested_action = Column(Text, nullable=False)
    status = Column(
        String(16),
        CheckConstraint("status IN ('open', 'resolved')", name="check_contradiction_status"),
        nullable=False,
        default="open",
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Phase 5 additions
    conflicting_source_ids = Column(Text, nullable=True)  # JSON list
    fingerprint = Column(String(64), nullable=True, index=True)
    clearance_level = Column(String(32), nullable=False, default="team", server_default="team")
    run_id = Column(String(64), nullable=True)
    resolved_by = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolution_note = Column(Text, nullable=True)

    project = relationship("Project", back_populates="contradictions")
    claims = relationship("Claim", secondary="contradiction_claims", back_populates="contradictions")


class ContradictionClaim(Base):
    __tablename__ = "contradiction_claims"

    contradiction_id = Column(String(64), ForeignKey("contradictions.id", ondelete="CASCADE"), primary_key=True, index=True)
    claim_id = Column(String(64), ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True, index=True)


class InterviewQuestion(Base):
    __tablename__ = "interview_questions"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_id = Column(String(64), ForeignKey("claims.id", ondelete="SET NULL"), nullable=True, index=True)
    module = Column(String(64), nullable=False)
    target_person_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    answered_at = Column(DateTime(timezone=True), nullable=True)
    # Phase 6 additions
    contradiction_id = Column(String(64), ForeignKey("contradictions.id", ondelete="SET NULL"), nullable=True, index=True)
    gap_type = Column(String(48), nullable=False, default="claim_gap", server_default="claim_gap")
    priority = Column(String(16), nullable=False, default="medium", server_default="medium")  # high | medium | low
    status = Column(String(16), nullable=False, default="open", server_default="open")  # open | answered | skipped
    skip_reason = Column(Text, nullable=True)
    skipped_by = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    skipped_at = Column(DateTime(timezone=True), nullable=True)
    answered_by = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    fingerprint = Column(String(64), nullable=True, index=True)
    clearance_level = Column(String(32), nullable=False, default="team", server_default="team")
    target_label = Column(String(128), nullable=True)  # person name, or 'unassigned'
    text_source = Column(String(16), nullable=False, default="template", server_default="template")  # template | llm
    facts_json = Column(Text, nullable=True)  # real values used to fill the template
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project = relationship("Project")
    claim = relationship("Claim")
    target_person = relationship("User", foreign_keys=[target_person_id])


class ReviewEvent(Base):
    __tablename__ = "review_events"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    claim_id = Column(String(64), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True)
    reviewer_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(
        String(16),
        CheckConstraint("action IN ('approve', 'edit', 'reject', 'flag', 'answer')", name="check_review_action"),
        nullable=False,
    )
    old_text = Column(Text, nullable=True)
    new_text = Column(Text, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    # Phase 6 additions
    note = Column(Text, nullable=True)
    resulting_review_status = Column(String(32), nullable=True)
    resulting_verification_status = Column(String(32), nullable=True)

    claim = relationship("Claim", back_populates="review_events")
    reviewer = relationship("User")


class Handover(Base):
    __tablename__ = "handovers"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    departing_user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    incoming_user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    period_start = Column(DateTime(timezone=True), nullable=True)
    period_end = Column(DateTime(timezone=True), nullable=True)
    status = Column(
        String(32),
        CheckConstraint(
            "status IN ('draft', 'in_review', 'approved', 'shared', 'acknowledged')",
            name="check_handover_status",
        ),
        nullable=False,
        default="draft",
    )
    approved_by = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Phase 7 additions
    readiness_score = Column(Float, nullable=True)
    readiness_json = Column(Text, nullable=True)
    snapshot_json = Column(Text, nullable=True)
    shared_by = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    shared_at = Column(DateTime(timezone=True), nullable=True)
    share_revoked_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    # Round 3 (Living Handover): version lineage. lineage_id is the id of v1 (null on legacy rows = own id).
    version_number = Column(Integer, nullable=False, default=1, server_default="1")
    parent_handover_id = Column(String(64), nullable=True, index=True)
    lineage_id = Column(String(64), nullable=True, index=True)

    project = relationship("Project", back_populates="handovers")
    departing_user = relationship("User", foreign_keys=[departing_user_id])
    incoming_user = relationship("User", foreign_keys=[incoming_user_id])
    sections = relationship("HandoverSection", back_populates="handover", cascade="all, delete-orphan", order_by="HandoverSection.ordinal")
    onboarding_progress = relationship("OnboardingProgress", back_populates="handover", cascade="all, delete-orphan")
    events = relationship("HandoverEvent", back_populates="handover", cascade="all, delete-orphan", order_by="HandoverEvent.timestamp")


class HandoverSection(Base):
    __tablename__ = "handover_sections"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    handover_id = Column(String(64), ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False, index=True)
    section_key = Column(String(64), nullable=False)
    content_json = Column(Text, nullable=False)
    review_status = Column(String(32), nullable=False, default="draft")
    # Phase 7 additions
    title = Column(String(255), nullable=True)
    ordinal = Column(Integer, nullable=False, default=0, server_default="0")
    approved_with_gaps = Column(Boolean, nullable=False, default=False, server_default="0")
    gap_note = Column(Text, nullable=True)
    reviewed_by = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)

    handover = relationship("Handover", back_populates="sections")


class HandoverEvent(Base):
    """Append-only history for handover generation, section edits/approvals, sharing, and acknowledgement."""

    __tablename__ = "handover_events"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    handover_id = Column(String(64), ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(48), nullable=False)
    section_key = Column(String(64), nullable=True)
    detail = Column(Text, nullable=True)
    old_content_json = Column(Text, nullable=True)
    new_content_json = Column(Text, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    handover = relationship("Handover", back_populates="events")
    actor = relationship("User")


class OnboardingProgress(Base):
    __tablename__ = "onboarding_progress"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    handover_id = Column(String(64), ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    section_key = Column(String(64), nullable=False)
    item_key = Column(String(128), nullable=True)  # e.g. plan item ID or null for section-level
    understood = Column(Boolean, nullable=False, default=False)
    note = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    handover = relationship("Handover", back_populates="onboarding_progress")
    user = relationship("User")


class Run(Base):
    """One analysis run. Stages are real rows written as the pipeline progresses."""

    __tablename__ = "runs"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(
        String(16),
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="check_run_status"),
        nullable=False,
        default="running",
    )
    started_by = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    llm_enabled = Column(Boolean, nullable=False, default=False)
    error_message = Column(Text, nullable=True)
    summary_json = Column(Text, nullable=True)  # counts, fallbacks, warnings
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    stages = relationship("RunStage", back_populates="run", cascade="all, delete-orphan", order_by="RunStage.ordinal")


class RunStage(Base):
    __tablename__ = "run_stages"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    run_id = Column(String(64), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    ordinal = Column(Integer, nullable=False)
    key = Column(String(32), nullable=False)
    label = Column(String(128), nullable=False)
    status = Column(
        String(16),
        CheckConstraint("status IN ('pending', 'running', 'done', 'failed')", name="check_run_stage_status"),
        nullable=False,
        default="pending",
    )
    count = Column(Integer, nullable=True)
    detail = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    run = relationship("Run", back_populates="stages")


class ModuleAlias(Base):
    """User renames/merges of modules; applied on every re-analysis."""

    __tablename__ = "module_aliases"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    alias = Column(String(128), nullable=False)
    target = Column(String(128), nullable=False)


class SourceVersion(Base):
    """One immutable version of a Source (Round 3, Living Handover)."""

    __tablename__ = "source_versions"
    __table_args__ = (UniqueConstraint("source_id", "version_number", name="uq_source_version_number"),)

    id = Column(String(64), primary_key=True, default=generate_uuid)
    source_id = Column(String(64), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    content_hash = Column(String(128), nullable=True)
    status = Column(String(16), nullable=False, default="pending", server_default="pending")  # pending|applied|failed
    origin = Column(String(32), nullable=True)  # initial | baseline | reupload | github_resync | manual_edit
    file_path = Column(String(512), nullable=True)
    uploaded_by = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    chunk_count = Column(Integer, nullable=False, default=0, server_default="0")
    added_count = Column(Integer, nullable=False, default=0, server_default="0")
    removed_count = Column(Integer, nullable=False, default=0, server_default="0")
    modified_count = Column(Integer, nullable=False, default=0, server_default="0")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    source = relationship("Source", back_populates="versions")
    snapshot_chunks = relationship(
        "SourceVersionChunk", back_populates="version", cascade="all, delete-orphan", order_by="SourceVersionChunk.ordinal"
    )


class SourceVersionChunk(Base):
    """Read-only chunk snapshot for a SourceVersion, kept so old versions stay readable for diffs."""

    __tablename__ = "source_version_chunks"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    version_id = Column(String(64), ForeignKey("source_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_id = Column(String(64), nullable=True, index=True)  # live Chunk id at snapshot time (may later be deleted)
    ordinal = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    locator = Column(String(255), nullable=True)
    author = Column(String(128), nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=True)

    version = relationship("SourceVersion", back_populates="snapshot_chunks")


class SourceChange(Base):
    """One deterministic chunk-level change between two versions of a source."""

    __tablename__ = "source_changes"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id = Column(String(64), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    from_version_id = Column(String(64), ForeignKey("source_versions.id", ondelete="CASCADE"), nullable=True, index=True)
    to_version_id = Column(String(64), ForeignKey("source_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    change_type = Column(String(16), nullable=False)  # added | removed | modified
    old_snapshot_chunk_id = Column(String(64), nullable=True)
    new_snapshot_chunk_id = Column(String(64), nullable=True)
    chunk_id = Column(String(64), nullable=True, index=True)  # live chunk id (old id for removed/modified)
    similarity = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    source = relationship("Source", back_populates="changes")


class Assessment(Base):
    """Readiness verification assessment generated from a handover's approved, incoming-visible claims."""

    __tablename__ = "assessments"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    handover_id = Column(String(64), ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="ready", server_default="ready")
    text_source = Column(String(16), nullable=False, default="template", server_default="template")  # template | llm
    created_by = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)

    questions = relationship(
        "AssessmentQuestion", back_populates="assessment", cascade="all, delete-orphan", order_by="AssessmentQuestion.ordinal"
    )
    attempts = relationship("AssessmentAttempt", back_populates="assessment", cascade="all, delete-orphan")


class AssessmentQuestion(Base):
    """One scenario question (MCQ or short-answer) grounded in approved handover claims."""

    __tablename__ = "assessment_questions"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    assessment_id = Column(String(64), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True)
    ordinal = Column(Integer, nullable=False, default=1)
    module = Column(String(64), nullable=False, index=True)
    question_type = Column(String(24), nullable=False)  # mcq | short_answer
    prompt = Column(Text, nullable=False)
    options_json = Column(Text, nullable=True)  # JSON list for MCQ
    correct_answer = Column(Text, nullable=False)  # NEVER sent to incoming role
    answer_key_json = Column(Text, nullable=True)  # JSON key terms/entities; NEVER sent to incoming role
    explanation = Column(Text, nullable=False)
    source_claim_ids_json = Column(Text, nullable=False)  # JSON list of Claim IDs
    evidence_refs_json = Column(Text, nullable=True)  # JSON list of source/locator/excerpt refs
    weight = Column(Float, nullable=False, default=1.0, server_default="1.0")
    clearance_level = Column(String(32), nullable=False, default="team", server_default="team")
    fingerprint = Column(String(64), nullable=False, index=True)
    text_source = Column(String(16), nullable=False, default="template", server_default="template")

    assessment = relationship("Assessment", back_populates="questions")


class AssessmentAttempt(Base):
    """One incoming member's baseline or reassessment attempt."""

    __tablename__ = "assessment_attempts"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    assessment_id = Column(String(64), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True)
    handover_id = Column(String(64), ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_number = Column(Integer, nullable=False, default=1)
    attempt_kind = Column(String(24), nullable=False, default="baseline")  # baseline | reassessment
    status = Column(String(24), nullable=False, default="in_progress")  # in_progress | submitted
    overall_score = Column(Float, nullable=True)
    correct_count = Column(Integer, nullable=False, default=0, server_default="0")
    total_questions = Column(Integer, nullable=False, default=0, server_default="0")
    needs_review_count = Column(Integer, nullable=False, default=0, server_default="0")
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    submitted_at = Column(DateTime(timezone=True), nullable=True)

    assessment = relationship("Assessment", back_populates="attempts")
    answers = relationship("AssessmentAnswer", back_populates="attempt", cascade="all, delete-orphan")
    area_scores = relationship("AreaScore", back_populates="attempt", cascade="all, delete-orphan")


class AssessmentAnswer(Base):
    """One answered question inside an attempt."""

    __tablename__ = "assessment_answers"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    attempt_id = Column(String(64), ForeignKey("assessment_attempts.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(String(64), ForeignKey("assessment_questions.id", ondelete="CASCADE"), nullable=False, index=True)
    answer_text = Column(Text, nullable=False)
    is_correct = Column(Boolean, nullable=True)
    score = Column(Float, nullable=False, default=0.0)
    confidence = Column(Float, nullable=False, default=1.0)
    needs_reviewer_check = Column(Boolean, nullable=False, default=False, server_default=false())
    heuristic_rationale = Column(Text, nullable=True)
    llm_suggested_score = Column(Float, nullable=True)
    answered_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    attempt = relationship("AssessmentAttempt", back_populates="answers")
    question = relationship("AssessmentQuestion")


class AreaScore(Base):
    """Per-module/area readiness score for an AssessmentAttempt."""

    __tablename__ = "area_scores"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    attempt_id = Column(String(64), ForeignKey("assessment_attempts.id", ondelete="CASCADE"), nullable=False, index=True)
    module = Column(String(64), nullable=False)
    score = Column(Float, nullable=False, default=0.0)
    correct_count = Column(Integer, nullable=False, default=0)
    question_count = Column(Integer, nullable=False, default=0)
    weight = Column(Float, nullable=False, default=1.0)
    weighted_points = Column(Float, nullable=False, default=0.0)
    max_weighted_points = Column(Float, nullable=False, default=0.0)
    status = Column(String(32), nullable=False, default="ready")  # ready | needs_more_handover
    missed_claim_ids_json = Column(Text, nullable=True)
    sent_to_interview_at = Column(DateTime(timezone=True), nullable=True)

    attempt = relationship("AssessmentAttempt", back_populates="area_scores")


class GraphNode(Base):
    """Continuity Graph node (Round 3, Improvement C)."""

    __tablename__ = "graph_nodes"
    __table_args__ = (UniqueConstraint("project_id", "node_key", name="uq_graph_node_project_key"),)

    id = Column(String(64), primary_key=True, default=generate_uuid)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    node_key = Column(String(255), nullable=False)
    node_type = Column(String(32), nullable=False, index=True)  # person | module | task | document | service
    label = Column(String(255), nullable=False)
    clearance_level = Column(String(32), nullable=False, default="team", server_default="team")
    review_status = Column(String(32), nullable=False, default="unreviewed", server_default="unreviewed")
    metadata_json = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class GraphEdge(Base):
    """Evidence-backed edge in the Continuity Graph (no evidence -> no edge)."""

    __tablename__ = "graph_edges"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_node_id = Column(String(64), ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    target_node_id = Column(String(64), ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    edge_type = Column(String(32), nullable=False, index=True)  # owns|contributed_to|depends_on|blocks|documents|decided
    inferred = Column(Boolean, nullable=False, default=False, server_default=false())
    claim_ids_json = Column(Text, nullable=False)
    evidence_refs_json = Column(Text, nullable=False)
    clearance_level = Column(String(32), nullable=False, default="team", server_default="team")
    review_status = Column(String(32), nullable=False, default="unreviewed", server_default="unreviewed")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CustodyItem(Base):
    """Account/service custody checklist item (NEVER stores secrets)."""

    __tablename__ = "custody_items"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(32), nullable=False, default="other")  # repository|hosting|database|domain|CI/CD|cloud account|third-party API|email/SaaS|other
    name = Column(String(255), nullable=False)
    owner_person = Column(String(255), nullable=True)
    backup_owner = Column(String(255), nullable=True)
    status = Column(String(24), nullable=False, default="unconfirmed", server_default="unconfirmed")  # confirmed|unconfirmed|unknown|transferred
    where_to_request_access = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    evidence_claim_ids_json = Column(Text, nullable=True)
    clearance_level = Column(String(32), nullable=False, default="team", server_default="team")
    suggested = Column(Boolean, nullable=False, default=False, server_default=false())
    confirmed_by = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)

    events = relationship("CustodyEvent", back_populates="item", cascade="all, delete-orphan", order_by="CustodyEvent.timestamp")


class CustodyEvent(Base):
    """Append-only audit history for CustodyItem changes."""

    __tablename__ = "custody_events"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    custody_item_id = Column(String(64), ForeignKey("custody_items.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(32), nullable=False)  # suggested|created|updated|confirmed|transferred
    detail_json = Column(Text, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    item = relationship("CustodyItem", back_populates="events")
    actor = relationship("User")



# Review history is append-only: updates are blocked at the ORM layer.
from sqlalchemy import event  # noqa: E402


@event.listens_for(ReviewEvent, "before_update")
def _review_events_are_append_only(mapper, connection, target):  # pragma: no cover - guard
    raise ValueError("ReviewEvent rows are append-only and cannot be modified.")


@event.listens_for(HandoverEvent, "before_update")
def _handover_events_are_append_only(mapper, connection, target):  # pragma: no cover - guard
    raise ValueError("HandoverEvent rows are append-only and cannot be modified.")


@event.listens_for(CustodyEvent, "before_update")
def _custody_events_are_append_only(mapper, connection, target):  # pragma: no cover - guard
    raise ValueError("CustodyEvent rows are append-only and cannot be modified.")

