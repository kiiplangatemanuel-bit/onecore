"""Daily school attendance register.

Revision ID: 0013_school_attendance
Revises: 0012_crm_quotes
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_school_attendance"
down_revision = "0012_crm_quotes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "school_attendance",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("school_classes.id"), nullable=False),
        sa.Column("learner_id", sa.Integer(), sa.ForeignKey("school_learners.id"), nullable=False),
        sa.Column("attendance_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("recorded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_school_attendance_organization_id", "school_attendance", ["organization_id"])
    op.create_index("ix_school_attendance_branch_id", "school_attendance", ["branch_id"])
    op.create_index("ix_school_attendance_class_id", "school_attendance", ["class_id"])
    op.create_index("ix_school_attendance_learner_id", "school_attendance", ["learner_id"])
    op.create_index("ix_school_attendance_attendance_date", "school_attendance", ["attendance_date"])
    op.create_index(
        "ix_school_attendance_org_date_learner", "school_attendance",
        ["organization_id", "attendance_date", "learner_id"], unique=True,
    )


def downgrade():
    op.drop_table("school_attendance")
