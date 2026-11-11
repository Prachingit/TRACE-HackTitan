"""SQLAlchemy 2.0 Database Models for TRACE.

DESIGN RULE (Enforced in Phase 7):
A claim's access_label must equal the STRICTEST label among its evidence sources.
Ordering: public < internal < restricted.
- If any evidence source is 'restricted', the claim's access_label must be 'restricted'.
- If no evidence is 'restricted' but at least one is 'internal', the claim's access_label must be 'internal'.
- A claim can only be 'public' if all its evidence sources are 'public'.
The column exists now to support multi-role clearance views from Phase 1 onward.
"""

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
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


class Project(Base):
    __tablename__ = "projects"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    sources = relationship("Source", back_populates="project", cascade="all, delete-orphan")
    claims = relationship("Claim", back_populates="project", cascade="all, delete-orphan")
    handovers = relationship("Handover", back_populates="project", cascade="all, delete-orphan")


class Role(Base):
    __tablename__ = "roles"

    id = Column(String(64), primary_key=True)  # e.g. team_lead, incoming_developer, external_reviewer
    name = Column(String(255), nullable=False)
    clearance = Column(
        String(32),
        CheckConstraint("clearance IN ('public', 'internal', 'restricted')", name="check_role_clearance"),
        nullable=False,
    )


class Source(Base):
    __tablename__ = "sources"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(
        String(32),
        CheckConstraint("type IN ('git', 'pr', 'task', 'note', 'chat', 'doc')", name="check_source_type"),
        nullable=False,
    )
    title = Column(String(255), nullable=False)
    origin_ref = Column(String(500), nullable=False)
    access_label = Column(
        String(32),
        CheckConstraint("access_label IN ('public', 'internal', 'restricted')", name="check_source_access_label"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project = relationship("Project", back_populates="sources")
    activity_items = relationship("ActivityItem", back_populates="source", cascade="all, delete-orphan")
    evidences = relationship("ClaimEvidence", back_populates="source", cascade="all, delete-orphan")


class ActivityItem(Base):
    """Filled in Phase 3; table and columns created in Phase 1."""
    __tablename__ = "activity_items"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    source_id = Column(String(64), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(64), nullable=False)
    author = Column(String(128), nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=True)
    text = Column(Text, nullable=False)
    ref = Column(String(500), nullable=True)
    access_label = Column(
        String(32),
        CheckConstraint("access_label IN ('public', 'internal', 'restricted')", name="check_activity_access_label"),
        nullable=False,
        index=True,
    )

    source = relationship("Source", back_populates="activity_items")
    evidences = relationship("ClaimEvidence", back_populates="activity_item")


class Claim(Base):
    __tablename__ = "claims"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(
        String(32),
        CheckConstraint(
            "type IN ('state', 'decision', 'task', 'blocker', 'dependency', 'ownership', 'contradiction', 'open_loop', 'gap')",
            name="check_claim_type",
        ),
        nullable=False,
    )
    statement = Column(Text, nullable=False)
    status = Column(
        String(32),
        CheckConstraint("status IN ('verified', 'inferred', 'conflicting', 'missing')", name="check_claim_status"),
        nullable=False,
        index=True,
    )
    confidence_note = Column(Text, nullable=True)
    owner = Column(String(128), nullable=True)
    access_label = Column(
        String(32),
        CheckConstraint("access_label IN ('public', 'internal', 'restricted')", name="check_claim_access_label"),
        nullable=False,
        index=True,
    )
    review_state = Column(
        String(32),
        CheckConstraint("review_state IN ('pending', 'accepted', 'edited', 'rejected')", name="check_claim_review_state"),
        nullable=False,
        default="pending",
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project = relationship("Project", back_populates="claims")
    evidence = relationship("ClaimEvidence", back_populates="claim", cascade="all, delete-orphan")
    gap_questions = relationship("GapQuestion", back_populates="claim", cascade="all, delete-orphan")
    reviews = relationship("Review", back_populates="claim", cascade="all, delete-orphan")
    plan_steps = relationship("PlanStep", secondary="plan_step_claims", back_populates="claims")


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    claim_id = Column(String(64), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True)
    activity_item_id = Column(String(64), ForeignKey("activity_items.id", ondelete="SET NULL"), nullable=True, index=True)
    source_id = Column(String(64), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    quote = Column(
        String(200),
        CheckConstraint("length(quote) <= 200", name="check_quote_max_length"),
        nullable=False,
    )
    locator = Column(String(255), nullable=False)

    claim = relationship("Claim", back_populates="evidence")
    activity_item = relationship("ActivityItem", back_populates="evidences")
    source = relationship("Source", back_populates="evidences")


class GapQuestion(Base):
    __tablename__ = "gap_questions"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    claim_id = Column(String(64), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    answered_by = Column(String(128), nullable=True)
    answered_at = Column(DateTime(timezone=True), nullable=True)

    claim = relationship("Claim", back_populates="gap_questions")


class Review(Base):
    __tablename__ = "reviews"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    claim_id = Column(String(64), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(
        String(32),
        CheckConstraint("action IN ('accept', 'edit', 'reject')", name="check_review_action"),
        nullable=False,
    )
    edited_statement = Column(Text, nullable=True)
    reviewer = Column(String(128), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    claim = relationship("Claim", back_populates="reviews")


class Handover(Base):
    __tablename__ = "handovers"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    status = Column(
        String(32),
        CheckConstraint("status IN ('draft', 'approved')", name="check_handover_status"),
        nullable=False,
        default="draft",
    )
    approved_by = Column(String(128), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by = Column(String(128), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project = relationship("Project", back_populates="handovers")
    plan_steps = relationship("PlanStep", back_populates="handover", cascade="all, delete-orphan", order_by="PlanStep.rank")


class PlanStepClaim(Base):
    __tablename__ = "plan_step_claims"

    plan_step_id = Column(String(64), ForeignKey("plan_steps.id", ondelete="CASCADE"), primary_key=True, index=True)
    claim_id = Column(String(64), ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True, index=True)


class PlanStep(Base):
    __tablename__ = "plan_steps"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    handover_id = Column(String(64), ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False, index=True)
    rank = Column(Integer, nullable=False)
    action = Column(Text, nullable=False)
    reason = Column(Text, nullable=False)

    handover = relationship("Handover", back_populates="plan_steps")
    claims = relationship("Claim", secondary="plan_step_claims", back_populates="plan_steps")
