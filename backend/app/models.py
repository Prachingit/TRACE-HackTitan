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

    project = relationship("Project", back_populates="handovers")
    departing_user = relationship("User", foreign_keys=[departing_user_id])
    incoming_user = relationship("User", foreign_keys=[incoming_user_id])
    sections = relationship("HandoverSection", back_populates="handover", cascade="all, delete-orphan")
    onboarding_progress = relationship("OnboardingProgress", back_populates="handover", cascade="all, delete-orphan")


class HandoverSection(Base):
    __tablename__ = "handover_sections"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    handover_id = Column(String(64), ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False, index=True)
    section_key = Column(String(64), nullable=False)
    content_json = Column(Text, nullable=False)
    review_status = Column(String(32), nullable=False, default="unreviewed")

    handover = relationship("Handover", back_populates="sections")


class OnboardingProgress(Base):
    __tablename__ = "onboarding_progress"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    handover_id = Column(String(64), ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    section_key = Column(String(64), nullable=False)
    understood = Column(Boolean, nullable=False, default=False)
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



# Review history is append-only: updates are blocked at the ORM layer.
from sqlalchemy import event  # noqa: E402


@event.listens_for(ReviewEvent, "before_update")
def _review_events_are_append_only(mapper, connection, target):  # pragma: no cover - guard
    raise ValueError("ReviewEvent rows are append-only and cannot be modified.")

