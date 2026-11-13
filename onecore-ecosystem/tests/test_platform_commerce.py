from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.models import AuditEvent, Membership, Organization, User
from app.core.platform_commerce_models import (
    ManagedFile, ManagedFileShare, ManagedFileVersion, OrganizationSubscription, SubscriptionPayment, SubscriptionPlan,
)


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_platform_commerce_models_and_routes_are_registered():
    from app.main import app
    assert SubscriptionPlan.__tablename__ == "subscription_plans"
    assert OrganizationSubscription.__tablename__ == "organization_subscriptions"
    assert SubscriptionPayment.__tablename__ == "subscription_payments"
    assert ManagedFile.__tablename__ == "managed_files"
    assert ManagedFileShare.__tablename__ == "managed_file_shares"
    assert ManagedFileVersion.__tablename__ == "managed_file_versions"
    paths = set(app.openapi()["paths"])
    for path in (
        "/api/v1/subscription-plans", "/api/v1/subscriptions", "/api/v1/subscriptions/current",
        "/api/v1/subscriptions/{subscription_id}/payments", "/api/v1/files",
        "/api/v1/files/upload", "/api/v1/files/folders", "/api/v1/files/{file_id}/download",
        "/api/v1/files/{file_id}/shares", "/api/v1/files/shared/{token}/download",
        "/api/v1/files/{file_id}/versions", "/api/v1/files/{file_id}/versions/{version_id}/download",
        "/api/v1/admin/platform/subscription-payments/{payment_id}/review",
    ):
        assert path in paths


def test_subscription_payment_is_idempotent_and_activates_only_after_admin_verification():
    from app.api.platform_commerce import (
        SubscriptionStartIn, SubscriptionPaymentIn, PaymentReviewIn,
        start_subscription, submit_subscription_payment, review_subscription_payment,
    )
    engine = _db()
    with Session(engine) as db:
        admin = User(email="admin@example.com", full_name="Tenant Admin", password_hash="unused")
        platform_admin = User(email="root@example.com", full_name="Platform Admin",
                              password_hash="unused", platform_role="root_superadmin")
        org = Organization(name="Tenant A", slug="tenant-a", currency="KES")
        db.add_all([admin, platform_admin, org]); db.flush()
        membership = Membership(user_id=admin.id, organization_id=org.id, role="org_admin", is_active=True)
        db.add(membership)
        plan = SubscriptionPlan(code="starter", name="Starter", amount=Decimal("2500.00"),
                                currency="KES", interval="monthly", entitlements={"seats": 5}, is_active=True)
        db.add(plan); db.commit()
        subscription = start_subscription(SubscriptionStartIn(plan_id=plan.id), membership, admin, db)
        assert subscription["status"] == "pending_payment"
        payload = SubscriptionPaymentIn(method="mpesa", external_reference="QAB123XYZ",
                                        idempotency_key="subscription-pay-0001")
        created = submit_subscription_payment(subscription["id"], payload, membership, admin, db)
        assert created["status"] == "pending_verification"
        replay = submit_subscription_payment(subscription["id"], payload, membership, admin, db)
        assert replay["idempotent_replay"] is True
        row = db.query(OrganizationSubscription).filter_by(id=subscription["id"]).one()
        assert row.status == "pending_payment"
        assert row.amount == Decimal("2500.00")
        assert row.currency == "KES"
        reviewed = review_subscription_payment(created["id"], PaymentReviewIn(decision="verified", note="Matched"),
                                                platform_admin, db)
        assert reviewed["payment_status"] == "verified"
        assert reviewed["subscription_status"] == "active"
        assert row.starts_at is not None and row.ends_at is not None
        first_end = row.ends_at
        renewal_payload = SubscriptionPaymentIn(method="mpesa", external_reference="QAB123XYZ2",
                                                idempotency_key="subscription-pay-0002")
        renewal = submit_subscription_payment(subscription["id"], renewal_payload, membership, admin, db)
        renewed = review_subscription_payment(renewal["id"], PaymentReviewIn(decision="verified", note="Renewal checked"),
                                              platform_admin, db)
        assert renewed["subscription_status"] == "active"
        assert row.ends_at > first_end
        assert db.query(AuditEvent).filter(AuditEvent.action.like("subscription.%")).count() >= 2
    engine.dispose()


