from pathlib import Path


def test_status_alert_outbox_migration_is_chained_after_tenant_rls():
    source = (Path(__file__).parents[1] / "migrations" / "versions" / "0060_status_alert_email_outbox.py").read_text()
    assert 'revision = "0060_status_alert_email_outbox"' in source
    assert 'down_revision = "0059_tenant_domain_row_level_security"' in source


def test_status_alert_outbox_has_user_and_worker_specific_rls_policies():
    source = (Path(__file__).parents[1] / "migrations" / "versions" / "0060_status_alert_email_outbox.py").read_text()
    assert "ALTER TABLE status_alert_deliveries ENABLE ROW LEVEL SECURITY" in source
    assert "ALTER TABLE status_alert_deliveries FORCE ROW LEVEL SECURITY" in source
    assert "user_id = NULLIF(current_setting('app.user_id', true), '')::integer" in source
    assert "current_user = 'onecore_status_alert_worker'" in source
    assert "public.onecore_is_platform_admin()" in source


def test_platform_admin_reads_only_status_subscription_record_types_for_fanout():
    source = (Path(__file__).parents[1] / "migrations" / "versions" / "0060_status_alert_email_outbox.py").read_text()
    assert "portal_key = 'status'" in source
    assert "record_type IN ('alert_subscription', 'notification_preference')" in source
