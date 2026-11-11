from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.models import AuditEvent, Branch, Membership, Organization, User
from app.core.sacco_models import SaccoFinancialTransaction, SaccoLedgerEntry, SaccoMember
from app.core.sacco_schemas import SaccoFinancialTransactionIn, SaccoWithdrawalDecisionIn


def _database():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[
        User.__table__, Organization.__table__, Membership.__table__, Branch.__table__,
        AuditEvent.__table__, SaccoMember.__table__,
        SaccoFinancialTransaction.__table__, SaccoLedgerEntry.__table__,
    ])
    return engine, Session(engine)


def _seed(db: Session, *, status="active", branch_id=None):
    creator = User(email="sacco-creator@example.test", full_name="Creator", password_hash="unused")
    manager = User(email="sacco-manager@example.test", full_name="Manager", password_hash="unused")
    approver = User(email="sacco-approver@example.test", full_name="Approver", password_hash="unused")
    organization = Organization(name="SACCO", slug="sacco-ledger-test", currency="KES")
    db.add_all([creator, manager, approver, organization])
    db.flush()
    if branch_id:
        db.add(Branch(id=branch_id, organization_id=organization.id, code=branch_id.upper(),
                      name="Test branch", is_active=True))
        db.flush()
    member = SaccoMember(
        organization_id=organization.id, branch_id=branch_id,
        member_number="MEM-0001", full_name="Jane Member", email=None,
        phone="+254700000001", identity_fingerprint="a" * 64,
        identity_ciphertext="encrypted-test-payload", status=status,
        review_note="", reviewed_by=None, reviewed_at=None, created_by=creator.id,
        idempotency_key="member-create-0001", request_fingerprint="b" * 64,
    )
    db.add(member)
    db.commit()
    return creator, manager, approver, organization, member


def _membership(organization_id, role, branch_scope="*"):
    return SimpleNamespace(
        organization_id=organization_id, role=role, branch_scope=branch_scope,
    )


def _transaction(*, account_type="savings", transaction_type="deposit", amount="100.00",
                 reference="receipt-001", key="sacco-txn-0001"):
    return SaccoFinancialTransactionIn(
        account_type=account_type, transaction_type=transaction_type,
        amount=amount, reference=reference, idempotency_key=key,
    )


def test_sacco_financial_contract_restricts_account_transaction_combinations():
    assert _transaction().amount == Decimal("100.00")
    assert _transaction(account_type="shares", transaction_type="share_contribution").account_type == "shares"
    with pytest.raises(ValidationError):
        _transaction(account_type="shares", transaction_type="withdrawal")
    with pytest.raises(ValidationError):
        _transaction(account_type="savings", transaction_type="share_contribution")
    with pytest.raises(ValidationError):
        _transaction(amount="0.00")
    with pytest.raises(ValidationError):
        _transaction(amount="1.001")


def test_savings_deposit_and_withdrawal_require_four_eyes_and_preserve_ledger():
    from app.api.sacco import create_member_transaction, decide_member_withdrawal, member_balances

    engine, db = _database()
    try:
        creator, manager, approver, org, member = _seed(db)
        treasurer = _membership(org.id, "sacco_treasurer")
        manager_role = _membership(org.id, "sacco_manager")
        deposit = create_member_transaction(
            member.id, _transaction(amount="500.00", key="sacco-deposit-0001"),
            creator, treasurer, db,
        )
        assert deposit["status"] == "posted"
        assert member_balances(member.id, treasurer, db)["savings_balance"] == "500.00"

        withdrawal = create_member_transaction(
            member.id, _transaction(transaction_type="withdrawal", amount="200.00",
                                    key="sacco-withdrawal-0001"),
            manager, manager_role, db,
        )
        assert withdrawal["status"] == "pending_approval"
        assert member_balances(member.id, treasurer, db)["savings_balance"] == "500.00"
        with pytest.raises(HTTPException) as self_approval:
            decide_member_withdrawal(
                withdrawal["id"],
                SaccoWithdrawalDecisionIn(decision="approve", note="Approve own request"),
                manager, manager_role, db,
            )
        assert self_approval.value.status_code == 403

        result = decide_member_withdrawal(
            withdrawal["id"],
            SaccoWithdrawalDecisionIn(decision="approve", note="Reviewed and approved"),
            approver, manager_role, db,
        )
        assert result["status"] == "posted" and result["decided_by"] == approver.id
        assert member_balances(member.id, treasurer, db)["savings_balance"] == "300.00"
        assert db.query(SaccoLedgerEntry).filter_by(member_id=member.id, account_type="savings").count() == 2
        with pytest.raises(HTTPException) as duplicate_decision:
            decide_member_withdrawal(
                withdrawal["id"],
                SaccoWithdrawalDecisionIn(decision="approve", note="Duplicate decision"),
                approver, manager_role, db,
            )
        assert duplicate_decision.value.status_code == 409
        assert db.query(AuditEvent).filter_by(action="sacco.withdrawal.approved").count() == 1
    finally:
        db.close()
        engine.dispose()


