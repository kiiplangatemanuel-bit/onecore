"""Add employee-configured overtime policy and scheduled working minutes."""
from alembic import op
import sqlalchemy as sa

revision = "0041_employee_overtime_policy"
down_revision = "0040_hr_attendance"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("hr_employees", sa.Column(
        "scheduled_minutes_per_day", sa.Integer(), nullable=False, server_default="480"
    ))
    op.add_column("hr_employees", sa.Column(
        "overtime_multiplier", sa.Numeric(5, 2), nullable=True
    ))


def downgrade():
    op.drop_column("hr_employees", "overtime_multiplier")
    op.drop_column("hr_employees", "scheduled_minutes_per_day")
