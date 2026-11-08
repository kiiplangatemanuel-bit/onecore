"""Add one-time PKCE authorization codes for portal SSO handoff."""
from alembic import op
import sqlalchemy as sa

revision = "0050_portal_authorization_codes"
down_revision = "0049_verified_org_registration"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "portal_authorization_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("redirect_uri", sa.String(2048), nullable=False),
        sa.Column("code_challenge", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_portal_authorization_codes_code_hash", "portal_authorization_codes", ["code_hash"], unique=True)
    op.create_index("ix_portal_authorization_codes_user_id", "portal_authorization_codes", ["user_id"])
    op.create_index("ix_portal_authorization_codes_expires_at", "portal_authorization_codes", ["expires_at"])


def downgrade():
    op.drop_index("ix_portal_authorization_codes_expires_at", table_name="portal_authorization_codes")
    op.drop_index("ix_portal_authorization_codes_user_id", table_name="portal_authorization_codes")
    op.drop_index("ix_portal_authorization_codes_code_hash", table_name="portal_authorization_codes")
    op.drop_table("portal_authorization_codes")
