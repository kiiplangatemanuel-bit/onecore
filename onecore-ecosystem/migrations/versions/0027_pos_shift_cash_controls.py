"""POS shift cash management and reconciliation."""
from alembic import op
import sqlalchemy as sa
revision="0027_pos_shift_cash_controls"
down_revision="0026_mpesa_receipt_uniqueness"
branch_labels=None
depends_on=None

def upgrade():
    with op.batch_alter_table("pos_shifts") as batch:
        for col in [
            sa.Column("expected_cash",sa.Numeric(18,2),nullable=True),
            sa.Column("counted_cash",sa.Numeric(18,2),nullable=True),
            sa.Column("cash_variance",sa.Numeric(18,2),nullable=True),
            sa.Column("reconciliation_status",sa.String(20),nullable=False,server_default="open"),
            sa.Column("counted_denominations",sa.JSON(),nullable=False,server_default=sa.text("'{}'")),
            sa.Column("close_note",sa.String(500),nullable=False,server_default=""),
            sa.Column("reviewed_by",sa.Integer(),sa.ForeignKey("users.id"),nullable=True),
            sa.Column("reviewed_at",sa.DateTime(timezone=True),nullable=True),
            sa.Column("review_note",sa.String(500),nullable=False,server_default="")]:
            batch.add_column(col)
    op.create_table("pos_cash_movements",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=False),
        sa.Column("branch_id",sa.String(36),sa.ForeignKey("branches.id"),nullable=False),
        sa.Column("shift_id",sa.Integer(),sa.ForeignKey("pos_shifts.id"),nullable=False),
        sa.Column("movement_type",sa.String(16),nullable=False),sa.Column("amount",sa.Numeric(18,2),nullable=False),
        sa.Column("reason",sa.String(500),nullable=False),sa.Column("reference",sa.String(120),nullable=False,server_default=""),
        sa.Column("idempotency_key",sa.String(100),nullable=False),sa.Column("status",sa.String(16),nullable=False,server_default="recorded"),
        sa.Column("created_by",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("authorized_by",sa.Integer(),sa.ForeignKey("users.id"),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_pos_cash_movements_organization_id","pos_cash_movements",["organization_id"])
    op.create_index("ix_pos_cash_movements_branch_id","pos_cash_movements",["branch_id"])
    op.create_index("ix_pos_cash_movements_shift_id","pos_cash_movements",["shift_id"])
    op.create_index("ix_pos_cash_movement_org_key","pos_cash_movements",["organization_id","idempotency_key"],unique=True)
    op.create_index("ix_pos_cash_movement_shift","pos_cash_movements",["organization_id","shift_id","status"])

def downgrade():
    for name in ("ix_pos_cash_movement_shift","ix_pos_cash_movement_org_key","ix_pos_cash_movements_shift_id","ix_pos_cash_movements_branch_id","ix_pos_cash_movements_organization_id"):
        op.drop_index(name,table_name="pos_cash_movements")
    op.drop_table("pos_cash_movements")
    for col in ("review_note","reviewed_at","reviewed_by","close_note","counted_denominations","reconciliation_status","cash_variance","counted_cash","expected_cash"):
        op.drop_column("pos_shifts",col)
