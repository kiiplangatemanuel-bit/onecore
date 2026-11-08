from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_mpesa_and_supplier_callbacks_bind_token_then_verified_tenant():
    mpesa = (ROOT / "app" / "api" / "mpesa.py").read_text()
    procurement = (ROOT / "app" / "api" / "procurement_workflows.py").read_text()
    assert "set_provider_callback_token_context(db, digest)" in mpesa
    assert "set_verified_organization_context(db, intent.organization_id)" in mpesa
    assert "set_provider_callback_token_context(db, digest)" in procurement
    assert "set_verified_organization_context(db, settlement.organization_id)" in procurement


def test_crm_delivery_and_unsubscribe_callbacks_bind_verified_tenant():
    source = (ROOT / "app" / "api" / "crm_campaigns.py").read_text()
    assert "set_crm_delivery_callback_context(db)" in source
    assert "set_crm_unsubscribe_token_context(db,digest)" in source
    assert "set_verified_organization_context(db,d.organization_id)" in source


def test_crm_scheduler_processes_one_tenant_per_rls_context():
    source = (ROOT / "app" / "workers" / "crm_scheduler.py").read_text()
    assert "set_verified_organization_context(db, organization_id)" in source
    assert "run_due_schedules(" in source
    assert "organization_id=organization_id" in source