def test_share_contributions_are_separate_from_savings_and_cannot_be_withdrawn():
    from app.api.sacco import create_member_transaction, member_balances

    engine, db = _database()
    try:
        creator, manager, approver, org, member = _seed(db)
        treasurer = _membership(org.id, "sacco_treasurer")
        created = create_member_transaction(
            member.id,
            _transaction(account_type="shares", transaction_type="share_contribution",
                         amount="75.50", key="sacco-share-0001"),
            creator, treasurer, db,
        )
        assert created["status"] == "posted"
        balances = member_balances(member.id, treasurer, db)
        assert balances["savings_balance"] == "0.00"
        assert balances["share_balance"] == "75.50"
        assert db.query(SaccoLedgerEntry).filter_by(
            member_id=member.id, account_type="shares", signed_amount=Decimal("75.50")
        ).count() == 1
    finally:
        db.close()
        engine.dispose()


def test_withdrawal_insufficient_balance_and_rejection_do_not_change_ledger():
    from app.api.sacco import create_member_transaction, decide_member_withdrawal, member_balances

    engine, db = _database()
    try:
        creator, manager, approver, org, member = _seed(db)
        treasurer = _membership(org.id, "sacco_treasurer")
        manager_role = _membership(org.id, "sacco_manager")
        create_member_transaction(
            member.id, _transaction(amount="100.00", key="sacco-deposit-0002"),
            creator, treasurer, db,
        )
        withdrawal = create_member_transaction(
            member.id, _transaction(transaction_type="withdrawal", amount="150.00",
                                    key="sacco-withdrawal-0002"),
            creator, treasurer, db,
        )
        with pytest.raises(HTTPException) as insufficient:
            decide_member_withdrawal(
                withdrawal["id"],
                SaccoWithdrawalDecisionIn(decision="approve", note="Reviewed but not funded"),
                manager, manager_role, db,
            )
        assert insufficient.value.status_code == 409
        assert member_balances(member.id, treasurer, db)["savings_balance"] == "100.00"
        assert db.query(SaccoLedgerEntry).filter_by(member_id=member.id).count() == 1

        rejected = decide_member_withdrawal(
            withdrawal["id"],
            SaccoWithdrawalDecisionIn(decision="reject", note="Insufficient available funds"),
            manager, manager_role, db,
        )
        assert rejected["status"] == "rejected"
        assert member_balances(member.id, treasurer, db)["savings_balance"] == "100.00"
        assert db.query(SaccoLedgerEntry).filter_by(member_id=member.id).count() == 1
        assert db.query(AuditEvent).filter_by(action="sacco.withdrawal.rejected").count() == 1
    finally:
        db.close()
        engine.dispose()


