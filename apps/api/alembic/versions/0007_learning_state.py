"""Add workspace-scoped learning records and resumable activity state."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0007_learning_state"
down_revision = "0006_traces_bad_cases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learner_profiles",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("inferred_fields", sa.JSON(), nullable=False),
        sa.Column("confirmed_fields", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("workspace_id"),
    )
    op.create_table(
        "learning_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("goal", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="not_started", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('not_started','active','completed','superseded')", name="ck_plan_status"
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workspace_id", name="uq_learning_plans_id_workspace"),
    )
    op.create_index(
        op.f("ix_learning_plans_workspace_id"), "learning_plans", ["workspace_id"], unique=False
    )
    op.create_table(
        "concepts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("objective", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="not_started", nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "status IN ('not_started','active','completed','needs_review','not_assessed')",
            name="ck_concept_status",
        ),
        sa.CheckConstraint('"order" > 0', name="ck_concept_order_positive"),
        sa.ForeignKeyConstraint(
            ["plan_id", "workspace_id"],
            ["learning_plans.id", "learning_plans.workspace_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workspace_id", name="uq_concepts_id_workspace"),
        sa.UniqueConstraint("plan_id", "order", name="uq_concepts_plan_order"),
    )
    op.create_index(op.f("ix_concepts_plan_id"), "concepts", ["plan_id"], unique=False)
    op.create_table(
        "activity_states",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("active_mode", sa.String(length=16), server_default="ASK", nullable=False),
        sa.Column("active_concept_id", sa.Uuid(), nullable=True),
        sa.Column("suspended_activity", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("return_checkpoint", sa.String(), nullable=True),
        sa.Column("nudge_cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "active_mode IN ('ASK','PLAN','LEARN','CHECK')", name="ck_activity_mode"
        ),
        sa.CheckConstraint(
            "suspended_activity IS NULL OR active_mode = 'ASK'", name="ck_activity_suspended_mode"
        ),
        sa.ForeignKeyConstraint(
            ["active_concept_id", "workspace_id"],
            ["concepts.id", "concepts.workspace_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("workspace_id"),
    )
    op.create_table(
        "assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("concept_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("purpose", sa.String(length=32), server_default="diagnostic", nullable=False),
        sa.Column("prompt", sa.String(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("answer_key", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("feedback_blocks", sa.JSON(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('single_choice','structured_short')", name="ck_assessment_kind"
        ),
        sa.CheckConstraint(
            "purpose != 'immediate_check' OR concept_id IS NOT NULL", name="ck_check_has_concept"
        ),
        sa.CheckConstraint(
            "purpose IN ('diagnostic','immediate_check')", name="ck_assessment_purpose"
        ),
        sa.ForeignKeyConstraint(
            ["concept_id", "workspace_id"],
            ["concepts.id", "concepts.workspace_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_assessments_concept_id"), "assessments", ["concept_id"], unique=False)
    op.create_index(
        op.f("ix_assessments_workspace_id"), "assessments", ["workspace_id"], unique=False
    )
    op.create_table(
        "attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("response", sa.String(), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'not_assessed' AND result IS NULL AND response IS NULL) OR (status = 'completed' AND result IS NOT NULL AND result IN ('understood','needs_review') AND response IS NOT NULL)",
            name="ck_attempt_result",
        ),
        sa.CheckConstraint("status IN ('completed','not_assessed')", name="ck_attempt_status"),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_attempts_assessment_id"), "attempts", ["assessment_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_attempts_assessment_id"), table_name="attempts")
    op.drop_table("attempts")
    op.drop_index(op.f("ix_assessments_workspace_id"), table_name="assessments")
    op.drop_index(op.f("ix_assessments_concept_id"), table_name="assessments")
    op.drop_table("assessments")
    op.drop_table("activity_states")
    op.drop_index(op.f("ix_concepts_plan_id"), table_name="concepts")
    op.drop_table("concepts")
    op.drop_index(op.f("ix_learning_plans_workspace_id"), table_name="learning_plans")
    op.drop_table("learning_plans")
    op.drop_table("learner_profiles")
