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
        "memberships", "audit_events", "mpesa_payment_intents",
        "mpesa_refund_intents", "mpesa_settlement_batches", "mpesa_settlement_lines",
        "procurement_settlements", "crm_campaign_deliveries",
        "developer_webhook_endpoints", "developer_webhook_deliveries",
        "records", "branches", "inventory_products", "inventory_stock_movements",
        "accounting_accounts", "accounting_journals", "accounting_journal_lines",
        "crm_contacts", "crm_leads", "procurement_suppliers",
        "procurement_purchase_orders", "pos_shifts", "pos_sales",
        "school_classes", "school_learners", "accounting_invoices",
        "status_alert_deliveries",
        "hr_employees", "hr_leave_requests", "hr_attendance_records",
        "payroll_rule_sets", "payroll_runs", "payroll_payslips",
        "payroll_accounting_mappings", "payroll_accounting_links",
        "payroll_adjustments", "payroll_payment_batches",
        "payroll_payment_batch_items", "payroll_bank_statement_lines",
        "accounting_fx_rates", "accounting_fx_postings",
        "accounting_fx_revaluations", "accounting_fx_settlements",
        "payroll_statutory_batches", "user_sessions", "portal_authorization_assurance",
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


@pytest.mark.parametrize("table_name", [
    "hr_employees", "hr_leave_requests", "hr_attendance_records",
    "payroll_rule_sets", "payroll_runs", "payroll_payslips",
    "payroll_accounting_mappings", "payroll_accounting_links",
    "payroll_adjustments", "payroll_payment_batches",
    "payroll_payment_batch_items", "payroll_bank_statement_lines",
    "accounting_fx_rates", "accounting_fx_postings",
    "accounting_fx_revaluations", "accounting_fx_settlements",
    "payroll_statutory_batches", "user_sessions", "portal_authorization_assurance",
])
def test_production_readiness_rejects_each_missing_critical_tenant_rls_table(table_name):
    from app.main import _verify_rls_database_boundary
    tables = [row for row in _tables() if row["relname"] != table_name]
    with pytest.raises(RuntimeError, match="RLS schema"):
        _verify_rls_database_boundary(_Connection(
            {"role_name": "onecore_api", "is_superuser": False, "bypasses_rls": False}, tables
        ))