def test_financial_idempotency_and_active_member_requirement():
    from app.api.sacco import create_member_transaction

    engine, db = _database()
    try:
        creator, manager, approver, org, member = _seed(db)
        treasurer = _membership(org.id, "sacco_treasurer")
        payload = _transaction(amount="25.00", key="sacco-idempotent-01")
        first = create_member_transaction(member.id, payload, creator, treasurer, db)
        replay = create_member_transaction(member.id, payload, creator, treasurer, db)
        assert first["id"] == replay["id"] and replay["replayed"] is True
        with pytest.raises(HTTPException) as conflict:
            create_member_transaction(
                member.id, _transaction(amount="26.00", key="sacco-idempotent-01"),
                creator, treasurer, db,
            )
        assert conflict.value.status_code == 409
        member.status = "suspended"
        db.commit()
        with pytest.raises(HTTPException) as suspended:
            create_member_transaction(
                member.id, _transaction(amount="1.00", key="sacco-suspended-01"),
                creator, treasurer, db,
            )
        assert suspended.value.status_code == 409
    finally:
        db.close()
        engine.dispose()


def test_financial_queries_and_decisions_enforce_tenant_and_branch_scope():
    from app.api.sacco import list_member_transactions, member_balances

    engine, db = _database()
    try:
        creator, manager, approver, org, member_a = _seed(db, branch_id="branch-a")
        branch_b = Branch(id="branch-b", organization_id=org.id, code="B", name="Branch B")
        db.add(branch_b)
        db.flush()
        member_b = SaccoMember(
            organization_id=org.id, branch_id="branch-b", member_number="MEM-0002",
            full_name="Branch B Member", email=None, phone="+254700000002",
            identity_fingerprint="c" * 64, identity_ciphertext="encrypted",
            status="active", created_by=creator.id, idempotency_key="member-create-0002",
            request_fingerprint="d" * 64,
        )
        db.add(member_b)
        other_org = Organization(name="Other SACCO", slug="other-sacco")
        db.add(other_org)
        db.commit()
        scoped = _membership(org.id, "sacco_auditor", "branch-a")
        with pytest.raises(HTTPException) as branch_denied:
            member_balances(member_b.id, scoped, db)
        assert branch_denied.value.status_code == 404
        with pytest.raises(HTTPException) as tenant_denied:
            list_member_transactions(member_a.id, membership=_membership(other_org.id, "sacco_auditor"), db=db)
        assert tenant_denied.value.status_code == 404
    finally:
        db.close()
        engine.dispose()


def test_financial_roles_are_least_privilege_and_routes_are_registered():
    from app.api.sacco import _require_sacco_permission
    from app.main import app

    with pytest.raises(HTTPException):
        _require_sacco_permission(_membership(1, "sacco_officer"), "deposit")
    with pytest.raises(HTTPException):
        _require_sacco_permission(_membership(1, "sacco_treasurer"), "approve_withdrawal")
    with pytest.raises(HTTPException):
        _require_sacco_permission(_membership(1, "sacco_auditor"), "share_contribute")

    paths = set(app.openapi()["paths"])
    assert "/api/v1/sacco/members/{member_id}/transactions" in paths
    assert "/api/v1/sacco/members/{member_id}/balances" in paths
    assert "/api/v1/sacco/transactions/{transaction_id}/decision" in paths


def test_sacco_ledger_migration_and_workspace_contracts():
    root = Path(__file__).resolve().parents[1]
    migration = root / "migrations" / "versions" / "0067_sacco_member_ledger.py"
    source = migration.read_text(encoding="utf-8")
    assert 'revision = "0067_sacco_member_ledger"' in source
    assert 'down_revision = "0066_sacco_membership_kyc"' in source
    assert "ENABLE ROW LEVEL SECURITY" in source and "FORCE ROW LEVEL SECURITY" in source
    assert "onecore_reject_sacco_ledger_mutation" in source
    page = (root / "app" / "web" / "sacco.html").read_text(encoding="utf-8")
    assert 'id="financial"' in page and 'id="balances"' in page
    assert "/sacco/members/" in page and "Powered by OneCore Technologies Ltd" in page
