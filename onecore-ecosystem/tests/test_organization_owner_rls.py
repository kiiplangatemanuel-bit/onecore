from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_organization_owner_migration_follows_tenant_rls():
    source = (ROOT / "migrations" / "versions" / "0061_organization_owner_membership_bootstrap.py").read_text()
    assert 'revision = "0061_organization_owner_membership_bootstrap"' in source
    assert 'down_revision = "0060_status_alert_email_outbox"' in source
    assert "UPDATE organizations o" in source
    assert "m.role = 'org_admin'" in source


def test_organization_creation_sets_authenticated_owner():
    routes = (ROOT / "app" / "api" / "routes.py").read_text()
    auth = (ROOT / "app" / "api" / "auth_workflows.py").read_text()
    assert "Organization(**payload.model_dump(), owner_user_id=user.id)" in routes
    assert "owner_user_id=user.id" in auth


def test_membership_policy_allows_owner_admin_but_blocks_peer_escalation():
    source = (ROOT / "migrations" / "versions" / "0060_organization_owner_membership_bootstrap.py").read_text()
    assert "public.onecore_is_org_owner(organization_id)" in source
    assert "role = 'org_admin'" in source
    assert "role <> 'org_admin'" in source
    assert "SECURITY DEFINER" in source
