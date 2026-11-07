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

def test_branch_model_and_schema():
    from app.core.models import Branch
    from app.core.schemas import BranchIn
    assert Branch.__tablename__ == "branches"
    branch = Branch(id="00000000-0000-0000-0000-000000000001",
                    organization_id=1, code="HQ", name="Head Office")
    assert branch.id.endswith("0001")
    assert BranchIn(code="HQ", name="Head Office").name == "Head Office"

def test_branch_schema_rejects_invalid_code():
    import pytest
    from pydantic import ValidationError
    from app.core.schemas import BranchIn
    with pytest.raises(ValidationError):
        BranchIn(code="bad code", name="Branch")


def test_invitation_branch_scope_requires_active_branch_in_same_organization():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from fastapi import HTTPException
    import pytest
    from app.core.models import Branch
    from app.api.platform_routes import _validated_branch_scope

    engine = create_engine("sqlite:///:memory:")
    Branch.__table__.create(engine)
    with Session(engine) as db:
        db.add_all([
            Branch(id="branch-hq", organization_id=1, code="HQ", name="Head Office", is_active=True),
            Branch(id="branch-closed", organization_id=1, code="OLD", name="Closed", is_active=False),
            Branch(id="branch-other", organization_id=2, code="HQ", name="Other tenant", is_active=True),
        ])
        db.commit()
        assert _validated_branch_scope(db, 1, " branch-hq ") == "branch-hq"
        assert _validated_branch_scope(db, 1, "*") == "*"
        with pytest.raises(HTTPException) as inactive:
            _validated_branch_scope(db, 1, "branch-closed")
        assert inactive.value.status_code == 422
        with pytest.raises(HTTPException):
            _validated_branch_scope(db, 1, "branch-other")
        with pytest.raises(HTTPException):
            _validated_branch_scope(db, 1, "branch-hq,branch-hq")
        with pytest.raises(HTTPException):
            _validated_branch_scope(db, 1, "missing-branch")
    engine.dispose()
