"""Add public and authenticated support ticketing."""
from alembic import op
import sqlalchemy as sa

revision = "0048_support_ticketing"
down_revision = "0047_pos_loyalty_redemption_policy"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "support_tickets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_number", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(180), nullable=False),
        sa.Column("category", sa.String(40), nullable=False, server_default="general"),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("contact_name", sa.String(180), nullable=False),
        sa.Column("contact_email", sa.String(320), nullable=False),
        sa.Column("contact_phone", sa.String(32), nullable=False, server_default=""),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("assigned_to_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("guest_token_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("guest_token_hash", name="uq_support_ticket_guest_token_hash"),
    )
    op.create_index("ix_support_tickets_ticket_number", "support_tickets", ["ticket_number"], unique=True)
    op.create_index("ix_support_tickets_status", "support_tickets", ["status"])
    op.create_index("ix_support_tickets_contact_email", "support_tickets", ["contact_email"])
    op.create_index("ix_support_tickets_organization_id", "support_tickets", ["organization_id"])
    op.create_index("ix_support_tickets_created_by_user_id", "support_tickets", ["created_by_user_id"])
    op.create_index("ix_support_tickets_assigned_to_user_id", "support_tickets", ["assigned_to_user_id"])

    op.create_table(
        "support_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("author_name", sa.String(180), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_staff", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_support_messages_ticket_id", "support_messages", ["ticket_id"])
    op.create_index("ix_support_message_ticket_created", "support_messages", ["ticket_id", "created_at"])


def downgrade():
    op.drop_index("ix_support_message_ticket_created", table_name="support_messages")
    op.drop_index("ix_support_messages_ticket_id", table_name="support_messages")
    op.drop_table("support_messages")
    op.drop_index("ix_support_tickets_assigned_to_user_id", table_name="support_tickets")
    op.drop_index("ix_support_tickets_created_by_user_id", table_name="support_tickets")
    op.drop_index("ix_support_tickets_organization_id", table_name="support_tickets")
    op.drop_index("ix_support_tickets_contact_email", table_name="support_tickets")
    op.drop_index("ix_support_tickets_status", table_name="support_tickets")
    op.drop_index("ix_support_tickets_ticket_number", table_name="support_tickets")
    op.drop_table("support_tickets")
