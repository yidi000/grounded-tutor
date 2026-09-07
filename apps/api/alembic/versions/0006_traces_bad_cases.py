"""Add replayable execution traces and their review cases."""

import sqlalchemy as sa

from alembic import op

revision = "0006_traces_bad_cases"
down_revision = "0005_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_traces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.String(255), nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("route", sa.String(32), nullable=False),
        sa.Column("retrieval_json", sa.JSON(), nullable=False),
        sa.Column("generation_json", sa.JSON(), nullable=False),
        sa.Column("validation_json", sa.JSON(), nullable=False),
        sa.Column("timing_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )
    op.create_index("ix_execution_traces_workspace_id", "execution_traces", ["workspace_id"])
    op.create_table(
        "bad_cases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "trace_id",
            sa.Uuid(),
            sa.ForeignKey("execution_traces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("note", sa.String(), nullable=False, server_default=""),
        sa.Column("resolution", sa.String(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )
    op.create_index("ix_bad_cases_trace_id", "bad_cases", ["trace_id"])


def downgrade() -> None:
    op.drop_table("bad_cases")
    op.drop_table("execution_traces")
