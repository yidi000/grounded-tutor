"""Persist plan provenance and immediate-check kinds without rebuilding old plans."""

import sqlalchemy as sa

from alembic import op

revision = "0010_learning_plans"
down_revision = "0009_diagnostics"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "concepts",
        sa.Column(
            "check_kind",
            sa.String(32),
            sa.CheckConstraint(
                "check_kind IN ('single_choice','structured_short')", name="ck_concept_check_kind"
            ),
            nullable=False,
            server_default="single_choice",
        ),
    )
    op.create_table(
        "plan_origins",
        sa.Column("plan_id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("diagnostic_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id", "workspace_id"], ["learning_plans.id", "learning_plans.workspace_id"]
        ),
        sa.ForeignKeyConstraint(
            ["diagnostic_id", "workspace_id"], ["diagnostics.id", "diagnostics.workspace_id"]
        ),
    )
    op.create_index("ix_plan_origins_diagnostic_id", "plan_origins", ["diagnostic_id"])


def downgrade():
    op.drop_table("plan_origins")
    # SQLite supports native DROP COLUMN; rebuilding Concepts would disturb its FK children.
    op.drop_column("concepts", "check_kind")
