"""PostgreSQL behavior tests for tenant isolation of SACCO loan origination tables."""
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import DBAPIError

from app.core.database import engine
from app.core.models import Membership, Organization, User
from app.core.sacco_models import SaccoMember
from app.core.sacco_loan_models import (
    SaccoLoanApplication, SaccoLoanCollateral, SaccoLoanDisbursement,
    SaccoLoanGuarantor, SaccoLoanInstallment, SaccoLoanProduct,
)

CI_RUNTIME_ROLE = os.getenv("ONECORE_CI_RLS_ROLE", "").strip()
pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql" or not CI_RUNTIME_ROLE,
    reason="Requires the PostgreSQL CI runtime role provisioned by onecore-ci.yml",
)


def test_sacco_loan_tables_block_cross_tenant_reads_and_writes(monkeypatch):
    if not re.fullmatch(r"^[a-z_][a-z0-9_]{0,62}$", CI_RUNTIME_ROLE):
        pytest.fail("ONECORE_CI_RLS_ROLE must be a safe PostgreSQL role identifier")
    from app.core.config import settings
    from app.core.runtime_role import apply_runtime_database_role

    suffix = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    due = date.today() + timedelta(days=30)
    with engine.connect() as connection:
        transaction = connection.begin()
        user_a = connection.execute(insert(User).values(
            email=f"loan-rls-a-{suffix}@example.test", full_name="Loan A", phone="",
            password_hash="not-a-real-login-hash", is_active=True, platform_role="customer",
            auth_version=0, created_at=now,
        ).returning(User.id)).scalar_one()
        user_b = connection.execute(insert(User).values(
            email=f"loan-rls-b-{suffix}@example.test", full_name="Loan B", phone="",
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
        connection.execute(insert(Membership).values(
            user_id=user_a, organization_id=org_a, role="org_admin", branch_scope="*", is_active=True,
        ))
        connection.execute(insert(Membership).values(
            user_id=user_b, organization_id=org_b, role="org_admin", branch_scope="*", is_active=True,
        ))
        member_a = connection.execute(insert(SaccoMember).values(
            organization_id=org_a, branch_id=None, member_number=f"LA-{suffix[:12]}",
            full_name="Loan Member A", email=None, phone="+254700000021",
            identity_fingerprint="a" * 64, identity_ciphertext="cipher-a", status="active",
            review_note="", reviewed_by=None, reviewed_at=None, created_by=user_a,
            idempotency_key=f"loan-member-a-{suffix}", request_fingerprint="b" * 64,
            created_at=now, updated_at=now,
        ).returning(SaccoMember.id)).scalar_one()
        member_b = connection.execute(insert(SaccoMember).values(
            organization_id=org_b, branch_id=None, member_number=f"LB-{suffix[:12]}",
            full_name="Loan Member B", email=None, phone="+254700000022",
            identity_fingerprint="c" * 64, identity_ciphertext="cipher-b", status="active",
            review_note="", reviewed_by=None, reviewed_at=None, created_by=user_b,
            idempotency_key=f"loan-member-b-{suffix}", request_fingerprint="d" * 64,
            created_at=now, updated_at=now,
        ).returning(SaccoMember.id)).scalar_one()

        def seed_tenant(organization_id, member_id, user_id, prefix):
            product_id = connection.execute(insert(SaccoLoanProduct).values(
                organization_id=organization_id, branch_id=None, code=f"{prefix}-{suffix[:8]}",
                name="Test loan", currency="KES", minimum_principal=Decimal("100.00"),
                maximum_principal=Decimal("10000.00"), annual_interest_rate_bps=1200,
                minimum_term_months=1, maximum_term_months=24, minimum_guarantors=0,
                maximum_debt_service_ratio_bps=4000, requires_collateral=False, is_active=True,
                created_by=user_id, created_at=now, updated_at=now,
            ).returning(SaccoLoanProduct.id)).scalar_one()
            application_id = connection.execute(insert(SaccoLoanApplication).values(
                organization_id=organization_id, product_id=product_id, member_id=member_id,
                branch_id=None, principal=Decimal("1000.00"), term_months=12,
                purpose="Test tenant loan application", monthly_net_income=Decimal("50000.00"),
                monthly_existing_debt=Decimal("0.00"), first_repayment_date=due,
                assessment_status="eligible", debt_service_ratio_bps=200,
                estimated_monthly_installment=Decimal("90.00"), assessment_note="Test assessment",
                assessed_by=user_id, assessed_at=now, status="pending_approval",
                decided_by=None, decided_at=None, decision_note="", created_by=user_id,
                idempotency_key=f"loan-app-{prefix}-{suffix}",
                request_fingerprint="e" * 64, created_at=now, updated_at=now,
            ).returning(SaccoLoanApplication.id)).scalar_one()
            guarantor_id = connection.execute(insert(SaccoLoanGuarantor).values(
                organization_id=organization_id, application_id=application_id,
                member_id=member_id, guaranteed_amount=Decimal("1000.00"),
                consent_status="accepted", consent_method="in_person_documented",
                consent_reference=f"FORM-{prefix}", consent_note="Consent evidence checked",
                consent_recorded_by=user_id, consent_at=now, created_by=user_id, created_at=now,
            ).returning(SaccoLoanGuarantor.id)).scalar_one()
            collateral_id = connection.execute(insert(SaccoLoanCollateral).values(
                organization_id=organization_id, application_id=application_id,
                collateral_type="equipment", description="Test equipment collateral",
                declared_value=Decimal("1500.00"), document_reference=f"DOC-{prefix}",
                status="verified", verification_note="Checked", verified_by=user_id,
                verified_at=now, created_by=user_id, created_at=now,
            ).returning(SaccoLoanCollateral.id)).scalar_one()
            installment_id = connection.execute(insert(SaccoLoanInstallment).values(
                organization_id=organization_id, application_id=application_id,
                installment_number=1, due_date=due, principal_due=Decimal("80.00"),
                interest_due=Decimal("10.00"), total_due=Decimal("90.00"),
                currency="KES", status="projected", created_at=now,
            ).returning(SaccoLoanInstallment.id)).scalar_one()
            disbursement_id = connection.execute(insert(SaccoLoanDisbursement).values(
                organization_id=organization_id, application_id=application_id,
                amount=Decimal("1000.00"), currency="KES", channel="bank_transfer",
                external_reference=f"DISBURSE-{prefix}-{suffix[:8]}", value_date=date.today(),
                status="pending_verification", request_note="RLS fixture disbursement evidence",
                requested_by=user_id, reviewed_by=None, reviewed_at=None, review_note="",
                idempotency_key=f"loan-disbursement-{prefix}-{suffix}",
                request_fingerprint="9" * 64, created_at=now, updated_at=now,
            ).returning(SaccoLoanDisbursement.id)).scalar_one()
            return product_id, application_id, guarantor_id, collateral_id, installment_id, disbursement_id

        a_ids = seed_tenant(org_a, member_a, user_a, "A")
        b_ids = seed_tenant(org_b, member_b, user_b, "B")

        monkeypatch.setattr(settings, "app_env", "production")
        monkeypatch.setenv("ONECORE_DATABASE_RUNTIME_ROLE", CI_RUNTIME_ROLE)
        assert apply_runtime_database_role(connection) == CI_RUNTIME_ROLE
        flags = connection.execute(text(
            "SELECT r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user"
        )).one()
        assert flags[0] is False and flags[1] is False
        connection.execute(text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": str(user_a)})

        models = [
            ("sacco_loan_products", a_ids[0], b_ids[0]),
            ("sacco_loan_applications", a_ids[1], b_ids[1]),
            ("sacco_loan_guarantors", a_ids[2], b_ids[2]),
            ("sacco_loan_collateral", a_ids[3], b_ids[3]),
            ("sacco_loan_installments", a_ids[4], b_ids[4]),
            ("sacco_loan_disbursements", a_ids[5], b_ids[5]),
        ]
        for table, visible_id, hidden_id in models:
            visible = set(connection.execute(
                text(f"SELECT id FROM {table} WHERE id IN (:a, :b)"),
                {"a": visible_id, "b": hidden_id},
            ).scalars().all())
            assert visible == {visible_id}, table
            assert connection.execute(
                text(f"UPDATE {table} SET organization_id = organization_id WHERE id = :id"),
                {"id": hidden_id},
            ).rowcount == 0, table

        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(insert(SaccoLoanProduct).values(
                    organization_id=org_b, branch_id=None, code=f"FORBIDDEN-{suffix[:8]}",
                    name="Cross tenant", currency="KES", minimum_principal=Decimal("100.00"),
                    maximum_principal=Decimal("1000.00"), annual_interest_rate_bps=0,
                    minimum_term_months=1, maximum_term_months=12, minimum_guarantors=0,
                    maximum_debt_service_ratio_bps=4000, requires_collateral=False, is_active=True,
                    created_by=user_a, created_at=now, updated_at=now,
                ))
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(insert(SaccoLoanApplication).values(
                    organization_id=org_b, product_id=b_ids[0], member_id=member_b,
                    branch_id=None, principal=Decimal("1000.00"), term_months=12,
                    purpose="Cross tenant application", monthly_net_income=Decimal("50000.00"),
                    monthly_existing_debt=Decimal("0.00"), first_repayment_date=due,
                    assessment_status="pending", status="pending_assessment",
                    created_by=user_a, idempotency_key=f"forbidden-app-{suffix}",
                    request_fingerprint="f" * 64, created_at=now, updated_at=now,
                ))
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(insert(SaccoLoanDisbursement).values(
                    organization_id=org_b, application_id=b_ids[1],
                    amount=Decimal("1000.00"), currency="KES", channel="bank_transfer",
                    external_reference=f"FORBIDDEN-{suffix}", value_date=date.today(),
                    status="pending_verification", request_note="Cross-tenant disbursement",
                    requested_by=user_a, reviewed_by=None, reviewed_at=None, review_note="",
                    idempotency_key=f"forbidden-disbursement-{suffix}",
                    request_fingerprint="8" * 64, created_at=now, updated_at=now,
                ))
        connection.execute(text("RESET ROLE"))
        transaction.rollback()