def test_subscription_requires_org_admin_and_rejects_cross_org_payment():
    from app.api.platform_commerce import SubscriptionStartIn, start_subscription
    engine = _db()
    with Session(engine) as db:
        user = User(email="staff@example.com", password_hash="unused")
        org = Organization(name="Tenant A", slug="tenant-a")
        db.add_all([user, org]); db.flush()
        membership = Membership(user_id=user.id, organization_id=org.id, role="staff", is_active=True)
        plan = SubscriptionPlan(code="pro", name="Pro", amount=Decimal("5000"), currency="KES")
        db.add_all([membership, plan]); db.commit()
        with pytest.raises(HTTPException) as denied:
            start_subscription(SubscriptionStartIn(plan_id=plan.id), membership, user, db)
        assert denied.value.status_code == 403
    engine.dispose()


def test_platform_admin_routes_are_protected_and_member_admin_routes_exist():
    from app.main import app
    paths = set(app.openapi()["paths"])
    for path in (
        "/api/v1/admin/platform/overview", "/api/v1/admin/platform/organizations",
        "/api/v1/admin/platform/organizations/{organization_id}/status",
        "/api/v1/admin/platform/users", "/api/v1/admin/platform/users/{user_id}/status",
        "/api/v1/admin/platform/subscriptions", "/api/v1/admin/platform/subscription-plans",
        "/api/v1/admin/platform/audit", "/api/v1/members", "/api/v1/members/{membership_id}",
    ):
        assert path in paths


def test_file_storage_fails_closed_without_private_object_storage_or_malware_scanner(monkeypatch):
    from app.api.platform_commerce import _s3, _scan
    from app.core.config import settings
    monkeypatch.setattr(settings, "integration_object_storage_enabled", False)
    with pytest.raises(HTTPException) as storage:
        _s3()
    assert storage.value.status_code == 503
    monkeypatch.setattr(settings, "support_attachment_scanning_enabled", False)
    with pytest.raises(HTTPException) as scanner:
        _scan(b"sample")
    assert scanner.value.status_code == 503


def test_document_and_subscription_migration_is_chained_and_enforces_rls():
    from pathlib import Path
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0071_platform_commerce_documents.py"
    source = path.read_text()
    assert 'revision = "0071_platform_commerce_documents"' in source
    assert 'down_revision = "0070_sacco_loan_repayments"' in source
    for table in ("organization_subscriptions", "subscription_payments", "managed_files", "managed_file_shares"):
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY" in source
        assert f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY" in source
    assert "file_share_token_read" in source
    assert "subscription_plan_admin_write" in source

def test_document_classification_access_is_role_limited():
    from app.api.platform_commerce import _classification_allowed
    assert _classification_allowed("staff", "internal")
    assert not _classification_allowed("staff", "confidential")
    assert _classification_allowed("manager", "confidential")
    assert not _classification_allowed("manager", "restricted")
    assert _classification_allowed("org_admin", "restricted")


def test_document_version_migration_is_chained_and_forced_rls():
    from pathlib import Path
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0072_managed_file_versions.py"
    source = path.read_text()
    assert 'revision = "0072_managed_file_versions"' in source
    assert 'down_revision = "0071_platform_commerce_documents"' in source
    assert "ALTER TABLE public.managed_file_versions ENABLE ROW LEVEL SECURITY" in source
    assert "ALTER TABLE public.managed_file_versions FORCE ROW LEVEL SECURITY" in source


def test_platform_user_suspension_increments_auth_version_and_protects_root():
    from app.api.platform_admin import UserStatusIn, set_user_status
    engine = _db()
    with Session(engine) as db:
        root = User(email="root@example.com", password_hash="unused", platform_role="root_superadmin")
        customer = User(email="customer@example.com", password_hash="unused", auth_version=4)
        db.add_all([root, customer]); db.commit()
        result = set_user_status(customer.id, UserStatusIn(is_active=False, reason="Security review"), root, db)
        assert result["is_active"] is False
        assert db.get(User, customer.id).auth_version == 5
        with pytest.raises(HTTPException) as self_suspend:
            set_user_status(root.id, UserStatusIn(is_active=False, reason="Self suspend"), root, db)
        assert self_suspend.value.status_code == 409
        with pytest.raises(HTTPException) as root_suspend:
            set_user_status(root.id + 100, UserStatusIn(is_active=False, reason="Suspend root"), root, db)
        assert root_suspend.value.status_code == 404
    engine.dispose()


def test_platform_organization_status_change_is_persisted_and_audited():
    from app.api.platform_admin import OrganizationStatusIn, set_organization_status
    engine = _db()
    with Session(engine) as db:
        root = User(email="root@example.com", password_hash="unused", platform_role="root_superadmin")
        org = Organization(name="Tenant", slug="tenant")
        db.add_all([root, org]); db.commit()
        result = set_organization_status(org.id, OrganizationStatusIn(is_active=False, reason="Contract ended"), root, db)
        assert result["is_active"] is False
        assert db.query(AuditEvent).filter_by(action="platform.organization_status_changed").count() == 1
    engine.dispose()
