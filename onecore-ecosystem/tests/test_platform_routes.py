from datetime import datetime, timedelta, timezone
from app.core.models import CustomDomain, SystemNotice, NoticeDismissal

def test_platform_models_register():
    assert CustomDomain.__tablename__ == "custom_domains"
    assert SystemNotice.__tablename__ == "system_notices"
    assert NoticeDismissal.__tablename__ == "notice_dismissals"

def test_domain_status_defaults():
    from app.core.models import now
    row=CustomDomain(organization_id=1,hostname="shop.example.com",verification_token="test-token")
    assert row.status == "pending_verification"
    assert row.tls_status == "not_provisioned"
    assert row.is_primary is False

def test_notice_is_informational_and_defaults_to_draft_model():
    row=SystemNotice(title="Planned maintenance",message="Services remain available",
                     created_by=1)
    assert row.status == "draft"
    assert row.severity == "info"
    assert row.audience == {}
