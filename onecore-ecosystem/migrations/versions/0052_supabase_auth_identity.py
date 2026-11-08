"""Link OneCore accounts to verified Supabase Auth identities."""
from alembic import op
import sqlalchemy as sa

revision = "0052_supabase_auth_identity"
down_revision = "0051_portal_workflow_resources"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("supabase_auth_user_id", sa.String(36), nullable=True))
    op.create_index("ix_users_supabase_auth_user_id", "users", ["supabase_auth_user_id"], unique=True)


def downgrade():
    op.drop_index("ix_users_supabase_auth_user_id", table_name="users")
    op.drop_column("users", "supabase_auth_user_id")
