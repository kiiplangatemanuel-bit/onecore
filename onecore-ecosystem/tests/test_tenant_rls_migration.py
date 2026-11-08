from pathlib import Path


def test_tenant_domain_rls_migration_follows_support_scan():
    source = (Path(__file__).parents[1] / "migrations" / "versions" / "0059_tenant_domain_row_level_security.py").read_text()
    assert 'revision = "0059_tenant_domain_row_level_security"' in source
    assert 'down_revision = "0058_support_attachment_scan_evidence"' in source


def test_tenant_domain_rls_uses_active_membership_for_all_tenant_tables():
    source = (Path(__file__).parents[1] / "migrations" / "versions" / "0059_tenant_domain_row_level_security.py").read_text()
    assert '"organization_id" in columns' in source
    assert "ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in source
    assert "ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in source
    assert "m.is_active = true" in source
    assert "public.onecore_is_platform_admin()" in source


def test_membership_rls_supports_self_service_and_org_admin_management():
    source = (Path(__file__).parents[1] / "migrations" / "versions" / "0059_tenant_domain_row_level_security.py").read_text()
    assert "membership_select" in source
    assert "public.onecore_is_org_admin(organization_id)" in source
    assert "SECURITY DEFINER" in source
    assert "SET search_path = pg_catalog, public" in source


def test_tenant_rls_leaves_tables_with_dedicated_policy_chains_alone():
    source = (Path(__file__).parents[1] / "migrations" / "versions" / "0059_tenant_domain_row_level_security.py").read_text()
    for table in ("memberships", "portal_workflow_records", "support_tickets", "developer_api_keys"):
        assert f'"{table}"' in source


def test_org_admin_cannot_grant_or_escalate_another_org_admin():
    source = (Path(__file__).parents[1] / "migrations" / "versions" / "0059_tenant_domain_row_level_security.py").read_text()
    assert "role <> 'org_admin'" in source
    assert "OR public.onecore_is_platform_admin()" in source
