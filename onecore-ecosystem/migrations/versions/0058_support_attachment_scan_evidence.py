"""Persist automated Support attachment malware scan evidence."""
from alembic import op
import sqlalchemy as sa

revision = "0058_support_attachment_scan_evidence"
down_revision = "0057_developer_webhooks"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("support_attachments", sa.Column("scan_engine", sa.String(40), nullable=True))
    op.add_column("support_attachments", sa.Column("scan_result", sa.String(24), nullable=True))
    op.add_column("support_attachments", sa.Column("scan_signature", sa.String(255), nullable=True))
    op.add_column("support_attachments", sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("support_attachments", "scanned_at")
    op.drop_column("support_attachments", "scan_signature")
    op.drop_column("support_attachments", "scan_result")
    op.drop_column("support_attachments", "scan_engine")
