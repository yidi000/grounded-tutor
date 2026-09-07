"""Persist diagnostic groups and ordered assessment/attempt links."""

import sqlalchemy as sa

from alembic import op

revision = "0009_diagnostics"
down_revision = "0008_diagnostic_invitation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("uq_assessments_workspace", "assessments", ["id", "workspace_id"], unique=True)
    op.create_index("uq_attempts_assessment", "attempts", ["id", "assessment_id"], unique=True)
    op.create_table(
        "diagnostics",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("goal", sa.String(), nullable=False),
        sa.Column("background", sa.String(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("id", "workspace_id", name="uq_diagnostics_workspace"),
        sa.CheckConstraint("status IN ('active','completed')", name="ck_diagnostic_status"),
    )
    op.create_index("ix_diagnostics_workspace_id", "diagnostics", ["workspace_id"])
    op.create_table(
        "diagnostic_questions",
        sa.Column("assessment_id", sa.Uuid(), primary_key=True),
        sa.Column("diagnostic_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("concept_label", sa.String(120), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["diagnostic_id", "workspace_id"], ["diagnostics.id", "diagnostics.workspace_id"]
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id", "workspace_id"], ["assessments.id", "assessments.workspace_id"]
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "assessment_id"], ["attempts.id", "attempts.assessment_id"]
        ),
        sa.UniqueConstraint("diagnostic_id", "order", name="uq_diagnostic_question_order"),
        sa.CheckConstraint('"order" BETWEEN 1 AND 5', name="ck_diagnostic_question_order"),
    )
    op.create_index(
        "ix_diagnostic_questions_diagnostic_id", "diagnostic_questions", ["diagnostic_id"]
    )


def downgrade():
    op.drop_table("diagnostic_questions")
    op.drop_table("diagnostics")
    op.drop_index("uq_attempts_assessment", table_name="attempts")
    op.drop_index("uq_assessments_workspace", table_name="assessments")
