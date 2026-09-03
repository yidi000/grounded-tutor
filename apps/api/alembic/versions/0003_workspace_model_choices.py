"""Add immutable Workspace model choices.

Revision ID: 0003_workspace_model_choices
Revises: 0002_source_lifecycle
Create Date: 2026-09-03 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_workspace_model_choices"
down_revision = "0002_source_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("vector_model", sa.String(255), nullable=True))
    op.add_column("workspaces", sa.Column("agent_model", sa.String(255), nullable=True))
    op.add_column("workspaces", sa.Column("vlm_model", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("workspaces", "vlm_model")
    op.drop_column("workspaces", "agent_model")
    op.drop_column("workspaces", "vector_model")
