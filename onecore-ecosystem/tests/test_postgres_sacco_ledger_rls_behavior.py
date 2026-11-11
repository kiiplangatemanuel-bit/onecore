"""Behavioral tenant-isolation and append-only tests for the SACCO ledger."""
import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, insert, text
from sqlalchemy.exc import DBAPIError

from app.core.database import engine
from app.core.models import Membership, Organization, User
from app.core.sacco_models import SaccoFinancialTransaction, SaccoLedgerEntry, SaccoMember

CI_RUNTIME_ROLE = os.getenv("ONECORE_CI_RLS_ROLE", "").strip()
pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql" or not CI_RUNTIME_ROLE,
    reason="Requires the PostgreSQL CI runtime role provisioned by onecore-ci.yml",
)


def test_sacco_member_rls_blocks_cross_tenant_reads_and_writes(monkeypatch):
    if not re.fullmatch(r"^[a-z_][a-z0-9_]{0,62}$", CI_RUNTIME_ROLE):
        pytest.fail("ONECORE_CI_RLS_ROLE must be a safe PostgreSQL role identifier")
    from app.core.config import settings
    from app.core.runtime_role import apply_runtime_database_role

    suffix = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        user_a = connection.execute(insert(User).values(
            email=f"sacco-rls-a-{suffix}@example.test", full_name="SACCO A", phone="",
            password_hash="not-a-real-login-hash", is_active=True, platform_role="customer",
            auth_version=0, created_at=now,
        ).returning(User.id)).scalar_one()
        user_b = connection.execute(insert(User).values(
            email=f"sacco-rls-b-{suffix}@example.test", full_name="SACCO B", phone="",
            password_hash="not-a-real-login-hash", is_active=True, platform_role="customer",
            auth_version=0, created_at=now,
        ).returning(User.id)).scalar_one()
        org_a = connection.execute(insert(Organization).values(
            name=f"SACCO A {suffix}", slug=f"sacco-a-{suffix}", owner_user_id=user_a,
            industry="finance", country="KE", currency="KES", timezone="Africa/Nairobi",
            is_active=True, created_at=now,
        ).returning(Organization.id)).scalar_one()
        org_b = connection.execute(insert(Organization).values(
            name=f"SACCO B {suffix}", slug=f"sacco-b-{suffix}", owner_user_id=user_b,
            industry="finance", country="KE", currency="KES", timezone="Africa/Nairobi",
            is_active=True, created_at=now,
        ).returning(Organization.id)).scalar_one()
        membership_a = connection.execute(insert(Membership).values(
            user_id=user_a, organization_id=org_a, role="org_admin", branch_scope="*", is_active=True,
        ).returning(Membership.id)).scalar_one()
        membership_b = connection.execute(insert(Membership).values(
            user_id=user_b, organization_id=org_b, role="org_admin", branch_scope="*", is_active=True,
        ).returning(Membership.id)).scalar_one()
        member_a = connection.execute(insert(SaccoMember).values(
            organization_id=org_a, branch_id=None, member_number=f"A-{suffix[:12]}",
            full_name="Member A", email=None, phone="+254700000001",
            identity_fingerprint="a" * 64, identity_ciphertext="cipher-a", status="active",
            review_note="", reviewed_by=None, reviewed_at=None, created_by=user_a,
            idempotency_key=f"key-a-{suffix}", request_fingerprint="b" * 64,
            created_at=now, updated_at=now,
        ).returning(SaccoMember.id)).scalar_one()
        member_b = connection.execute(insert(SaccoMember).values(
            organization_id=org_b, branch_id=None, member_number=f"B-{suffix[:12]}",
            full_name="Member B", email=None, phone="+254700000002",
            identity_fingerprint="c" * 64, identity_ciphertext="cipher-b", status="active",
            review_note="", reviewed_by=None, reviewed_at=None, created_by=user_b,
            idempotency_key=f"key-b-{suffix}", request_fingerprint="d" * 64,
            created_at=now, updated_at=now,
        ).returning(SaccoMember.id)).scalar_one()

        monkeypatch.setattr(settings, "app_env", "production")
        monkeypatch.setenv("ONECORE_DATABASE_RUNTIME_ROLE", CI_RUNTIME_ROLE)
        assert apply_runtime_database_role(connection) == CI_RUNTIME_ROLE
        flags = connection.execute(text("""
            SELECT r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user
        """)).one()
        assert flags[0] is False and flags[1] is False
        connection.execute(text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": str(user_a)})
        visible = set(connection.execute(
            text("SELECT id FROM sacco_members WHERE id IN (:a, :b)"),
            {"a": member_a, "b": member_b},
        ).scalars().all())
        assert visible == {member_a}
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(insert(SaccoMember).values(
                    organization_id=org_b, branch_id=None, member_number=f"X-{suffix[:12]}",
                    full_name="Forbidden", email=None, phone="+254700000003",
                    identity_fingerprint="e" * 64, identity_ciphertext="cipher-x", status="active",
                    review_note="", created_by=user_a, idempotency_key=f"key-x-{suffix}",
                    request_fingerprint="f" * 64, created_at=now, updated_at=now,
                ))
        assert connection.execute(
            text("UPDATE sacco_members SET status = 'suspended' WHERE id = :id"), {"id": member_b}
        ).rowcount == 0
        connection.execute(text("RESET ROLE"))
        connection.execute(delete(SaccoMember).where(SaccoMember.id.in_([member_a, member_b])))
        connection.execute(delete(Membership).where(Membership.id.in_([membership_a, membership_b])))
        connection.execute(delete(Organization).where(Organization.id.in_([org_a, org_b])))
        connection.execute(delete(User).where(User.id.in_([user_a, user_b])))


def test_sacco_financial_rls_and_ledger_immutability(monkeypatch):
    if not re.fullmatch(r"^[a-z_][a-z0-9_]{0,62}$", CI_RUNTIME_ROLE):
        pytest.fail("ONECORE_CI_RLS_ROLE must be a safe PostgreSQL role identifier")
    from app.core.config import settings
    from app.core.runtime_role import apply_runtime_database_role

    suffix = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    with engine.connect() as connection:
        transaction = connection.begin()
        user_a = connection.execute(insert(User).values(
            email=f"sacco-fin-a-{suffix}@example.test", full_name="SACCO A", phone="",
            password_hash="not-a-real-login-hash", is_active=True, platform_role="customer",
            auth_version=0, created_at=now,
        ).returning(User.id)).scalar_one()
        user_b = connection.execute(insert(User).values(
            email=f"sacco-fin-b-{suffix}@example.test", full_name="SACCO B", phone="",
            password_hash="not-a-real-login-hash", is_active=True, platform_role="customer",
            auth_version=0, created_at=now,
        ).returning(User.id)).scalar_one()
        org_a = connection.execute(insert(Organization).values(
            name=f"SACCO Fin A {suffix}", slug=f"sacco-fin-a-{suffix}", owner_user_id=user_a,
            industry="finance", country="KE", currency="KES", timezone="Africa/Nairobi",
            is_active=True, created_at=now,
        ).returning(Organization.id)).scalar_one()
        org_b = connection.execute(insert(Organization).values(
            name=f"SACCO Fin B {suffix}", slug=f"sacco-fin-b-{suffix}", owner_user_id=user_b,
            industry="finance", country="KE", currency="KES", timezone="Africa/Nairobi",
            is_active=True, created_at=now,
        ).returning(Organization.id)).scalar_one()
        membership_a = connection.execute(insert(Membership).values(
            user_id=user_a, organization_id=org_a, role="org_admin", branch_scope="*", is_active=True,
        ).returning(Membership.id)).scalar_one()
        membership_b = connection.execute(insert(Membership).values(
            user_id=user_b, organization_id=org_b, role="org_admin", branch_scope="*", is_active=True,
        ).returning(Membership.id)).scalar_one()
        member_a = connection.execute(insert(SaccoMember).values(
            organization_id=org_a, branch_id=None, member_number=f"FA-{suffix[:12]}",
            full_name="Financial A", email=None, phone="+254700000011",
            identity_fingerprint="1" * 64, identity_ciphertext="cipher-a", status="active",
            review_note="", reviewed_by=None, reviewed_at=None, created_by=user_a,
            idempotency_key=f"fin-member-a-{suffix}", request_fingerprint="2" * 64,
            created_at=now, updated_at=now,
        ).returning(SaccoMember.id)).scalar_one()
        member_b = connection.execute(insert(SaccoMember).values(
            organization_id=org_b, branch_id=None, member_number=f"FB-{suffix[:12]}",
            full_name="Financial B", email=None, phone="+254700000012",
            identity_fingerprint="3" * 64, identity_ciphertext="cipher-b", status="active",
            review_note="", reviewed_by=None, reviewed_at=None, created_by=user_b,
            idempotency_key=f"fin-member-b-{suffix}", request_fingerprint="4" * 64,
            created_at=now, updated_at=now,
        ).returning(SaccoMember.id)).scalar_one()

        transaction_a = connection.execute(insert(SaccoFinancialTransaction).values(
            organization_id=org_a, member_id=member_a, branch_id=None,
            account_type="savings", transaction_type="deposit", amount=Decimal("100.00"),
            currency="KES", reference="A", status="posted", idempotency_key=f"fin-a-{suffix}",
            request_fingerprint="5" * 64, created_by=user_a, decided_by=None,
            decided_at=None, decision_note="", created_at=now, updated_at=now,
        ).returning(SaccoFinancialTransaction.id)).scalar_one()
        transaction_b = connection.execute(insert(SaccoFinancialTransaction).values(
            organization_id=org_b, member_id=member_b, branch_id=None,
            account_type="savings", transaction_type="deposit", amount=Decimal("200.00"),
            currency="KES", reference="B", status="posted", idempotency_key=f"fin-b-{suffix}",
            request_fingerprint="6" * 64, created_by=user_b, decided_by=None,
            decided_at=None, decision_note="", created_at=now, updated_at=now,
        ).returning(SaccoFinancialTransaction.id)).scalar_one()
        ledger_a = connection.execute(insert(SaccoLedgerEntry).values(
            organization_id=org_a, member_id=member_a, transaction_id=transaction_a,
            branch_id=None, account_type="savings", signed_amount=Decimal("100.00"),
            currency="KES", reference="A", created_by=user_a, created_at=now,
        ).returning(SaccoLedgerEntry.id)).scalar_one()
        ledger_b = connection.execute(insert(SaccoLedgerEntry).values(
            organization_id=org_b, member_id=member_b, transaction_id=transaction_b,
            branch_id=None, account_type="savings", signed_amount=Decimal("200.00"),
            currency="KES", reference="B", created_by=user_b, created_at=now,
        ).returning(SaccoLedgerEntry.id)).scalar_one()

        monkeypatch.setattr(settings, "app_env", "production")
        monkeypatch.setenv("ONECORE_DATABASE_RUNTIME_ROLE", CI_RUNTIME_ROLE)
        assert apply_runtime_database_role(connection) == CI_RUNTIME_ROLE
        connection.execute(text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": str(user_a)})

        visible_transactions = set(connection.execute(
            text("SELECT id FROM sacco_financial_transactions WHERE id IN (:a, :b)"),
            {"a": transaction_a, "b": transaction_b},
        ).scalars().all())
        visible_ledger = set(connection.execute(
            text("SELECT id FROM sacco_ledger_entries WHERE id IN (:a, :b)"),
            {"a": ledger_a, "b": ledger_b},
        ).scalars().all())
        assert visible_transactions == {transaction_a}
        assert visible_ledger == {ledger_a}

        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(insert(SaccoFinancialTransaction).values(
                    organization_id=org_b, member_id=member_b, branch_id=None,
                    account_type="savings", transaction_type="deposit", amount=Decimal("1.00"),
                    currency="KES", reference="cross-tenant", status="posted",
                    idempotency_key=f"forbidden-{suffix}", request_fingerprint="7" * 64,
                    created_by=user_a, created_at=now, updated_at=now,
                ))
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(insert(SaccoLedgerEntry).values(
                    organization_id=org_b, member_id=member_b, transaction_id=transaction_b,
                    branch_id=None, account_type="savings", signed_amount=Decimal("1.00"),
                    currency="KES", reference="cross-tenant", created_by=user_a, created_at=now,
                ))
        assert connection.execute(
            text("UPDATE sacco_financial_transactions SET status = 'rejected' WHERE id = :id"),
            {"id": transaction_b},
        ).rowcount == 0
        assert connection.execute(
            text("UPDATE sacco_ledger_entries SET signed_amount = 0 WHERE id = :id"),
            {"id": ledger_b},
        ).rowcount == 0

        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    text("UPDATE sacco_ledger_entries SET signed_amount = 0 WHERE id = :id"),
                    {"id": ledger_a},
                )
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    text("DELETE FROM sacco_ledger_entries WHERE id = :id"),
                    {"id": ledger_a},
                )

        connection.execute(text("RESET ROLE"))
        transaction.rollback()
