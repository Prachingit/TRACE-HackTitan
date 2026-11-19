"""round3_continuity_graph

ADDITIVE ONLY: creates graph_nodes, graph_edges, custody_items, custody_events.
Never touches existing tables.

Revision ID: g0b5e1f4c637
Revises: f9a4d0e3b526
Create Date: 2026-11-19 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'g0b5e1f4c637'
down_revision: Union[str, None] = 'f9a4d0e3b526'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'graph_nodes',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('project_id', sa.String(length=64), nullable=False),
        sa.Column('node_key', sa.String(length=255), nullable=False),
        sa.Column('node_type', sa.String(length=32), nullable=False),
        sa.Column('label', sa.String(length=255), nullable=False),
        sa.Column('clearance_level', sa.String(length=32), server_default='team', nullable=False),
        sa.Column('review_status', sa.String(length=32), server_default='unreviewed', nullable=False),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'node_key', name='uq_graph_node_project_key'),
    )
    op.create_index('ix_graph_nodes_project_id', 'graph_nodes', ['project_id'], unique=False)
    op.create_index('ix_graph_nodes_node_type', 'graph_nodes', ['node_type'], unique=False)

    op.create_table(
        'graph_edges',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('project_id', sa.String(length=64), nullable=False),
        sa.Column('source_node_id', sa.String(length=64), nullable=False),
        sa.Column('target_node_id', sa.String(length=64), nullable=False),
        sa.Column('edge_type', sa.String(length=32), nullable=False),
        sa.Column('inferred', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('claim_ids_json', sa.Text(), nullable=False),
        sa.Column('evidence_refs_json', sa.Text(), nullable=False),
        sa.Column('clearance_level', sa.String(length=32), server_default='team', nullable=False),
        sa.Column('review_status', sa.String(length=32), server_default='unreviewed', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_node_id'], ['graph_nodes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_node_id'], ['graph_nodes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_graph_edges_project_id', 'graph_edges', ['project_id'], unique=False)
    op.create_index('ix_graph_edges_source_node_id', 'graph_edges', ['source_node_id'], unique=False)
    op.create_index('ix_graph_edges_target_node_id', 'graph_edges', ['target_node_id'], unique=False)
    op.create_index('ix_graph_edges_edge_type', 'graph_edges', ['edge_type'], unique=False)

    op.create_table(
        'custody_items',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('project_id', sa.String(length=64), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('owner_person', sa.String(length=255), nullable=True),
        sa.Column('backup_owner', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=24), server_default='unconfirmed', nullable=False),
        sa.Column('where_to_request_access', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('evidence_claim_ids_json', sa.Text(), nullable=True),
        sa.Column('clearance_level', sa.String(length=32), server_default='team', nullable=False),
        sa.Column('suggested', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('confirmed_by', sa.String(length=64), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['confirmed_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_custody_items_project_id', 'custody_items', ['project_id'], unique=False)

    op.create_table(
        'custody_events',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('custody_item_id', sa.String(length=64), nullable=False),
        sa.Column('actor_id', sa.String(length=64), nullable=True),
        sa.Column('action', sa.String(length=32), nullable=False),
        sa.Column('detail_json', sa.Text(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['custody_item_id'], ['custody_items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_custody_events_custody_item_id', 'custody_events', ['custody_item_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_custody_events_custody_item_id', table_name='custody_events')
    op.drop_table('custody_events')
    op.drop_index('ix_custody_items_project_id', table_name='custody_items')
    op.drop_table('custody_items')
    op.drop_index('ix_graph_edges_edge_type', table_name='graph_edges')
    op.drop_index('ix_graph_edges_target_node_id', table_name='graph_edges')
    op.drop_index('ix_graph_edges_source_node_id', table_name='graph_edges')
    op.drop_index('ix_graph_edges_project_id', table_name='graph_edges')
    op.drop_table('graph_edges')
    op.drop_index('ix_graph_nodes_node_type', table_name='graph_nodes')
    op.drop_index('ix_graph_nodes_project_id', table_name='graph_nodes')
    op.drop_table('graph_nodes')
