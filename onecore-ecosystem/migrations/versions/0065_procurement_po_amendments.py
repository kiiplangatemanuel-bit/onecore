"""Add immutable PO versions and approval-version isolation."""
from alembic import op
import sqlalchemy as sa


revision = "0065_procurement_po_amendments"
down_revision = "0064_identity_sessions"
branch_labels = None
depends_on = None


def _backfill_initial_versions(bind):
    if bind.dialect.name == "postgresql":
        op.execute("""
            INSERT INTO public.procurement_purchase_order_versions
                (organization_id, purchase_order_id, version_number, change_reason,
                 supporting_notes, snapshot, changed_by, created_at)
            SELECT
                po.organization_id,
                po.id,
                1,
                'Initial purchase order (migration backfill)',
                COALESCE(po.notes, ''),
                json_build_object(
                    'order', json_build_object(
                        'supplier_id', po.supplier_id,
                        'branch_id', po.branch_id,
                        'currency', po.currency,
                        'notes', po.notes,
                        'status', po.status,
                        'amendment_version', 1
                    ),
                    'lines', COALESCE((
                        SELECT json_agg(json_build_object(
                            'line_id', line.id,
                            'product_id', line.product_id,
                            'quantity_ordered', line.quantity_ordered::text,
                            'quantity_received', line.quantity_received::text,
                            'unit_cost', line.unit_cost::text
                        ) ORDER BY line.id)
                        FROM public.procurement_purchase_order_lines line
                        WHERE line.purchase_order_id = po.id
                          AND line.organization_id = po.organization_id
                    ), '[]'::json)
                ),
                po.created_by,
                COALESCE(po.created_at, now())
            FROM public.procurement_purchase_orders po
        """)
        return

    metadata = sa.MetaData()
    orders = sa.Table("procurement_purchase_orders", metadata, autoload_with=bind)
    lines = sa.Table("procurement_purchase_order_lines", metadata, autoload_with=bind)
    versions = sa.Table("procurement_purchase_order_versions", metadata, autoload_with=bind)
    order_rows = bind.execute(sa.select(
        orders.c.id, orders.c.organization_id, orders.c.supplier_id, orders.c.branch_id,
        orders.c.currency, orders.c.notes, orders.c.status, orders.c.created_by, orders.c.created_at,
    )).mappings()
    for order in order_rows:
        line_rows = bind.execute(sa.select(
            lines.c.id, lines.c.product_id, lines.c.quantity_ordered,
            lines.c.quantity_received, lines.c.unit_cost,
        ).where(
            lines.c.organization_id == order["organization_id"],
            lines.c.purchase_order_id == order["id"],
        ).order_by(lines.c.id)).mappings()
        snapshot = {
            "order": {
                "supplier_id": order["supplier_id"],
                "branch_id": order["branch_id"],
                "currency": order["currency"],
                "notes": order["notes"],
                "status": order["status"],
                "amendment_version": 1,
            },
            "lines": [{
                "line_id": line["id"],
                "product_id": line["product_id"],
                "quantity_ordered": str(line["quantity_ordered"]),
                "quantity_received": str(line["quantity_received"]),
                "unit_cost": str(line["unit_cost"]),
            } for line in line_rows],
        }
        bind.execute(versions.insert().values(
            organization_id=order["organization_id"],
            purchase_order_id=order["id"],
            version_number=1,
            change_reason="Initial purchase order (migration backfill)",
            supporting_notes=order["notes"] or "",
            snapshot=snapshot,
            changed_by=order["created_by"],
            created_at=order["created_at"],
        ))


def upgrade():
    op.add_column(
        "procurement_purchase_orders",
        sa.Column("amendment_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "procurement_approval_actions",
        sa.Column("approval_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.drop_index(
        "ix_procurement_approval_action_org_entity_level",
        table_name="procurement_approval_actions",
    )
    op.create_index(
        "ix_procurement_approval_action_org_entity_level",
        "procurement_approval_actions",
        ["organization_id", "entity_type", "entity_id", "approval_level", "approval_version"],
        unique=True,
    )
    op.create_table(
        "procurement_purchase_order_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("procurement_purchase_orders.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("change_reason", sa.String(500), nullable=False),
        sa.Column("supporting_notes", sa.String(2000), nullable=False, server_default=""),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("changed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "organization_id", "purchase_order_id", "version_number",
            name="uq_procurement_po_version",
        ),
    )
    op.create_index(
        "ix_procurement_purchase_order_versions_organization_id",
        "procurement_purchase_order_versions", ["organization_id"],
    )
    op.create_index(
        "ix_procurement_purchase_order_versions_purchase_order_id",
        "procurement_purchase_order_versions", ["purchase_order_id"],
    )

    bind = op.get_bind()
    _backfill_initial_versions(bind)

    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE public.procurement_purchase_order_versions ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE public.procurement_purchase_order_versions FORCE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY tenant_scope_access ON public.procurement_purchase_order_versions
            FOR ALL
            USING (
                (
                    organization_id IS NOT NULL
                    AND EXISTS (
                        SELECT 1 FROM public.memberships m
                        WHERE m.organization_id = procurement_purchase_order_versions.organization_id
                          AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND m.is_active = true
                    )
                )
                OR organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer
                OR public.onecore_is_platform_admin()
            )
            WITH CHECK (
                (
                    organization_id IS NOT NULL
                    AND EXISTS (
                        SELECT 1 FROM public.memberships m
                        WHERE m.organization_id = procurement_purchase_order_versions.organization_id
                          AND m.user_id = NULLIF(current_setting('app.user_id', true), '')::integer
                          AND m.is_active = true
                    )
                )
                OR organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer
                OR public.onecore_is_platform_admin()
            )
        """)
        op.execute("""
            DO $po_versions$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'onecore_api') THEN
                    REVOKE UPDATE, DELETE, TRUNCATE ON TABLE
                        public.procurement_purchase_order_versions FROM onecore_api;
                    GRANT SELECT, INSERT ON TABLE
                        public.procurement_purchase_order_versions TO onecore_api;
                    GRANT USAGE, SELECT ON SEQUENCE
                        public.procurement_purchase_order_versions_id_seq TO onecore_api;
                END IF;
            END
            $po_versions$
        """)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_scope_access ON public.procurement_purchase_order_versions")
        op.execute("ALTER TABLE public.procurement_purchase_order_versions NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE public.procurement_purchase_order_versions DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "ix_procurement_purchase_order_versions_purchase_order_id",
        table_name="procurement_purchase_order_versions",
    )
    op.drop_index(
        "ix_procurement_purchase_order_versions_organization_id",
        table_name="procurement_purchase_order_versions",
    )
    op.drop_table("procurement_purchase_order_versions")
    op.drop_index(
        "ix_procurement_approval_action_org_entity_level",
        table_name="procurement_approval_actions",
    )
    op.create_index(
        "ix_procurement_approval_action_org_entity_level",
        "procurement_approval_actions",
        ["organization_id", "entity_type", "entity_id", "approval_level"],
        unique=True,
    )
    with op.batch_alter_table("procurement_approval_actions") as batch:
        batch.drop_column("approval_version")
    with op.batch_alter_table("procurement_purchase_orders") as batch:
        batch.drop_column("amendment_version")
