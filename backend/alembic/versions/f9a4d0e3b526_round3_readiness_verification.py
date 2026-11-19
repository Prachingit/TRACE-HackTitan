"""round3_readiness_verification

ADDITIVE ONLY: creates assessments, assessment_questions, assessment_attempts,
assessment_answers, and area_scores. Never touches existing tables.

Revision ID: f9a4d0e3b526
Revises: e8f3c9d2a415
Create Date: 2026-11-19 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f9a4d0e3b526'
down_revision: Union[str, None] = 'e8f3c9d2a415'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'assessments',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('handover_id', sa.String(length=64), nullable=False),
        sa.Column('project_id', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=24), server_default='ready', nullable=False),
        sa.Column('text_source', sa.String(length=16), server_default='template', nullable=False),
        sa.Column('created_by', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['handover_id'], ['handovers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_assessments_handover_id', 'assessments', ['handover_id'], unique=False)
    op.create_index('ix_assessments_project_id', 'assessments', ['project_id'], unique=False)

    op.create_table(
        'assessment_questions',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('assessment_id', sa.String(length=64), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('module', sa.String(length=64), nullable=False),
        sa.Column('question_type', sa.String(length=24), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('options_json', sa.Text(), nullable=True),
        sa.Column('correct_answer', sa.Text(), nullable=False),
        sa.Column('answer_key_json', sa.Text(), nullable=True),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('source_claim_ids_json', sa.Text(), nullable=False),
        sa.Column('evidence_refs_json', sa.Text(), nullable=True),
        sa.Column('weight', sa.Float(), server_default='1.0', nullable=False),
        sa.Column('clearance_level', sa.String(length=32), server_default='team', nullable=False),
        sa.Column('fingerprint', sa.String(length=64), nullable=False),
        sa.Column('text_source', sa.String(length=16), server_default='template', nullable=False),
        sa.ForeignKeyConstraint(['assessment_id'], ['assessments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_assessment_questions_assessment_id', 'assessment_questions', ['assessment_id'], unique=False)
    op.create_index('ix_assessment_questions_module', 'assessment_questions', ['module'], unique=False)
    op.create_index('ix_assessment_questions_fingerprint', 'assessment_questions', ['fingerprint'], unique=False)

    op.create_table(
        'assessment_attempts',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('assessment_id', sa.String(length=64), nullable=False),
        sa.Column('handover_id', sa.String(length=64), nullable=False),
        sa.Column('project_id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('attempt_number', sa.Integer(), nullable=False),
        sa.Column('attempt_kind', sa.String(length=24), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('overall_score', sa.Float(), nullable=True),
        sa.Column('correct_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_questions', sa.Integer(), server_default='0', nullable=False),
        sa.Column('needs_review_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['assessment_id'], ['assessments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['handover_id'], ['handovers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_assessment_attempts_assessment_id', 'assessment_attempts', ['assessment_id'], unique=False)
    op.create_index('ix_assessment_attempts_handover_id', 'assessment_attempts', ['handover_id'], unique=False)
    op.create_index('ix_assessment_attempts_project_id', 'assessment_attempts', ['project_id'], unique=False)
    op.create_index('ix_assessment_attempts_user_id', 'assessment_attempts', ['user_id'], unique=False)

    op.create_table(
        'assessment_answers',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('attempt_id', sa.String(length=64), nullable=False),
        sa.Column('question_id', sa.String(length=64), nullable=False),
        sa.Column('answer_text', sa.Text(), nullable=False),
        sa.Column('is_correct', sa.Boolean(), nullable=True),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('needs_reviewer_check', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('heuristic_rationale', sa.Text(), nullable=True),
        sa.Column('llm_suggested_score', sa.Float(), nullable=True),
        sa.Column('answered_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['attempt_id'], ['assessment_attempts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['question_id'], ['assessment_questions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_assessment_answers_attempt_id', 'assessment_answers', ['attempt_id'], unique=False)
    op.create_index('ix_assessment_answers_question_id', 'assessment_answers', ['question_id'], unique=False)

    op.create_table(
        'area_scores',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('attempt_id', sa.String(length=64), nullable=False),
        sa.Column('module', sa.String(length=64), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('correct_count', sa.Integer(), nullable=False),
        sa.Column('question_count', sa.Integer(), nullable=False),
        sa.Column('weight', sa.Float(), nullable=False),
        sa.Column('weighted_points', sa.Float(), nullable=False),
        sa.Column('max_weighted_points', sa.Float(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('missed_claim_ids_json', sa.Text(), nullable=True),
        sa.Column('sent_to_interview_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['attempt_id'], ['assessment_attempts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_area_scores_attempt_id', 'area_scores', ['attempt_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_area_scores_attempt_id', table_name='area_scores')
    op.drop_table('area_scores')
    op.drop_index('ix_assessment_answers_question_id', table_name='assessment_answers')
    op.drop_index('ix_assessment_answers_attempt_id', table_name='assessment_answers')
    op.drop_table('assessment_answers')
    op.drop_index('ix_assessment_attempts_user_id', table_name='assessment_attempts')
    op.drop_index('ix_assessment_attempts_project_id', table_name='assessment_attempts')
    op.drop_index('ix_assessment_attempts_handover_id', table_name='assessment_attempts')
    op.drop_index('ix_assessment_attempts_assessment_id', table_name='assessment_attempts')
    op.drop_table('assessment_attempts')
    op.drop_index('ix_assessment_questions_fingerprint', table_name='assessment_questions')
    op.drop_index('ix_assessment_questions_module', table_name='assessment_questions')
    op.drop_index('ix_assessment_questions_assessment_id', table_name='assessment_questions')
    op.drop_table('assessment_questions')
    op.drop_index('ix_assessments_project_id', table_name='assessments')
    op.drop_index('ix_assessments_handover_id', table_name='assessments')
    op.drop_table('assessments')
