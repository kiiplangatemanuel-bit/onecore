"""School admissions, classes, subjects and assessment foundation.

Revision ID: 0007_school
Revises: 0006_pos
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_school"
down_revision = "0006_pos"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("school_classes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("stream", sa.String(40), nullable=False),
        sa.Column("academic_year", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_school_classes_organization_id", "school_classes", ["organization_id"])
    op.create_index("ix_school_classes_branch_id", "school_classes", ["branch_id"])
    op.create_index("ix_school_class_org_year_name_stream", "school_classes", ["organization_id", "academic_year", "name", "stream"], unique=True)

    op.create_table("school_learners",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("school_classes.id"), nullable=True),
        sa.Column("admission_number", sa.String(40), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("date_of_birth", sa.DateTime(timezone=True), nullable=True),
        sa.Column("guardian_name", sa.String(180), nullable=False),
        sa.Column("guardian_phone", sa.String(32), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_school_learners_organization_id", "school_learners", ["organization_id"])
    op.create_index("ix_school_learners_branch_id", "school_learners", ["branch_id"])
    op.create_index("ix_school_learners_class_id", "school_learners", ["class_id"])
    op.create_index("ix_school_learner_org_admission", "school_learners", ["organization_id", "admission_number"], unique=True)

    op.create_table("school_subjects",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("code", sa.String(24), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_school_subjects_organization_id", "school_subjects", ["organization_id"])
    op.create_index("ix_school_subject_org_code", "school_subjects", ["organization_id", "code"], unique=True)

    op.create_table("school_assessments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("school_classes.id"), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("school_subjects.id"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("academic_year", sa.Integer(), nullable=False),
        sa.Column("term", sa.String(24), nullable=False),
        sa.Column("maximum_score", sa.Numeric(8, 2), nullable=False),
        sa.Column("weight", sa.Numeric(8, 4), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("published_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_school_assessments_organization_id", "school_assessments", ["organization_id"])
    op.create_index("ix_school_assessments_class_id", "school_assessments", ["class_id"])
    op.create_index("ix_school_assessments_subject_id", "school_assessments", ["subject_id"])

    op.create_table("school_marks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("school_assessments.id"), nullable=False),
        sa.Column("learner_id", sa.Integer(), sa.ForeignKey("school_learners.id"), nullable=False),
        sa.Column("score", sa.Numeric(8, 2), nullable=False),
        sa.Column("entered_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_school_marks_organization_id", "school_marks", ["organization_id"])
    op.create_index("ix_school_marks_assessment_id", "school_marks", ["assessment_id"])
    op.create_index("ix_school_marks_learner_id", "school_marks", ["learner_id"])
    op.create_index("ix_school_mark_org_assessment_learner", "school_marks", ["organization_id", "assessment_id", "learner_id"], unique=True)

    op.create_table("school_grade_bands",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("scale_name", sa.String(80), nullable=False),
        sa.Column("grade", sa.String(12), nullable=False),
        sa.Column("minimum_percent", sa.Numeric(6, 3), nullable=False),
        sa.Column("maximum_percent", sa.Numeric(6, 3), nullable=False),
        sa.Column("points", sa.Numeric(6, 3), nullable=False))
    op.create_index("ix_school_grade_bands_organization_id", "school_grade_bands", ["organization_id"])
    op.create_index("ix_school_grade_org_scale_grade", "school_grade_bands", ["organization_id", "scale_name", "grade"], unique=True)


def downgrade():
    op.drop_table("school_grade_bands")
    op.drop_table("school_marks")
    op.drop_table("school_assessments")
    op.drop_table("school_subjects")
    op.drop_table("school_learners")
    op.drop_table("school_classes")
