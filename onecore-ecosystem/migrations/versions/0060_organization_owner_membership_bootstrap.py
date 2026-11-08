"""Preserve organization ownership and permit secure first-admin bootstrap."""
from alembic import op
import sqlalchemy as sa

revision = "0060_organization_owner_membership_bootstrap"
down_revision = "0059_tenant_domain_row_level_security"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "organizations",
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_organizations_owner_user_id_users",
        "organizations", "users", ["owner_user_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_organizations_owner_user_id", "organizations", ["owner_user_id"]
    )
    op.execute("""
        UPDATE organizations o
        SET owner_user_id = (
            SELECT m.user_id
            FROM memberships m
            WHERE m.organization_id = o.id
              AND m.is_active = true
              AND m.role = 'org_admin'
            ORDER BY m.id ASC
            LIMIT 1
        )
        WHERE o.owner_user_id IS NULL
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.onecore_is_org_owner(target_org_id integer)
        RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT EXISTS (
                SELECT 1 FROM public.organizations o
                WHERE o.id = target_org_id
                  AND o.owner_user_id = NULLIF(current_setting('app.user_id', true), '')::integer
            )
        $$
    """)
    op.execute("GRANT EXECUTE ON FUNCTION public.onecore_is_org_owner(integer) TO PUBLIC")
    op.execute("DROP POLICY IF EXISTS membership_insert ON memberships")
    op.execute("""
        CREATE POLICY membership_insert ON memberships
        FOR INSERT WITH CHECK (
            (
                public.onecore_is_org_admin(organization_id)
                AND role <> 'org_admin'
            )
            OR (
                public.onecore_is_org_owner(organization_id)
                AND role = 'org_admin'
            )
            OR public.onecore_is_platform_admin()
        )
    """)
    op.execute("DROP POLICY IF EXISTS membership_update ON memberships")
    op.execute("""
        CREATE POLICY membership_update ON memberships
        FOR UPDATE
        USING (
            public.onecore_is_org_admin(organization_id)
            OR public.onecore_is_org_owner(organization_id)
            OR public.onecore_is_platform_admin()
        )
        WITH CHECK (
            (
                (
                    public.onecore_is_org_admin(organization_id)
                    AND role <> 'org_admin'
                )
                OR public.onecore_is_org_owner(organization_id)
            )
            OR public.onecore_is_platform_admin()
        )
    """)


def downgrade():
    op.execute("DROP POLICY IF EXISTS membership_update ON memberships")
    op.execute("""
        CREATE POLICY membership_update ON memberships
        FOR UPDATE
        USING (public.onecore_is_org_admin(organization_id) OR public.onecore_is_platform_admin())
        WITH CHECK (
            (public.onecore_is_org_admin(organization_id) AND role <> 'org_admin')
            OR public.onecore_is_platform_admin()
        )
    """)
    op.execute("DROP POLICY IF EXISTS membership_insert ON memberships")
    op.execute("""
        CREATE POLICY membership_insert ON memberships
        FOR INSERT WITH CHECK (
            (public.onecore_is_org_admin(organization_id) AND role <> 'org_admin')
            OR public.onecore_is_platform_admin()
        )
    """)
    op.execute("DROP FUNCTION IF EXISTS public.onecore_is_org_owner(integer)")
    op.drop_index("ix_organizations_owner_user_id", table_name="organizations")
    op.drop_constraint("fk_organizations_owner_user_id_users", "organizations", type_="foreignkey")
    op.drop_column("organizations", "owner_user_id")
