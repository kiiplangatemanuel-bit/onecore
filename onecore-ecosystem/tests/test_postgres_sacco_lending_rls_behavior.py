"""Behavioral tenant isolation and immutable-ledger tests for SACCO lending."""
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
from app.core.sacco_models import (
    SaccoMember, SaccoLoanProduct, SaccoLoanApplication, SaccoLoanLedgerEntry,
)

CI_RUNTIME_ROLE = os.getenv("ONECORE_CI_RLS_ROLE", "").strip()
pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql" or not CI_RUNTIME_ROLE,
    reason="Requires the PostgreSQL CI runtime role provisioned by onecore-ci.yml",
)


def test_sacco_loan_tables_enforce_tenant_rls_and_append_only_ledger(monkeypatch):
    if not re.fullmatch(r"^[a-z_][a-z0-9_]{0,62}$", CI_RUNTIME_ROLE):
        pytest.fail("ONECORE_CI_RLS_ROLE must be a safe PostgreSQL role identifier")
    from app.core.config import settings
    from app.core.runtime_role import apply_runtime_database_role

    suffix = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    with engine.connect() as connection:
        transaction = connection.begin()
        user_a = connection.execute(insert(User).values(
            email=f"sacco-loan-rls-a-{suffix}@example.test", full_name="Loan A", phone="",
            password_hash="not-a-real-login-hash", is_active=True, platform_role="customer",
            auth_version=0, created_at=now,
        ).returning(User.id)).scalar_one()
        user_b = connection.execute(insert(User).values(
            email=f"sacco-loan-rls-b-{suffix}@example.test", full_name="Loan B", phone="",
            password_hash="not-a-real-login-hash", is_active=True, platform_role="customer",
            auth_version=0, created_at=now,
        ).returning(User.id)).scalar_one()
        org_a = connection.execute(insert(Organization).values(
            name=f"Loan A {suffix}", slug=f"loan-a-{suffix}", owner_user_id=user_a,
            industry="finance", country="KE", currency="KES", timezone="Africa/Nairobi",
            is_active=True, created_at=now,
        ).returning(Organization.id)).scalar_one()
        org_b = connection.execute(insert(Organization).values(
            name=f"Loan B {suffix}", slug=f"loan-b-{suffix}", owner_user_id=user_b,
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
            organization_id=org_a, branch_id=None, member_number=f"LA-{suffix[:12]}",
            full_name="Loan Member A", email=None, phone="+254700000031",
            identity_fingerprint="1" * 64, identity_ciphertext="cipher-a", status="active",
            review_note="", reviewed_by=None, reviewed_at=None, created_by=user_a,
            idempotency_key=f"loan-member-a-{suffix}", request_fingerprint="2" * 64,
            created_at=now, updated_at=now,
        ).returning(SaccoMember.id)).scalar_one()
        member_b = connection.execute(insert(SaccoMember).values(
            organization_id=org_b, branch_id=None, member_number=f"LB-{suffix[:12]}",
            full_name="Loan Member B", email=None, phone="+254700000032",
            identity_fingerprint="3" * 64, identity_ciphertext="cipher-b", status="active",
            review_note="", reviewed_by=None, reviewed_at=None, created_by=user_b,
            idempotency_key=f"loan-member-b-{suffix}", request_fingerprint="4" * 64,
            created_at=now, updated_at=now,
        ).returning(SaccoMember.id)).scalar_one()

        product_a = connection.execute(insert(SaccoLoanProduct).values(
            organization_id=org_a, code=f"PROD-{suffix[:8]}", name="Product A", currency="KES",
            min_amount=Decimal("1000.00"), max_amount=Decimal("10000.00"),
            annual_interest_rate=Decimal("12.0000"), min_term_months=3, max_term_months=12,
            max_debt_service_ratio=Decimal("0.4000"), is_active=True, created_by=user_a,
            created_at=now, updated_at=now,
        ).returning(SaccoLoanProduct.id)).scalar_one()
        product_b = connection.execute(insert(SaccoLoanProduct).values(
            organization_id=org_b, code=f"PROD-{suffix[8:16]}", name="Product B", currency="KES",
            min_amount=Decimal("1000.00"), max_amount=Decimal("10000.00"),
            annual_interest_rate=Decimal("12.0000"), min_term_months=3, max_term_months=12,
            max_debt_service_ratio=Decimal("0.4000"), is_active=True, created_by=user_b,
            created_at=now, updated_at=now,
        ).returning(SaccoLoanProduct.id)).scalar_one()
        loan_a = connection.execute(insert(SaccoLoanApplication).values(
            organization_id=org_a, member_id=member_a, product_id=product_a, branch_id=None,
            requested_amount=Decimal("1000.00"), term_months=12,
            annual_interest_rate=Decimal("12.0000"), max_debt_service_ratio=Decimal("0.4000"),
            purpose="Working capital", status="disbursed", created_by=user_a,
            idempotency_key=f"loan-app-a-{suffix}", request_fingerprint="5" * 64,
            decision_by=user_a, decided_at=now, disbursed_by=user_a, disbursed_at=now,
            created_at=now, updated_at=now,
        ).returning(SaccoLoanApplication.id)).scalar_one()
        loan_b = connection.execute(insert(SaccoLoanApplication).values(
            organization_id=org_b, member_id=member_b, product_id=product_b, branch_id=None,
            requested_amount=Decimal("1000.00"), term_months=12,
            annual_interest_rate=Decimal("12.0000"), max_debt_service_ratio=Decimal("0.4000"),
            purpose="Working capital", status="disbursed", created_by=user_b,
            idempotency_key=f"loan-app-b-{suffix}", request_fingerprint="6" * 64,
            decision_by=user_b, decided_at=now, disbursed_by=user_b, disbursed_at=now,
            created_at=now, updated_at=now,
        ).returning(SaccoLoanApplication.id)).scalar_one()
        entry_a = connection.execute(insert(SaccoLoanLedgerEntry).values(
            organization_id=org_a, loan_application_id=loan_a, member_id=member_a,
            branch_id=None, entry_type="disbursement", amount=Decimal("1000.00"),
            principal_delta=Decimal("1000.00"), interest_delta=Decimal("120.00"),
            currency="KES", reference="A", idempotency_key=f"loan-ledger-a-{suffix}",
            request_fingerprint="7" * 64, created_by=user_a, created_at=now,
        ).returning(SaccoLoanLedgerEntry.id)).scalar_one()
        entry_b = connection.execute(insert(SaccoLoanLedgerEntry).values(
            organization_id=org_b, loan_application_id=loan_b, member_id=member_b,
            branch_id=None, entry_type="disbursement", amount=Decimal("1000.00"),
            principal_delta=Decimal("1000.00"), interest_delta=Decimal("120.00"),
            currency="KES", reference="B", idempotency_key=f"loan-ledger-b-{suffix}",
            request_fingerprint="8" * 64, created_by=user_b, created_at=now,
        ).returning(SaccoLoanLedgerEntry.id)).scalar_one()

        monkeypatch.setattr(settings, "app_env", "production")
        monkeypatch.setenv("ONECORE_DATABASE_RUNTIME_ROLE", CI_RUNTIME_ROLE)
        assert apply_runtime_database_role(connection) == CI_RUNTIME_ROLE
        flags = connection.execute(text(
            "SELECT r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user"
        )).one()
        assert flags[0] is False and flags[1] is False
        connection.execute(text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": str(user_a)})

        for table, id_a, id_b in (
            ("sacco_loan_products", product_a, product_b),
            ("sacco_loan_applications", loan_a, loan_b),
            ("sacco_loan_ledger_entries", entry_a, entry_b),
        ):
            visible = set(connection.execute(
                text(f"SELECT id FROM {table} WHERE id IN (:a, :b)"),
                {"a": id_a, "b": id_b},
            ).scalars().all())
            assert visible == {id_a}
            assert connection.execute(
                text(f"UPDATE {table} SET organization_id = organization_id WHERE id = :id"),
                {"id": id_b},
            ).rowcount == 0

        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(insert(SaccoLoanProduct).values(
                    organization_id=org_b, code=f"FORBID-{suffix[:8]}", name="Forbidden",
                    currency="KES", min_amount=Decimal("1.00"), max_amount=Decimal("10.00"),
                    annual_interest_rate=Decimal("0.0000"), min_term_months=1, max_term_months=2,
                    max_debt_service_ratio=Decimal("0.4000"), is_active=True, created_by=user_a,
                    created_at=now, updated_at=now,
                ))
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(insert(SaccoLoanApplication).values(
                    organization_id=org_b, member_id=member_b, product_id=product_b, branch_id=None,
                    requested_amount=Decimal("1000.00"), term_months=12,
                    annual_interest_rate=Decimal("12.0000"), max_debt_service_ratio=Decimal("0.4000"),
                    purpose="Forbidden application", status="submitted", created_by=user_a,
                    idempotency_key=f"forbidden-app-{suffix}", request_fingerprint="9" * 64,
                    created_at=now, updated_at=now,
                ))
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(insert(SaccoLoanLedgerEntry).values(
                    organization_id=org_b, loan_application_id=loan_b, member_id=member_b,
                    branch_id=None, entry_type="repayment", amount=Decimal("1.00"),
                    principal_delta=Decimal("-1.00"), interest_delta=Decimal("0.00"),
                    currency="KES", reference="Forbidden", idempotency_key=f"forbidden-ledger-{suffix}",
                    request_fingerprint="a" * 64, created_by=user_a, created_at=now,
                ))

        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    text("UPDATE sacco_loan_ledger_entries SET reference = 'tampered' WHERE id = :id"),
                    {"id": entry_a},
                )
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    text("DELETE FROM sacco_loan_ledger_entries WHERE id = :id"),
                    {"id": entry_a},
                )

        connection.execute(text("RESET ROLE"))
        connection.execute(delete(SaccoLoanLedgerEntry).where(SaccoLoanLedgerEntry.id.in_([entry_a, entry_b])))
        connection.execute(delete(SaccoLoanApplication).where(SaccoLoanApplication.id.in_([loan_a, loan_b])))
        connection.execute(delete(SaccoLoanProduct).where(SaccoLoanProduct.id.in_([product_a, product_b])))
        connection.execute(delete(SaccoMember).where(SaccoMember.id.in_([member_a, member_b])))
        connection.execute(delete(Membership).where(Membership.id.in_([membership_a, membership_b])))
        connection.execute(delete(Organization).where(Organization.id.in_([org_a, org_b])))
        connection.execute(delete(User).where(User.id.in_([user_a, user_b])))
        transaction.commit()
