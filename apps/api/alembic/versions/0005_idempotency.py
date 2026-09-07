"""Add workspace-scoped idempotency records."""

import sqlalchemy as sa

from alembic import op

revision = "0005_idempotency"
down_revision = "0004_message_content_blocks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "request_records",
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), primary_key=True),
        sa.Column("idempotency_key", sa.String(255), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.CheckConstraint("state IN ('pending', 'completed')", name="ck_request_records_state"),
    )


def downgrade() -> None:
    op.drop_table("request_records")
