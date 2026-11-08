from app.api.auth_workflows import CompleteOrganizationRegistrationIn, complete_organization_registration
from app.core.models import AuditEvent, Membership, Organization, User
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.core.database import Base


def test_verified_supabase_user_can_complete_org_registration():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__, Organization.__table__, Membership.__table__, AuditEvent.__table__])
    with Session(engine) as db:
        user = User(email="new@example.com", full_name="New User", password_hash="unused", is_active=True)
        db.add(user); db.commit()
        result = complete_organization_registration(
            CompleteOrganizationRegistrationIn(organization_name="New Org", organization_slug="new-org"),
            user, db,
        )
        assert result["organization"]["slug"] == "new-org"
        assert db.query(Membership).filter_by(user_id=user.id, role="org_admin", is_active=True).count() == 1
    engine.dispose()
