from pathlib import Path


def test_tenant_domain_rls_migration_is_chained_after_support_scan():
    migration = Path(__file__).parents[1] / "migrations" / "versions" / "0059_tenant_domain_row_level_security.py"
    source = migration.read_text()
    assert 'revision = "0059_tenant_domain_row_level_security"' in source
    assert 'down_revision = "0058_support_attachment_scan_evidence"' in source


def test_tenant_domain_rls_covers_only_tables_with_tenant_columns():
    migration = Path(__file__).parents[1] / "migrations" / "versions" / "0059_tenant_domain_row_level_security.py"
    source = migration.read_text()
    assert '"organization_id" in columns' in source
    assert "ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in source
    assert "ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in source
    assert "m.is_active = true" in source
    assert "u.platform_role IN ('root_superadmin', 'platform_admin')" in source


def test_tenant_domain_rls_defers_sensitive_and_specialized_tables():
    migration = Path(__file__).parents[1] / "migrations" / "versions" / "0059_tenant_domain_row_level_security.py"
    source = migration.read_text()
    for table in ("memberships", "portal_workflow_records", "support_tickets", "developer_api_keys"):
        assert f'"{table}"' in source
    assert 'table_name.startswith("healthcare_")' in source
