"""Add source review lifecycle metadata.

Revision ID: 0002_source_lifecycle
Revises: 0001_workspace_sources
Create Date: 2026-09-03 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002_source_lifecycle"
down_revision = "0001_workspace_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("lineage_id", sa.Uuid(), nullable=True))
    op.add_column("sources", sa.Column("replaces_source_id", sa.Uuid(), nullable=True))
    op.add_column("sources", sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(sa.text("UPDATE sources SET lineage_id = id"))
    with op.batch_alter_table("sources") as batch_op:
        batch_op.alter_column("lineage_id", existing_type=sa.Uuid(), nullable=False)
        batch_op.create_foreign_key(
            "fk_sources_replaces_source_id_sources",
            "sources",
            ["replaces_source_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index(op.f("ix_sources_lineage_id"), "sources", ["lineage_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sources_lineage_id"), table_name="sources")
    with op.batch_alter_table("sources") as batch_op:
        batch_op.drop_constraint("fk_sources_replaces_source_id_sources", type_="foreignkey")
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("superseded_at")
        batch_op.drop_column("replaces_source_id")
        batch_op.drop_column("lineage_id")
