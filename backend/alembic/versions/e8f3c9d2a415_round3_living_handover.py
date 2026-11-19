"""round3_living_handover

ADDITIVE ONLY: new tables source_versions, source_version_chunks, source_changes; new nullable/defaulted
columns on claims (stale flags) and handovers (version lineage). No existing table is dropped or rebuilt.

Revision ID: e8f3c9d2a415
Revises: d7e2b8a1c304
Create Date: 2026-11-19 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e8f3c9d2a415'
down_revision: Union[str, None] = 'd7e2b8a1c304'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'source_versions',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('source_id', sa.String(length=64), nullable=False),
        sa.Column('project_id', sa.String(length=64), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('content_hash', sa.String(length=128), nullable=True),
        sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
        sa.Column('origin', sa.String(length=32), nullable=True),
        sa.Column('file_path', sa.String(length=512), nullable=True),
        sa.Column('uploaded_by', sa.String(length=64), nullable=True),
        sa.Column('chunk_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('added_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('removed_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('modified_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_id', 'version_number', name='uq_source_version_number'),
    )
    op.create_index('ix_source_versions_source_id', 'source_versions', ['source_id'], unique=False)
    op.create_index('ix_source_versions_project_id', 'source_versions', ['project_id'], unique=False)

    op.create_table(
        'source_version_chunks',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('version_id', sa.String(length=64), nullable=False),
        sa.Column('chunk_id', sa.String(length=64), nullable=True),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('locator', sa.String(length=255), nullable=True),
        sa.Column('author', sa.String(length=128), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['version_id'], ['source_versions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_source_version_chunks_version_id', 'source_version_chunks', ['version_id'], unique=False)
    op.create_index('ix_source_version_chunks_chunk_id', 'source_version_chunks', ['chunk_id'], unique=False)

    op.create_table(
        'source_changes',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('project_id', sa.String(length=64), nullable=False),
        sa.Column('source_id', sa.String(length=64), nullable=False),
        sa.Column('from_version_id', sa.String(length=64), nullable=True),
        sa.Column('to_version_id', sa.String(length=64), nullable=False),
        sa.Column('change_type', sa.String(length=16), nullable=False),
        sa.Column('old_snapshot_chunk_id', sa.String(length=64), nullable=True),
        sa.Column('new_snapshot_chunk_id', sa.String(length=64), nullable=True),
        sa.Column('chunk_id', sa.String(length=64), nullable=True),
        sa.Column('similarity', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['from_version_id'], ['source_versions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['to_version_id'], ['source_versions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_source_changes_project_id', 'source_changes', ['project_id'], unique=False)
    op.create_index('ix_source_changes_source_id', 'source_changes', ['source_id'], unique=False)
    op.create_index('ix_source_changes_from_version_id', 'source_changes', ['from_version_id'], unique=False)
    op.create_index('ix_source_changes_to_version_id', 'source_changes', ['to_version_id'], unique=False)
    op.create_index('ix_source_changes_chunk_id', 'source_changes', ['chunk_id'], unique=False)

    # Plain ADD COLUMN on existing tables (no table rebuild on SQLite, no constraint changes on Postgres).
    op.add_column('claims', sa.Column('is_stale', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('claims', sa.Column('stale_reason', sa.Text(), nullable=True))
    op.add_column('claims', sa.Column('stale_change_ids', sa.Text(), nullable=True))
    op.add_column('claims', sa.Column('stale_since', sa.DateTime(timezone=True), nullable=True))
    op.add_column('claims', sa.Column('possibly_affected', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('claims', sa.Column('affected_reason', sa.Text(), nullable=True))

    op.add_column('handovers', sa.Column('version_number', sa.Integer(), server_default='1', nullable=False))
    op.add_column('handovers', sa.Column('parent_handover_id', sa.String(length=64), nullable=True))
    op.add_column('handovers', sa.Column('lineage_id', sa.String(length=64), nullable=True))
    op.create_index('ix_handovers_parent_handover_id', 'handovers', ['parent_handover_id'], unique=False)
    op.create_index('ix_handovers_lineage_id', 'handovers', ['lineage_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_handovers_lineage_id', table_name='handovers')
    op.drop_index('ix_handovers_parent_handover_id', table_name='handovers')
    with op.batch_alter_table('handovers', schema=None) as batch_op:
        batch_op.drop_column('lineage_id')
        batch_op.drop_column('parent_handover_id')
        batch_op.drop_column('version_number')
    with op.batch_alter_table('claims', schema=None) as batch_op:
        for col in ('affected_reason', 'possibly_affected', 'stale_since', 'stale_change_ids', 'stale_reason', 'is_stale'):
            batch_op.drop_column(col)
    op.drop_table('source_changes')
    op.drop_table('source_version_chunks')
    op.drop_table('source_versions')
