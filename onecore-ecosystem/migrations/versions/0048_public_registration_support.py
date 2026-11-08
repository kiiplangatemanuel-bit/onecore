"""Public organization registration and support ticket lifecycle."""
from alembic import op
import sqlalchemy as sa
revision="0048_public_registration_support"
down_revision="0047_pos_loyalty_redemption_policy"
branch_labels=None
depends_on=None

def upgrade():
    op.add_column("organizations",sa.Column("registration_number",sa.String(100),nullable=False,server_default=""))
    op.add_column("organizations",sa.Column("contact_phone",sa.String(32),nullable=False,server_default=""))
    op.create_table("email_verifications",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("user_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),
        sa.Column("token_hash",sa.String(64),nullable=False),
        sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("used_at",sa.DateTime(timezone=True),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.UniqueConstraint("token_hash",name="uq_email_verifications_token_hash"))
    op.create_index("ix_email_verifications_user_id","email_verifications",["user_id"])
    op.create_index("ix_email_verifications_token_hash","email_verifications",["token_hash"])
    op.create_table("support_tickets",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("reference",sa.String(32),nullable=False),
        sa.Column("organization_id",sa.Integer(),sa.ForeignKey("organizations.id"),nullable=True),
        sa.Column("requester_user_id",sa.Integer(),sa.ForeignKey("users.id"),nullable=True),
        sa.Column("requester_name",sa.String(180),nullable=False),
        sa.Column("requester_email",sa.String(320),nullable=False),
        sa.Column("subject",sa.String(180),nullable=False),
        sa.Column("category",sa.String(30),nullable=False,server_default="general"),
        sa.Column("priority",sa.String(20),nullable=False,server_default="normal"),
        sa.Column("status",sa.String(30),nullable=False,server_default="open"),
        sa.Column("public_access_hash",sa.String(64),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.UniqueConstraint("reference",name="uq_support_tickets_reference"),
        sa.UniqueConstraint("public_access_hash",name="uq_support_tickets_public_access_hash"))
    op.create_index("ix_support_tickets_organization_id","support_tickets",["organization_id"])
    op.create_index("ix_support_tickets_requester_user_id","support_tickets",["requester_user_id"])
    op.create_index("ix_support_tickets_requester_email","support_tickets",["requester_email"])
    op.create_index("ix_support_ticket_org_status","support_tickets",["organization_id","status"])
    op.create_table("support_messages",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("ticket_id",sa.Integer(),sa.ForeignKey("support_tickets.id",ondelete="CASCADE"),nullable=False),
        sa.Column("author_user_id",sa.Integer(),sa.ForeignKey("users.id"),nullable=True),
        sa.Column("author_type",sa.String(20),nullable=False),
        sa.Column("body",sa.Text(),nullable=False),
        sa.Column("is_internal",sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))
    op.create_index("ix_support_messages_ticket_id","support_messages",["ticket_id"])

def downgrade():
    op.drop_index("ix_support_messages_ticket_id",table_name="support_messages")
    op.drop_table("support_messages")
    op.drop_index("ix_support_ticket_org_status",table_name="support_tickets")
    op.drop_index("ix_support_tickets_requester_email",table_name="support_tickets")
    op.drop_index("ix_support_tickets_requester_user_id",table_name="support_tickets")
    op.drop_index("ix_support_tickets_organization_id",table_name="support_tickets")
    op.drop_table("support_tickets")
    op.drop_index("ix_email_verifications_token_hash",table_name="email_verifications")
    op.drop_index("ix_email_verifications_user_id",table_name="email_verifications")
    op.drop_table("email_verifications")
    op.drop_column("organizations","contact_phone")
    op.drop_column("organizations","registration_number")
