"""Encrypt confidential Trust portal payloads at rest."""
from alembic import op
import sqlalchemy as sa

revision = "0053_portal_confidential_payloads"
down_revision = "0052_supabase_auth_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("portal_resources", sa.Column("encrypted_payload", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("portal_resources", "encrypted_payload")
