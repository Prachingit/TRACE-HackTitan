"""phase7_clearance_handover

Extends claims, handovers, handover_sections, onboarding_progress and adds handover_events.

Revision ID: d7e2b8a1c304
Revises: c6d1a7f9b210
Create Date: 2026-11-13 11:02:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd7e2b8a1c304'
down_revision: Union[str, None] = 'c6d1a7f9b210'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('claims', schema=None) as batch_op:
        batch_op.add_column(sa.Column('clearance_override_reason', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('clearance_overridden_by', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('clearance_overridden_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            'fk_claims_clearance_overridden_by_users', 'users', ['clearance_overridden_by'], ['id'], ondelete='SET NULL'
        )

    with op.batch_alter_table('handovers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('readiness_score', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('readiness_json', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('snapshot_json', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('shared_by', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('shared_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('share_revoked_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('acknowledged_by', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key('fk_handovers_shared_by_users', 'users', ['shared_by'], ['id'], ondelete='SET NULL')
        batch_op.create_foreign_key('fk_handovers_acknowledged_by_users', 'users', ['acknowledged_by'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('handover_sections', schema=None) as batch_op:
        batch_op.add_column(sa.Column('title', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('ordinal', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('approved_with_gaps', sa.Boolean(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('gap_note', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('reviewed_by', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key('fk_handover_sections_reviewed_by_users', 'users', ['reviewed_by'], ['id'], ondelete='SET NULL')

    op.create_table(
        'handover_events',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('handover_id', sa.String(length=64), nullable=False),
        sa.Column('actor_id', sa.String(length=64), nullable=True),
        sa.Column('action', sa.String(length=48), nullable=False),
        sa.Column('section_key', sa.String(length=64), nullable=True),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('old_content_json', sa.Text(), nullable=True),
        sa.Column('new_content_json', sa.Text(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['handover_id'], ['handovers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('handover_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_handover_events_handover_id'), ['handover_id'], unique=False)

    with op.batch_alter_table('onboarding_progress', schema=None) as batch_op:
        batch_op.add_column(sa.Column('item_key', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('note', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('onboarding_progress', schema=None) as batch_op:
        batch_op.drop_column('note')
        batch_op.drop_column('item_key')

    with op.batch_alter_table('handover_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_handover_events_handover_id'))
    op.drop_table('handover_events')

    with op.batch_alter_table('handover_sections', schema=None) as batch_op:
        batch_op.drop_constraint('fk_handover_sections_reviewed_by_users', type_='foreignkey')
        for col in ('updated_at', 'reviewed_at', 'reviewed_by', 'gap_note', 'approved_with_gaps', 'ordinal', 'title'):
            batch_op.drop_column(col)

    with op.batch_alter_table('handovers', schema=None) as batch_op:
        batch_op.drop_constraint('fk_handovers_acknowledged_by_users', type_='foreignkey')
        batch_op.drop_constraint('fk_handovers_shared_by_users', type_='foreignkey')
        for col in (
            'updated_at', 'acknowledged_at', 'acknowledged_by', 'share_revoked_at',
            'shared_at', 'shared_by', 'snapshot_json', 'readiness_json', 'readiness_score',
        ):
            batch_op.drop_column(col)

    with op.batch_alter_table('claims', schema=None) as batch_op:
        batch_op.drop_constraint('fk_claims_clearance_overridden_by_users', type_='foreignkey')
        for col in ('clearance_overridden_at', 'clearance_overridden_by', 'clearance_override_reason'):
            batch_op.drop_column(col)
