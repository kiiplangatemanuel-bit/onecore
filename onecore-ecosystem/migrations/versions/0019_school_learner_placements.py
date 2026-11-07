"""School learner placement history.

Revision ID: 0019_school_learner_placements
Revises: 0018_pos_returns
"""
from alembic import op
import sqlalchemy as sa

revision = "0019_school_learner_placements"
down_revision = "0018_pos_returns"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "school_enrollment_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("learner_id", sa.Integer(), sa.ForeignKey("school_learners.id"), nullable=False),
        sa.Column("from_class_id", sa.Integer(), sa.ForeignKey("school_classes.id"), nullable=False),
        sa.Column("to_class_id", sa.Integer(), sa.ForeignKey("school_classes.id"), nullable=False),
        sa.Column("effective_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("change_type", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("changed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_school_enrollment_history_organization_id", "school_enrollment_history", ["organization_id"])
    op.create_index("ix_school_enrollment_history_learner_id", "school_enrollment_history", ["learner_id"])
    op.create_index("ix_school_enrollment_history_from_class_id", "school_enrollment_history", ["from_class_id"])
    op.create_index("ix_school_enrollment_history_to_class_id", "school_enrollment_history", ["to_class_id"])
    op.create_index("ix_school_enrollment_history_effective_date", "school_enrollment_history", ["effective_date"])


def downgrade():
    op.drop_table("school_enrollment_history")
