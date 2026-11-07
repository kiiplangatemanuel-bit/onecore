"""Merge the SACCO security and HR migration branches.

Revision ID: 0029_sacco_loan_security_merge
Revises: 0028_sacco_loan_servicing, 0022_sacco_guarantors_collateral
"""
revision = "0029_sacco_loan_security_merge"
down_revision = ("0028_sacco_loan_servicing", "0022_sacco_guarantors_collateral")
branch_labels = None
depends_on = None


def upgrade():
    # Both parent revisions have already applied their schema changes.
    pass


def downgrade():
    # Alembic downgrades each parent branch after this merge revision.
    pass
