"""Persist lesson variants and immediate-check origins/attempts."""

import sqlalchemy as sa

from alembic import op

revision = "0011_lessons_checks"
down_revision = "0010_learning_plans"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "lessons",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("concept_id", sa.Uuid(), nullable=False),
        sa.Column("depth", sa.String(32), nullable=False),
        sa.Column("content_blocks", sa.JSON(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["concept_id", "workspace_id"], ["concepts.id", "concepts.workspace_id"]
        ),
        sa.UniqueConstraint("id", "workspace_id", name="uq_lessons_workspace"),
        sa.UniqueConstraint("concept_id", "depth", name="uq_lessons_concept_depth"),
        sa.CheckConstraint(
            "depth IN ('standard','simpler','more_examples','deeper')", name="ck_lesson_depth"
        ),
    )
    op.create_index("ix_lessons_workspace_id", "lessons", ["workspace_id"])
    op.create_index("ix_lessons_concept_id", "lessons", ["concept_id"])
    op.create_table(
        "immediate_checks",
        sa.Column("assessment_id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["assessment_id", "workspace_id"], ["assessments.id", "assessments.workspace_id"]
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id", "workspace_id"], ["lessons.id", "lessons.workspace_id"]
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "assessment_id"], ["attempts.id", "attempts.assessment_id"]
        ),
    )
    op.create_index("ix_immediate_checks_lesson_id", "immediate_checks", ["lesson_id"])


def downgrade():
    op.drop_table("immediate_checks")
    op.drop_table("lessons")
