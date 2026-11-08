import pytest


class _Result:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row

    def all(self):
        return self.rows


class _Connection:
    def __init__(self, role, tables):
        self.role = role
        self.tables = tables

    def execute(self, statement):
        if "FROM pg_roles" in str(statement):
            return _Result(row=self.role)
        return _Result(rows=self.tables)


def _tables():
    names = (
        "portal_workflow_records", "support_tickets", "support_messages",
        "support_attachments", "developer_api_keys", "developer_api_key_usages",
        "memberships",
        "developer_webhook_endpoints", "developer_webhook_deliveries",
        "records", "branches", "inventory_products", "inventory_stock_movements",
        "accounting_accounts", "accounting_journals", "accounting_journal_lines",
        "crm_contacts", "crm_leads", "procurement_suppliers",
        "procurement_purchase_orders", "pos_shifts", "pos_sales",
        "school_classes", "school_learners", "accounting_invoices",
    )
    return [
        {"relname": name, "rls_enabled": True, "rls_forced": True, "has_policy": True}
        for name in names
    ]


def test_production_database_boundary_accepts_nobypassrls_role_and_forced_policies():
    from app.main import _verify_rls_database_boundary
    _verify_rls_database_boundary(_Connection(
        {"role_name": "onecore_api", "is_superuser": False, "bypasses_rls": False}, _tables()
    ))


@pytest.mark.parametrize("role", [
    {"role_name": "postgres", "is_superuser": True, "bypasses_rls": True},
    {"role_name": "unsafe_runtime", "is_superuser": False, "bypasses_rls": True},
])
def test_production_database_boundary_rejects_privileged_roles(role):
    from app.main import _verify_rls_database_boundary
    with pytest.raises(RuntimeError, match="NOBYPASSRLS"):
        _verify_rls_database_boundary(_Connection(role, _tables()))


def test_production_database_boundary_rejects_tables_without_forced_rls():
    from app.main import _verify_rls_database_boundary
    tables = _tables()
    tables[0]["rls_forced"] = False
    with pytest.raises(RuntimeError, match="RLS schema"):
        _verify_rls_database_boundary(_Connection(
            {"role_name": "onecore_api", "is_superuser": False, "bypasses_rls": False}, tables
        ))


def test_production_database_boundary_rejects_missing_critical_rls_table():
    from app.main import _verify_rls_database_boundary
    tables = _tables()[:-1]
    with pytest.raises(RuntimeError, match="RLS schema"):
        _verify_rls_database_boundary(_Connection(
            {"role_name": "onecore_api", "is_superuser": False, "bypasses_rls": False}, tables
        ))
