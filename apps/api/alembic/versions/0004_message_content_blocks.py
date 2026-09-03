"""Add structured content blocks to messages.

Revision ID: 0004_message_content_blocks
Revises: 0003_workspace_model_choices
Create Date: 2026-09-03 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004_message_content_blocks"
down_revision = "0003_workspace_model_choices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.add_column(sa.Column("content_blocks", sa.JSON(), nullable=True))
        batch_op.alter_column(
            "idempotency_key",
            existing_type=sa.String(length=255),
            nullable=True,
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE messages SET idempotency_key = "
            "'legacy-' || CAST(id AS VARCHAR) WHERE idempotency_key IS NULL"
        )
    )
    with op.batch_alter_table("messages") as batch_op:
        batch_op.alter_column(
            "idempotency_key",
            existing_type=sa.String(length=255),
            nullable=False,
        )
        batch_op.drop_column("content_blocks")
