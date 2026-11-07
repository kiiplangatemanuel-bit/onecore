from app.core.models import CustomDomain, SystemNotice, NoticeDismissal

def test_platform_tables_registered():
    assert CustomDomain.__tablename__ == "custom_domains"
    assert SystemNotice.__tablename__ == "system_notices"
    assert NoticeDismissal.__tablename__ == "notice_dismissals"

def test_domain_column_defaults():
    assert CustomDomain.__table__.c.status.default.arg == "pending_verification"
    assert CustomDomain.__table__.c.tls_status.default.arg == "not_provisioned"
    assert CustomDomain.__table__.c.is_primary.default.arg is False

def test_notice_column_defaults():
    assert SystemNotice.__table__.c.status.default.arg == "draft"
    assert SystemNotice.__table__.c.severity.default.arg == "info"

def test_dismissal_is_unique_per_user_and_notice():
    constraints = [c for c in NoticeDismissal.__table__.constraints if getattr(c, "name", None) == "ix_notice_dismissal_user_notice"]
    indexes = [i for i in NoticeDismissal.__table__.indexes if i.name == "ix_notice_dismissal_user_notice"]
    assert constraints or indexes

def test_hostname_validation():
    import pytest
    from fastapi import HTTPException
    from app.api.platform_routes import _hostname
    assert _hostname("Shop.Example.com") == "shop.example.com"
    with pytest.raises(HTTPException):
        _hostname("localhost")
    with pytest.raises(HTTPException):
        _hostname("bad host.example.com")
    with pytest.raises(HTTPException):
        _hostname("customer.onecore.co.ke")

def test_invitation_role_validation():
    import pytest
    from pydantic import ValidationError
    from app.api.platform_routes import InvitationIn
    assert InvitationIn(email="staff@example.com", role="staff").role == "staff"
    with pytest.raises(ValidationError):
        InvitationIn(email="staff@example.com", role="root_superadmin")
