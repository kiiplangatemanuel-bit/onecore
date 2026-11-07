"""Merge the parallel HR payroll and school/healthcare migration heads.

Revision ID: 0026_merge_hr_school_health
Revises: 0024_hr_payroll, 0025_healthcare_patients_appointments
"""
revision = "0026_merge_hr_school_health"
down_revision = ("0024_hr_payroll", "0025_healthcare_patients_appointments")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
