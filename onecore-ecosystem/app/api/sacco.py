"""SACCO member onboarding, protected KYC review and savings/share ledger."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.authorization import branch_scope_ids, can_access_branch
from app.core.database import get_db
from app.core.models import AuditEvent, Branch, Membership, Organization, User
from app.core.sacco_models import (SaccoFinancialTransaction, SaccoLedgerEntry, SaccoMember, SaccoLoanProduct, SaccoLoanApplication, SaccoLoanLedgerEntry)
from app.core.sacco_schemas import (
    SaccoFinancialTransactionIn, SaccoKycReviewIn, SaccoMemberCreateIn,
    SaccoWithdrawalDecisionIn,
)
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.services.sacco_lending import calculate_debt_service_ratio, calculate_flat_loan_terms, allocate_repayment\nfrom app.services.sacco_membership import (
    KYCConfigurationError, decrypt_kyc_payload, encrypt_kyc_payload,
    identity_fingerprint, request_fingerprint, transaction_fingerprint,
)

router = APIRouter(prefix="/api/v1/sacco", tags=["sacco-membership-and-ledger"])
KYC_ACCESS_WINDOW = timedelta(minutes=30)
SACCO_ROLE_PERMISSIONS = {
    "org_admin": {"read", "create", "update", "review", "deposit", "withdraw", "share_contribute", "approve_withdrawal", "manage_loan_products", "create_loan", "assess_loan", "decide_loan", "disburse_loan", "repay_loan"},
    "sacco_manager": {"read", "create", "update", "review", "deposit", "withdraw", "share_contribute", "approve_withdrawal", "manage_loan_products", "create_loan", "assess_loan", "decide_loan", "disburse_loan", "repay_loan"},
    "sacco_officer": {"read", "create", "create_loan"},\n    "sacco_credit_officer": {"read", "create_loan", "assess_loan"},\n    "sacco_credit_approver": {"read", "decide_loan"},
    "sacco_kyc_approver": {"read", "review"},
    "sacco_treasurer": {"read", "create", "deposit", "withdraw", "share_contribute", "disburse_loan", "repay_loan"},
    "sacco_auditor": {"read"},
}


def _require_sacco_permission(membership: Membership, action: str) -> None:
    role = (membership.role or "").strip().lower()
    if action not in SACCO_ROLE_PERMISSIONS.get(role, set()):
        raise HTTPException(403, "Insufficient SACCO permissions")


def _require_kyc_approver(membership: Membership) -> None:
    _require_sacco_permission(membership, "review")


def _validate_branch(db: Session, membership: Membership, branch_id: str | None) -> None:
    allowed = branch_scope_ids(membership)
    if branch_id is None:
        if allowed is not None:
            raise HTTPException(403, "Select an authorized branch for this membership")
        return
    branch = db.query(Branch).filter_by(id=branch_id, organization_id=membership.organization_id, is_active=True).first()
    if not branch or not can_access_branch(membership, branch_id):
        raise HTTPException(404, "Branch not found")


def _member_query(db: Session, membership: Membership):
    query = db.query(SaccoMember).filter(SaccoMember.organization_id == membership.organization_id)
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            query = query.filter(SaccoMember.id == -1)
        else:
            query = query.filter(SaccoMember.branch_id.in_(allowed))
    return query


def _member_for_membership(
    db: Session, membership: Membership, member_id: int, *, for_update: bool = False
) -> SaccoMember:
    query = _member_query(db, membership).filter(SaccoMember.id == member_id)
    if for_update:
        query = query.with_for_update()
    row = query.first()
    if not row:
        raise HTTPException(404, "SACCO member not found")
    return row


def _member_out(row: SaccoMember, *, replayed: bool = False) -> dict:
    return {
        "id": row.id, "organization_id": row.organization_id, "branch_id": row.branch_id,
        "member_number": row.member_number, "full_name": row.full_name, "email": row.email,
        "phone": row.phone, "status": row.status, "review_note": row.review_note,
        "reviewed_by": row.reviewed_by, "reviewed_at": row.reviewed_at,
        "created_by": row.created_by, "created_at": row.created_at, "replayed": replayed,
    }


def _audit(db: Session, user: User, membership: Membership, action: str, member_id: int, detail: str = "") -> None:
    db.add(AuditEvent(
        organization_id=membership.organization_id, actor_user_id=user.id,
        action=action, resource_type="sacco_member", resource_id=str(member_id), detail=detail[:500],
    ))


def _audit_financial(
    db: Session, user: User, membership: Membership, action: str,
    transaction_id: int, detail: str = "",
) -> None:
    db.add(AuditEvent(
        organization_id=membership.organization_id, actor_user_id=user.id,
        action=action, resource_type="sacco_financial_transaction",
        resource_id=str(transaction_id), detail=detail[:500],
    ))


def _financial_out(row: SaccoFinancialTransaction, *, replayed: bool = False) -> dict:
    return {
        "id": row.id, "organization_id": row.organization_id, "member_id": row.member_id,
        "branch_id": row.branch_id, "account_type": row.account_type,
        "transaction_type": row.transaction_type, "amount": format(row.amount, ".2f"),
        "currency": row.currency, "reference": row.reference, "status": row.status,
        "created_by": row.created_by, "decided_by": row.decided_by,
        "decided_at": row.decided_at, "decision_note": row.decision_note,
        "created_at": row.created_at, "replayed": replayed,
    }


def _ledger_balance(db: Session, organization_id: int, member_id: int, account_type: str) -> Decimal:
    total = db.query(func.coalesce(func.sum(SaccoLedgerEntry.signed_amount), 0)).filter(
        SaccoLedgerEntry.organization_id == organization_id,
        SaccoLedgerEntry.member_id == member_id,
        SaccoLedgerEntry.account_type == account_type,
    ).scalar()
    return Decimal(str(total or "0")).quantize(Decimal("0.01"))


@router.post("/members", status_code=201)
def create_member(
    payload: SaccoMemberCreateIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_sacco_permission(membership, "create")
    _validate_branch(db, membership, payload.branch_id)
    safe_payload = payload.model_dump(mode="json", exclude={"idempotency_key"})
    try:
        identity_hash = identity_fingerprint(payload.national_id)
        request_hash = request_fingerprint(safe_payload)
        ciphertext = encrypt_kyc_payload({
            "national_id": payload.national_id,
            "date_of_birth": payload.date_of_birth.isoformat(),
            "postal_address": payload.postal_address,
        })
    except KYCConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc

    existing_key = db.query(SaccoMember).filter_by(
        organization_id=membership.organization_id, idempotency_key=payload.idempotency_key
    ).first()
    if existing_key:
        if existing_key.request_fingerprint != request_hash:
            raise HTTPException(409, "Idempotency key was already used for a different member request")
        return _member_out(existing_key, replayed=True)

    duplicate_number = db.query(SaccoMember).filter_by(
        organization_id=membership.organization_id, member_number=payload.member_number
    ).first()
    if duplicate_number:
        raise HTTPException(409, "Member number already exists in this organization")
    duplicate_identity = db.query(SaccoMember).filter_by(
        organization_id=membership.organization_id, identity_fingerprint=identity_hash
    ).first()
    if duplicate_identity:
        raise HTTPException(409, "A member with this identity number already exists in this organization")

    row = SaccoMember(
        organization_id=membership.organization_id, branch_id=payload.branch_id,
        member_number=payload.member_number, full_name=payload.full_name,
        email=str(payload.email).lower() if payload.email else None, phone=payload.phone,
        identity_fingerprint=identity_hash, identity_ciphertext=ciphertext,
        status="pending_kyc", created_by=user.id, idempotency_key=payload.idempotency_key,
        request_fingerprint=request_hash,
    )
    db.add(row)
    try:
        db.flush()
        _audit(db, user, membership, "sacco.member.created", row.id,
               f"member_number={row.member_number};branch_id={row.branch_id or ''};status=pending_kyc")
        db.commit()
        db.refresh(row)
        return _member_out(row)
    except IntegrityError:
        db.rollback()
        replay = db.query(SaccoMember).filter_by(
            organization_id=membership.organization_id, idempotency_key=payload.idempotency_key
        ).first()
        if replay and replay.request_fingerprint == request_hash:
            return _member_out(replay, replayed=True)
        raise HTTPException(409, "Member number, identity or idempotency key conflicts with an existing member")


@router.get("/members")
def list_members(
    status: str | None = Query(default=None, pattern=r"^(pending_kyc|active|rejected|suspended|exited)$"),
    branch_id: str | None = Query(default=None, min_length=1, max_length=36),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_sacco_permission(membership, "read")
    query = _member_query(db, membership)
    if branch_id:
        _validate_branch(db, membership, branch_id)
        query = query.filter(SaccoMember.branch_id == branch_id)
    if status:
        query = query.filter(SaccoMember.status == status)
    total = query.count()
    rows = query.order_by(SaccoMember.created_at.desc(), SaccoMember.id.desc()).offset(offset).limit(limit).all()
    return {"items": [_member_out(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/members/{member_id}")
def get_member(
    member_id: int,
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_sacco_permission(membership, "read")
    return _member_out(_member_for_membership(db, membership, member_id))


@router.get("/members/{member_id}/kyc-details")
def get_member_kyc_details(
    member_id: int,
    reason: str = Query(min_length=10, max_length=300),
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_kyc_approver(membership)
    row = _member_for_membership(db, membership, member_id)
    try:
        details = decrypt_kyc_payload(row.identity_ciphertext)
    except KYCConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    _audit(db, user, membership, "sacco.member.kyc_details_accessed", row.id, f"reason={reason.strip()}")
    db.commit()
    return {"member_id": row.id, **details}


@router.post("/members/{member_id}/kyc-review")
def review_member_kyc(
    member_id: int,
    payload: SaccoKycReviewIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_kyc_approver(membership)
    row = _member_for_membership(db, membership, member_id, for_update=True)
    if row.status != "pending_kyc":
        raise HTTPException(409, "Only members awaiting KYC review can be decided")
    if row.created_by == user.id:
        raise HTTPException(403, "The member creator cannot approve or reject their own KYC submission")
    cutoff = datetime.now(timezone.utc) - KYC_ACCESS_WINDOW
    accessed = db.query(AuditEvent).filter(
        AuditEvent.organization_id == membership.organization_id,
        AuditEvent.actor_user_id == user.id,
        AuditEvent.action == "sacco.member.kyc_details_accessed",
        AuditEvent.resource_type == "sacco_member",
        AuditEvent.resource_id == str(row.id),
        AuditEvent.created_at >= cutoff,
    ).first()
    if not accessed:
        raise HTTPException(409, "Open and review the protected KYC details before recording a decision")
    row.status = "active" if payload.decision == "verify" else "rejected"
    row.review_note = payload.note
    row.reviewed_by = user.id
    row.reviewed_at = datetime.now(timezone.utc)
    _audit(db, user, membership, "sacco.member.kyc_reviewed", row.id,
           f"decision={payload.decision};status={row.status}")
    db.commit()
    db.refresh(row)
    return _member_out(row)


@router.post("/members/{member_id}/transactions", status_code=201)
def create_member_transaction(
    member_id: int,
    payload: SaccoFinancialTransactionIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    action = {
        "deposit": "deposit",
        "withdrawal": "withdraw",
        "share_contribution": "share_contribute",
    }[payload.transaction_type]
    _require_sacco_permission(membership, action)
    member = _member_for_membership(db, membership, member_id, for_update=True)
    fingerprint = transaction_fingerprint({
        "member_id": member.id,
        "account_type": payload.account_type,
        "transaction_type": payload.transaction_type,
        "amount": format(payload.amount, ".2f"),
        "reference": payload.reference,
    })
    existing = db.query(SaccoFinancialTransaction).filter_by(
        organization_id=membership.organization_id,
        idempotency_key=payload.idempotency_key,
    ).first()
    if existing:
        if existing.request_fingerprint != fingerprint:
            raise HTTPException(409, "Idempotency key was already used for a different financial transaction")
        return _financial_out(existing, replayed=True)
    if member.status != "active":
        raise HTTPException(409, "Financial transactions require an active, KYC-verified member")
    organization = db.get(Organization, membership.organization_id)
    if not organization:
        raise HTTPException(404, "Organization not found")

    status = "pending_approval" if payload.transaction_type == "withdrawal" else "posted"
    row = SaccoFinancialTransaction(
        organization_id=membership.organization_id, member_id=member.id,
        branch_id=member.branch_id, account_type=payload.account_type,
        transaction_type=payload.transaction_type, amount=payload.amount,
        currency=organization.currency, reference=payload.reference, status=status,
        idempotency_key=payload.idempotency_key, request_fingerprint=fingerprint,
        created_by=user.id,
    )
    db.add(row)
    try:
        db.flush()
        if status == "posted":
            db.add(SaccoLedgerEntry(
                organization_id=membership.organization_id, member_id=member.id,
                transaction_id=row.id, branch_id=member.branch_id,
                account_type=payload.account_type, signed_amount=payload.amount,
                currency=organization.currency, reference=payload.reference,
                created_by=user.id,
            ))
            _audit_financial(
                db, user, membership, "sacco.transaction.posted", row.id,
                f"type={payload.transaction_type};account={payload.account_type};amount={payload.amount:.2f};currency={organization.currency}",
            )
        else:
            _audit_financial(
                db, user, membership, "sacco.withdrawal.requested", row.id,
                f"amount={payload.amount:.2f};currency={organization.currency}",
            )
        db.commit()
        db.refresh(row)
        return _financial_out(row)
    except IntegrityError:
        db.rollback()
        replay = db.query(SaccoFinancialTransaction).filter_by(
            organization_id=membership.organization_id,
            idempotency_key=payload.idempotency_key,
        ).first()
        if replay and replay.request_fingerprint == fingerprint:
            return _financial_out(replay, replayed=True)
        raise HTTPException(409, "Financial idempotency key conflicts with an existing transaction")


@router.get("/members/{member_id}/transactions")
def list_member_transactions(
    member_id: int,
    account_type: str | None = Query(default=None, pattern=r"^(savings|shares)$"),
    status: str | None = Query(default=None, pattern=r"^(pending_approval|posted|rejected)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_sacco_permission(membership, "read")
    member = _member_for_membership(db, membership, member_id)
    query = db.query(SaccoFinancialTransaction).filter_by(
        organization_id=membership.organization_id, member_id=member.id,
    )
    if account_type:
        query = query.filter(SaccoFinancialTransaction.account_type == account_type)
    if status:
        query = query.filter(SaccoFinancialTransaction.status == status)
    total = query.count()
    rows = query.order_by(
        SaccoFinancialTransaction.created_at.desc(), SaccoFinancialTransaction.id.desc()
    ).offset(offset).limit(limit).all()
    return {"items": [_financial_out(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/members/{member_id}/balances")
def member_balances(
    member_id: int,
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_sacco_permission(membership, "read")
    member = _member_for_membership(db, membership, member_id)
    organization = db.get(Organization, membership.organization_id)
    if not organization:
        raise HTTPException(404, "Organization not found")
    return {
        "member_id": member.id, "member_number": member.member_number,
        "currency": organization.currency,
        "savings_balance": format(_ledger_balance(db, membership.organization_id, member.id, "savings"), ".2f"),
        "share_balance": format(_ledger_balance(db, membership.organization_id, member.id, "shares"), ".2f"),
    }


@router.post("/transactions/{transaction_id}/decision")
def decide_member_withdrawal(
    transaction_id: int,
    payload: SaccoWithdrawalDecisionIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_sacco_permission(membership, "approve_withdrawal")
    row = db.query(SaccoFinancialTransaction).filter_by(
        id=transaction_id, organization_id=membership.organization_id,
    ).with_for_update().first()
    if not row:
        raise HTTPException(404, "SACCO financial transaction not found")
    member = _member_for_membership(db, membership, row.member_id, for_update=True)
    if row.transaction_type != "withdrawal" or row.account_type != "savings":
        raise HTTPException(409, "Only savings withdrawal requests require this decision")
    if row.status != "pending_approval":
        raise HTTPException(409, "Only pending withdrawal requests can be decided")
    if row.created_by == user.id:
        raise HTTPException(403, "The withdrawal requester cannot approve or reject their own request")

    if payload.decision == "approve":
        balance = _ledger_balance(db, membership.organization_id, member.id, "savings")
        if row.amount > balance:
            raise HTTPException(409, "Insufficient available savings balance for this withdrawal")
        db.add(SaccoLedgerEntry(
            organization_id=membership.organization_id, member_id=member.id,
            transaction_id=row.id, branch_id=member.branch_id,
            account_type="savings", signed_amount=-row.amount,
            currency=row.currency, reference=row.reference, created_by=user.id,
        ))
        row.status = "posted"
        action = "sacco.withdrawal.approved"
    else:
        row.status = "rejected"
        action = "sacco.withdrawal.rejected"
    row.decided_by = user.id
    row.decided_at = datetime.now(timezone.utc)
    row.decision_note = payload.note
    _audit_financial(
        db, user, membership, action, row.id,
        f"decision={payload.decision};amount={row.amount:.2f};currency={row.currency}",
    )
    db.commit()
    db.refresh(row)
    return _financial_out(row)



def _loan_product_out(row: SaccoLoanProduct) -> dict:
    return {
        "id": row.id, "organization_id": row.organization_id, "code": row.code,
        "name": row.name, "currency": row.currency,
        "min_amount": format(row.min_amount, ".2f"), "max_amount": format(row.max_amount, ".2f"),
        "annual_interest_rate": format(row.annual_interest_rate, ".4f"),
        "min_term_months": row.min_term_months, "max_term_months": row.max_term_months,
        "max_debt_service_ratio": format(row.max_debt_service_ratio, ".4f"),
        "is_active": row.is_active, "created_at": row.created_at,
    }


def _loan_application_out(row: SaccoLoanApplication) -> dict:
    return {
        "id": row.id, "organization_id": row.organization_id, "member_id": row.member_id,
        "product_id": row.product_id, "branch_id": row.branch_id,
        "requested_amount": format(row.requested_amount, ".2f"),
        "term_months": row.term_months,
        "annual_interest_rate": format(row.annual_interest_rate, ".4f"),
        "purpose": row.purpose, "status": row.status, "created_by": row.created_by,
        "assessment_monthly_net_income": format(row.assessment_monthly_net_income, ".2f") if row.assessment_monthly_net_income is not None else None,
        "assessment_existing_monthly_debt": format(row.assessment_existing_monthly_debt, ".2f") if row.assessment_existing_monthly_debt is not None else None,
        "assessment_monthly_installment": format(row.assessment_monthly_installment, ".2f") if row.assessment_monthly_installment is not None else None,
        "assessment_total_interest": format(row.assessment_total_interest, ".2f") if row.assessment_total_interest is not None else None,
        "assessment_debt_service_ratio": format(row.assessment_debt_service_ratio, ".4f") if row.assessment_debt_service_ratio is not None else None,
        "assessment_recommendation": row.assessment_recommendation,
        "assessment_note": row.assessment_note, "assessed_by": row.assessed_by,
        "assessed_at": row.assessed_at, "decision_by": row.decision_by,
        "decided_at": row.decided_at, "decision_note": row.decision_note,
        "disbursed_by": row.disbursed_by, "disbursed_at": row.disbursed_at,
        "created_at": row.created_at,
    }


def _loan_ledger_out(row: SaccoLoanLedgerEntry) -> dict:
    return {
        "id": row.id, "loan_application_id": row.loan_application_id,
        "member_id": row.member_id, "branch_id": row.branch_id,
        "entry_type": row.entry_type, "amount": format(row.amount, ".2f"),
        "principal_delta": format(row.principal_delta, ".2f"),
        "interest_delta": format(row.interest_delta, ".2f"),
        "currency": row.currency, "reference": row.reference,
        "created_by": row.created_by, "created_at": row.created_at,
    }


def _loan_query(db: Session, membership: Membership):
    query = db.query(SaccoLoanApplication).filter(
        SaccoLoanApplication.organization_id == membership.organization_id
    )
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        query = query.filter(
            SaccoLoanApplication.branch_id.in_(allowed) if allowed else SaccoLoanApplication.id == -1
        )
    return query


def _loan_for_membership(
    db: Session, membership: Membership, loan_id: int, *, for_update: bool = False
) -> SaccoLoanApplication:
    query = _loan_query(db, membership).filter(SaccoLoanApplication.id == loan_id)
    if for_update:
        query = query.with_for_update()
    row = query.first()
    if not row:
        raise HTTPException(404, "SACCO loan application not found")
    return row


def _loan_balances(db: Session, organization_id: int, loan_id: int) -> tuple[Decimal, Decimal]:
    principal = db.query(func.coalesce(func.sum(SaccoLoanLedgerEntry.principal_delta), 0)).filter(
        SaccoLoanLedgerEntry.organization_id == organization_id,
        SaccoLoanLedgerEntry.loan_application_id == loan_id,
    ).scalar()
    interest = db.query(func.coalesce(func.sum(SaccoLoanLedgerEntry.interest_delta), 0)).filter(
        SaccoLoanLedgerEntry.organization_id == organization_id,
        SaccoLoanLedgerEntry.loan_application_id == loan_id,
    ).scalar()
    return (
        max(Decimal(str(principal or "0")).quantize(Decimal("0.01")), Decimal("0.00")),
        max(Decimal(str(interest or "0")).quantize(Decimal("0.01")), Decimal("0.00")),
    )


def _audit_loan(
    db: Session, user: User, membership: Membership, action: str,
    loan_id: int, detail: str = "",
) -> None:
    db.add(AuditEvent(
        organization_id=membership.organization_id, actor_user_id=user.id,
        action=action, resource_type="sacco_loan_application",
        resource_id=str(loan_id), detail=detail[:500],
    ))


@router.post("/loan-products", status_code=201)
def create_loan_product(
    payload: SaccoLoanProductCreateIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_sacco_permission(membership, "manage_loan_products")
    organization = db.get(Organization, membership.organization_id)
    if not organization:
        raise HTTPException(404, "Organization not found")
    existing = db.query(SaccoLoanProduct).filter_by(
        organization_id=membership.organization_id, code=payload.code
    ).first()
    if existing:
        raise HTTPException(409, "Loan product code already exists in this organization")
    row = SaccoLoanProduct(
        organization_id=membership.organization_id, code=payload.code, name=payload.name,
        currency=organization.currency, min_amount=payload.min_amount,
        max_amount=payload.max_amount, annual_interest_rate=payload.annual_interest_rate,
        min_term_months=payload.min_term_months, max_term_months=payload.max_term_months,
        max_debt_service_ratio=payload.max_debt_service_ratio, is_active=True,
        created_by=user.id,
    )
    db.add(row)
    try:
        db.flush()
        db.add(AuditEvent(
            organization_id=membership.organization_id, actor_user_id=user.id,
            action="sacco.loan_product.created", resource_type="sacco_loan_product",
            resource_id=str(row.id),
            detail=f"code={row.code};currency={row.currency};rate={row.annual_interest_rate}",
        ))
        db.commit()
        db.refresh(row)
        return _loan_product_out(row)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Loan product code conflicts with an existing product")


@router.get("/loan-products")
def list_loan_products(
    include_inactive: bool = False,
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_sacco_permission(membership, "read")
    query = db.query(SaccoLoanProduct).filter(
        SaccoLoanProduct.organization_id == membership.organization_id
    )
    if not include_inactive:
        query = query.filter(SaccoLoanProduct.is_active.is_(True))
    rows = query.order_by(SaccoLoanProduct.code.asc()).all()
    return {"items": [_loan_product_out(row) for row in rows]}


@router.post("/members/{member_id}/loan-applications", status_code=201)
def create_loan_application(
    member_id: int,
    payload: SaccoLoanApplicationCreateIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_sacco_permission(membership, "create_loan")
    member = _member_for_membership(db, membership, member_id, for_update=True)
    if member.status != "active":
        raise HTTPException(409, "Loan applications require an active, KYC-verified member")
    product = db.query(SaccoLoanProduct).filter_by(
        id=payload.product_id, organization_id=membership.organization_id, is_active=True
    ).first()
    if not product:
        raise HTTPException(404, "Active loan product not found")
    if payload.requested_amount < product.min_amount or payload.requested_amount > product.max_amount:
        raise HTTPException(422, "Requested amount is outside the loan product limits")
    if not product.min_term_months <= payload.term_months <= product.max_term_months:
        raise HTTPException(422, "Requested term is outside the loan product limits")
    fingerprint = transaction_fingerprint({
        "member_id": member.id, "product_id": product.id,
        "requested_amount": format(payload.requested_amount, ".2f"),
        "term_months": payload.term_months, "purpose": payload.purpose,
    })
    existing = db.query(SaccoLoanApplication).filter_by(
        organization_id=membership.organization_id, idempotency_key=payload.idempotency_key
    ).first()
    if existing:
        if existing.request_fingerprint != fingerprint:
            raise HTTPException(409, "Loan idempotency key was used for a different application")
        return {**_loan_application_out(existing), "replayed": True}
    row = SaccoLoanApplication(
        organization_id=membership.organization_id, member_id=member.id,
        product_id=product.id, branch_id=member.branch_id,
        requested_amount=payload.requested_amount, term_months=payload.term_months,
        annual_interest_rate=product.annual_interest_rate,
        max_debt_service_ratio=product.max_debt_service_ratio,
        purpose=payload.purpose, status="submitted", created_by=user.id,
        idempotency_key=payload.idempotency_key, request_fingerprint=fingerprint,
    )
    db.add(row)
    try:
        db.flush()
        _audit_loan(
            db, user, membership, "sacco.loan_application.submitted", row.id,
            f"member_id={member.id};product_id={product.id};amount={row.requested_amount:.2f};term_months={row.term_months}",
        )
        db.commit()
        db.refresh(row)
        return {**_loan_application_out(row), "replayed": False}
    except IntegrityError:
        db.rollback()
        replay = db.query(SaccoLoanApplication).filter_by(
            organization_id=membership.organization_id, idempotency_key=payload.idempotency_key
        ).first()
        if replay and replay.request_fingerprint == fingerprint:
            return {**_loan_application_out(replay), "replayed": True}
        raise HTTPException(409, "Loan application idempotency key conflicts with another request")


@router.get("/loan-applications")
def list_loan_applications(
    status: str | None = Query(default=None, pattern=r"^(submitted|assessed|approved|rejected|disbursed|closed)$"),
    member_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_sacco_permission(membership, "read")
    query = _loan_query(db, membership)
    if member_id is not None:
        _member_for_membership(db, membership, member_id)
        query = query.filter(SaccoLoanApplication.member_id == member_id)
    if status:
        query = query.filter(SaccoLoanApplication.status == status)
    total = query.count()
    rows = query.order_by(
        SaccoLoanApplication.created_at.desc(), SaccoLoanApplication.id.desc()
    ).offset(offset).limit(limit).all()
    return {"items": [_loan_application_out(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/loan-applications/{loan_id}")
def get_loan_application(
    loan_id: int,
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_sacco_permission(membership, "read")
    return _loan_application_out(_loan_for_membership(db, membership, loan_id))


@router.post("/loan-applications/{loan_id}/assessment")
def assess_loan_application(
    loan_id: int,
    payload: SaccoLoanAssessmentIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_sacco_permission(membership, "assess_loan")
    row = _loan_for_membership(db, membership, loan_id, for_update=True)
    if row.status != "submitted":
        raise HTTPException(409, "Only submitted loan applications can be assessed")
    if row.created_by == user.id:
        raise HTTPException(403, "The loan application creator cannot assess their own application")
    try:
        interest, total_due, installment = calculate_flat_loan_terms(
            row.requested_amount, row.annual_interest_rate, row.term_months
        )
        ratio = calculate_debt_service_ratio(
            payload.monthly_net_income, payload.existing_monthly_debt, installment
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    recommendation = "approve" if ratio <= row.max_debt_service_ratio else "decline"
    row.assessment_monthly_net_income = payload.monthly_net_income
    row.assessment_existing_monthly_debt = payload.existing_monthly_debt
    row.assessment_monthly_installment = installment
    row.assessment_total_interest = interest
    row.assessment_debt_service_ratio = ratio
    row.assessment_recommendation = recommendation
    row.assessment_note = payload.note
    row.assessed_by = user.id
    row.assessed_at = datetime.now(timezone.utc)
    row.status = "assessed"
    _audit_loan(
        db, user, membership, "sacco.loan_application.assessed", row.id,
        f"recommendation={recommendation};dsr={ratio};installment={installment:.2f};total_due={total_due:.2f}",
    )
    db.commit()
    db.refresh(row)
    return _loan_application_out(row)


@router.post("/loan-applications/{loan_id}/decision")
def decide_loan_application(
    loan_id: int,
    payload: SaccoLoanDecisionIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_sacco_permission(membership, "decide_loan")
    row = _loan_for_membership(db, membership, loan_id, for_update=True)
    if row.status != "assessed":
        raise HTTPException(409, "Only assessed loan applications can be decided")
    if user.id in {row.created_by, row.assessed_by}:
        raise HTTPException(403, "The applicant and credit assessor cannot decide the same loan")
    if payload.decision == "approve" and row.assessment_recommendation != "approve":
        raise HTTPException(409, "The affordability assessment does not recommend approval")
    row.status = "approved" if payload.decision == "approve" else "rejected"
    row.decision_by = user.id
    row.decided_at = datetime.now(timezone.utc)
    row.decision_note = payload.note
    _audit_loan(
        db, user, membership, "sacco.loan_application.decided", row.id,
        f"decision={payload.decision};status={row.status}",
    )
    db.commit()
    db.refresh(row)
    return _loan_application_out(row)


@router.post("/loan-applications/{loan_id}/disbursement")
def disburse_loan_application(
    loan_id: int,
    payload: SaccoLoanDisbursementIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_sacco_permission(membership, "disburse_loan")
    row = _loan_for_membership(db, membership, loan_id, for_update=True)
    fingerprint = transaction_fingerprint({
        "loan_id": row.id, "entry_type": "disbursement",
        "amount": format(row.requested_amount, ".2f"), "reference": payload.reference,
    })
    existing = db.query(SaccoLoanLedgerEntry).filter_by(
        organization_id=membership.organization_id, idempotency_key=payload.idempotency_key
    ).first()
    if existing:
        if existing.request_fingerprint != fingerprint:
            raise HTTPException(409, "Loan ledger idempotency key was used for a different request")
        return {**_loan_ledger_out(existing), "replayed": True}
    if row.status != "approved":
        raise HTTPException(409, "Only approved loans can be disbursed")
    if row.decision_by == user.id:
        raise HTTPException(403, "The loan approver cannot disburse the same loan")
    try:
        interest, _, _ = calculate_flat_loan_terms(
            row.requested_amount, row.annual_interest_rate, row.term_months
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    organization = db.get(Organization, membership.organization_id)
    if not organization:
        raise HTTPException(404, "Organization not found")
    entry = SaccoLoanLedgerEntry(
        organization_id=membership.organization_id, loan_application_id=row.id,
        member_id=row.member_id, branch_id=row.branch_id, entry_type="disbursement",
        amount=row.requested_amount, principal_delta=row.requested_amount,
        interest_delta=interest, currency=organization.currency, reference=payload.reference,
        idempotency_key=payload.idempotency_key, request_fingerprint=fingerprint,
        created_by=user.id,
    )
    db.add(entry)
    row.status = "disbursed"
    row.disbursed_by = user.id
    row.disbursed_at = datetime.now(timezone.utc)
    try:
        db.flush()
        _audit_loan(
            db, user, membership, "sacco.loan_application.disbursed", row.id,
            f"principal={row.requested_amount:.2f};interest={interest:.2f};currency={organization.currency};cash_settlement=external",
        )
        db.commit()
        db.refresh(entry)
        return {**_loan_ledger_out(entry), "replayed": False}
    except IntegrityError:
        db.rollback()
        replay = db.query(SaccoLoanLedgerEntry).filter_by(
            organization_id=membership.organization_id, idempotency_key=payload.idempotency_key
        ).first()
        if replay and replay.request_fingerprint == fingerprint:
            return {**_loan_ledger_out(replay), "replayed": True}
        raise HTTPException(409, "Loan already has a disbursement or the idempotency key conflicts")


@router.post("/loan-applications/{loan_id}/repayments", status_code=201)
def repay_loan_application(
    loan_id: int,
    payload: SaccoLoanRepaymentIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_sacco_permission(membership, "repay_loan")
    row = _loan_for_membership(db, membership, loan_id, for_update=True)
    fingerprint = transaction_fingerprint({
        "loan_id": row.id, "entry_type": "repayment",
        "amount": format(payload.amount, ".2f"), "reference": payload.reference,
    })
    existing = db.query(SaccoLoanLedgerEntry).filter_by(
        organization_id=membership.organization_id, idempotency_key=payload.idempotency_key
    ).first()
    if existing:
        if existing.request_fingerprint != fingerprint:
            raise HTTPException(409, "Loan ledger idempotency key was used for a different request")
        return {**_loan_ledger_out(existing), "replayed": True}
    if row.status != "disbursed":
        raise HTTPException(409, "Repayments require a disbursed loan that is not closed")
    principal_due, interest_due = _loan_balances(db, membership.organization_id, row.id)
    try:
        principal_delta, interest_delta = allocate_repayment(
            payload.amount, principal_due, interest_due
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    entry = SaccoLoanLedgerEntry(
        organization_id=membership.organization_id, loan_application_id=row.id,
        member_id=row.member_id, branch_id=row.branch_id, entry_type="repayment",
        amount=payload.amount, principal_delta=principal_delta,
        interest_delta=interest_delta, currency=organization_currency(db, membership.organization_id),
        reference=payload.reference, idempotency_key=payload.idempotency_key,
        request_fingerprint=fingerprint, created_by=user.id,
    )
    db.add(entry)
    new_principal = principal_due + principal_delta
    new_interest = interest_due + interest_delta
    if new_principal == 0 and new_interest == 0:
        row.status = "closed"
    try:
        db.flush()
        _audit_loan(
            db, user, membership, "sacco.loan_application.repayment_posted", row.id,
            f"amount={payload.amount:.2f};principal_delta={principal_delta:.2f};interest_delta={interest_delta:.2f}",
        )
        db.commit()
        db.refresh(entry)
        return {**_loan_ledger_out(entry), "replayed": False}
    except IntegrityError:
        db.rollback()
        replay = db.query(SaccoLoanLedgerEntry).filter_by(
            organization_id=membership.organization_id, idempotency_key=payload.idempotency_key
        ).first()
        if replay and replay.request_fingerprint == fingerprint:
            return {**_loan_ledger_out(replay), "replayed": True}
        raise HTTPException(409, "Loan repayment idempotency key conflicts with an existing entry")


def organization_currency(db: Session, organization_id: int) -> str:
    organization = db.get(Organization, organization_id)
    if not organization:
        raise HTTPException(404, "Organization not found")
    return organization.currency


@router.get("/loan-applications/{loan_id}/ledger")
def get_loan_ledger(
    loan_id: int,
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_sacco_permission(membership, "read")
    row = _loan_for_membership(db, membership, loan_id)
    entries = db.query(SaccoLoanLedgerEntry).filter_by(
        organization_id=membership.organization_id, loan_application_id=row.id
    ).order_by(SaccoLoanLedgerEntry.created_at.asc(), SaccoLoanLedgerEntry.id.asc()).all()
    principal_due, interest_due = _loan_balances(db, membership.organization_id, row.id)
    return {
        "loan_application": _loan_application_out(row),
        "currency": entries[0].currency if entries else organization_currency(db, membership.organization_id),
        "principal_outstanding": format(principal_due, ".2f"),
        "interest_outstanding": format(interest_due, ".2f"),
        "total_outstanding": format(principal_due + interest_due, ".2f"),
        "entries": [_loan_ledger_out(entry) for entry in entries],
    }
