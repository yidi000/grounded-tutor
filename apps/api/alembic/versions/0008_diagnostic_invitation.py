"""Persist one diagnostic invitation per Workspace."""

import sqlalchemy as sa

from alembic import op

revision = "0008_diagnostic_invitation"
down_revision = "0007_learning_state"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "activity_states",
        sa.Column("diagnostic_invitation", sa.JSON(none_as_null=True), nullable=True),
    )


def downgrade():
    with op.batch_alter_table("activity_states") as batch:
        batch.drop_column("diagnostic_invitation")
