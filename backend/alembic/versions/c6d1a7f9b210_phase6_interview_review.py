"""phase6_interview_review

Extends existing tables for the exit interview and review workbench:
- claims: needs_review status, reviewer identity/timestamp/note, original text
- claim_evidence: interview answers (nullable source_id, evidence_type, author)
- review_events: note + resulting statuses, 'answer' action
- interview_questions: gap metadata, status, dedupe fingerprint, clearance, nullable target person

Revision ID: c6d1a7f9b210
Revises: eb78411be374
Create Date: 2026-11-13 10:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c6d1a7f9b210'
down_revision: Union[str, None] = 'eb78411be374'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _claim_checks(review_values: str):
    return (
        sa.CheckConstraint("claim_type IN ('task_status', 'decision', 'ownership', 'blocker', 'dependency', 'contribution', 'testing', 'doc_gap')", name='check_claim_type'),
        sa.CheckConstraint("verification_status IN ('verified', 'inferred', 'conflicting', 'missing')", name='check_claim_verification_status'),
        sa.CheckConstraint(f"review_status IN ({review_values})", name='check_claim_review_status'),
        sa.CheckConstraint("clearance_level IN ('public', 'team', 'restricted')", name='check_claim_clearance'),
    )


def upgrade() -> None:
    # SQLite batch rebuilds drop reflected CHECK constraints, so they are re-declared explicitly.
    with op.batch_alter_table(
        'claims', schema=None, recreate='always',
        table_args=_claim_checks("'unreviewed', 'needs_review', 'approved', 'edited', 'rejected'"),
    ) as batch_op:
        batch_op.add_column(sa.Column('original_text', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('reviewed_by', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('review_note', sa.Text(), nullable=True))
        batch_op.create_foreign_key('fk_claims_reviewed_by_users', 'users', ['reviewed_by'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('claim_evidence', schema=None) as batch_op:
        batch_op.alter_column('source_id', existing_type=sa.String(length=64), nullable=True)
        batch_op.add_column(sa.Column('evidence_type', sa.String(length=32), server_default='document', nullable=False))
        batch_op.add_column(sa.Column('author_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('question_id', sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f('ix_claim_evidence_question_id'), ['question_id'], unique=False)
        batch_op.create_foreign_key('fk_claim_evidence_author_id_users', 'users', ['author_id'], ['id'], ondelete='SET NULL')

    review_checks = (
        sa.CheckConstraint("action IN ('approve', 'edit', 'reject', 'flag', 'answer')", name='check_review_action'),
    )
    with op.batch_alter_table('review_events', schema=None, recreate='always', table_args=review_checks) as batch_op:
        batch_op.add_column(sa.Column('note', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('resulting_review_status', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('resulting_verification_status', sa.String(length=32), nullable=True))

    with op.batch_alter_table('interview_questions', schema=None) as batch_op:
        batch_op.alter_column('target_person_id', existing_type=sa.String(length=64), nullable=True)
        batch_op.add_column(sa.Column('contradiction_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('gap_type', sa.String(length=48), server_default='claim_gap', nullable=False))
        batch_op.add_column(sa.Column('priority', sa.String(length=16), server_default='medium', nullable=False))
        batch_op.add_column(sa.Column('status', sa.String(length=16), server_default='open', nullable=False))
        batch_op.add_column(sa.Column('skip_reason', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('skipped_by', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('skipped_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('answered_by', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('fingerprint', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('clearance_level', sa.String(length=32), server_default='team', nullable=False))
        batch_op.add_column(sa.Column('target_label', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('text_source', sa.String(length=16), server_default='template', nullable=False))
        batch_op.add_column(sa.Column('facts_json', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False))
        batch_op.create_index(batch_op.f('ix_interview_questions_contradiction_id'), ['contradiction_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_interview_questions_fingerprint'), ['fingerprint'], unique=False)
        batch_op.create_foreign_key('fk_interview_questions_contradiction_id', 'contradictions', ['contradiction_id'], ['id'], ondelete='SET NULL')
        batch_op.create_foreign_key('fk_interview_questions_skipped_by_users', 'users', ['skipped_by'], ['id'], ondelete='SET NULL')
        batch_op.create_foreign_key('fk_interview_questions_answered_by_users', 'users', ['answered_by'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.execute("DELETE FROM interview_questions WHERE target_person_id IS NULL")
    with op.batch_alter_table('interview_questions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_interview_questions_answered_by_users', type_='foreignkey')
        batch_op.drop_constraint('fk_interview_questions_skipped_by_users', type_='foreignkey')
        batch_op.drop_constraint('fk_interview_questions_contradiction_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_interview_questions_fingerprint'))
        batch_op.drop_index(batch_op.f('ix_interview_questions_contradiction_id'))
        for col in (
            'created_at', 'facts_json', 'text_source', 'target_label', 'clearance_level', 'fingerprint',
            'answered_by', 'skipped_at', 'skipped_by', 'skip_reason', 'status', 'priority', 'gap_type',
            'contradiction_id',
        ):
            batch_op.drop_column(col)
        batch_op.alter_column('target_person_id', existing_type=sa.String(length=64), nullable=False)

    op.execute("DELETE FROM review_events WHERE action = 'answer'")
    review_checks = (
        sa.CheckConstraint("action IN ('approve', 'edit', 'reject', 'flag')", name='check_review_action'),
    )
    with op.batch_alter_table('review_events', schema=None, recreate='always', table_args=review_checks) as batch_op:
        batch_op.drop_column('resulting_verification_status')
        batch_op.drop_column('resulting_review_status')
        batch_op.drop_column('note')

    op.execute("DELETE FROM claim_evidence WHERE source_id IS NULL")
    with op.batch_alter_table('claim_evidence', schema=None) as batch_op:
        batch_op.drop_constraint('fk_claim_evidence_author_id_users', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_claim_evidence_question_id'))
        batch_op.drop_column('question_id')
        batch_op.drop_column('author_id')
        batch_op.drop_column('evidence_type')
        batch_op.alter_column('source_id', existing_type=sa.String(length=64), nullable=False)

    op.execute("UPDATE claims SET review_status = 'unreviewed' WHERE review_status = 'needs_review'")
    with op.batch_alter_table(
        'claims', schema=None, recreate='always',
        table_args=_claim_checks("'unreviewed', 'approved', 'edited', 'rejected'"),
    ) as batch_op:
        batch_op.drop_constraint('fk_claims_reviewed_by_users', type_='foreignkey')
        batch_op.drop_column('review_note')
        batch_op.drop_column('reviewed_at')
        batch_op.drop_column('reviewed_by')
        batch_op.drop_column('original_text')
