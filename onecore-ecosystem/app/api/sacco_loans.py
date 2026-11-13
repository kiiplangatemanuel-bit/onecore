"""Tenant- and branch-scoped SACCO loan origination, credit checks and approvals."""
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.authorization import branch_scope_ids, can_access_branch
from app.core.database import get_db
from app.core.models import AuditEvent, Branch, Membership, Organization, User
from app.core.sacco_models import SaccoMember
from app.core.sacco_loan_models import (
    SaccoLoanApplication, SaccoLoanCollateral, SaccoLoanDisbursement,
    SaccoLoanGuarantor, SaccoLoanInstallment, SaccoLoanProduct,
    SaccoLoanRepayment, SaccoLoanRepaymentAllocation, SaccoLoanRepaymentJournalLine,
)
from app.core.sacco_loan_schemas import (
    SaccoLoanApplicationCreateIn, SaccoLoanAssessmentIn, SaccoLoanCollateralCreateIn,
    SaccoLoanCollateralVerificationIn, SaccoLoanDecisionIn, SaccoLoanDisbursementCreateIn,
    SaccoLoanDisbursementVerificationIn, SaccoLoanGuarantorConsentIn,
    SaccoLoanGuarantorCreateIn, SaccoLoanProductCreateIn,
    SaccoLoanRepaymentCreateIn, SaccoLoanRepaymentVerificationIn,
)
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.services.sacco_loans import allocate_due_repayment, monthly_installment, projected_schedule
from app.services.sacco_membership import transaction_fingerprint

router = APIRouter(prefix="/api/v1/sacco", tags=["sacco-loans"])

LOAN_PERMISSIONS = {
    "org_admin": {"read", "manage_products", "create_application", "add_guarantor", "record_consent", "add_collateral", "verify_collateral", "assess", "decide", "request_disbursement", "verify_disbursement", "request_repayment", "verify_repayment"},
    "sacco_manager": {"read", "manage_products", "create_application", "add_guarantor", "record_consent", "add_collateral", "verify_collateral", "assess", "decide", "request_disbursement", "request_repayment"},
    "sacco_officer": {"read", "create_application", "add_guarantor", "add_collateral", "request_repayment"},
    "sacco_treasurer": {"read", "verify_disbursement", "verify_repayment"},
    "sacco_credit_officer": {"read", "create_application", "add_guarantor", "add_collateral", "assess"},
    "sacco_credit_approver": {"read", "decide"},
    "sacco_guarantor_verifier": {"read", "record_consent", "verify_collateral"},
    "sacco_auditor": {"read"},
}


def _require_permission(membership: Membership, action: str) -> None:
    role = (membership.role or "").strip().lower()
    if action not in LOAN_PERMISSIONS.get(role, set()):
        raise HTTPException(403, "Insufficient SACCO loan permissions")


def _validate_branch(db: Session, membership: Membership, branch_id: str | None) -> None:
    allowed = branch_scope_ids(membership)
    if branch_id is None:
        if allowed is not None:
            raise HTTPException(403, "Select an authorized branch for this membership")
        return
    branch = db.query(Branch).filter_by(
        id=branch_id, organization_id=membership.organization_id, is_active=True
    ).first()
    if not branch or not can_access_branch(membership, branch_id):
        raise HTTPException(404, "Branch not found")


def _product_query(db: Session, membership: Membership):
    query = db.query(SaccoLoanProduct).filter(
        SaccoLoanProduct.organization_id == membership.organization_id
    )
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        query = query.filter(or_(
            SaccoLoanProduct.branch_id.is_(None),
            SaccoLoanProduct.branch_id.in_(allowed) if allowed else SaccoLoanProduct.branch_id.is_(None),
        ))
    return query


def _application_query(db: Session, membership: Membership):
    query = db.query(SaccoLoanApplication).filter(
        SaccoLoanApplication.organization_id == membership.organization_id
    )
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            query = query.filter(SaccoLoanApplication.id == -1)
        else:
            query = query.filter(SaccoLoanApplication.branch_id.in_(allowed))
    return query


def _member_for_membership(db: Session, membership: Membership, member_id: int, *, for_update: bool = False) -> SaccoMember:
    query = db.query(SaccoMember).filter_by(
        organization_id=membership.organization_id, id=member_id
    )
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            query = query.filter(SaccoMember.id == -1)
        else:
            query = query.filter(SaccoMember.branch_id.in_(allowed))
    if for_update:
        query = query.with_for_update()
    member = query.first()
    if not member:
        raise HTTPException(404, "SACCO member not found")
    return member


def _guarantor_query(db: Session, membership: Membership, application_id: int):
    query = db.query(SaccoLoanGuarantor).join(
        SaccoMember,
        (SaccoMember.id == SaccoLoanGuarantor.member_id)
        & (SaccoMember.organization_id == SaccoLoanGuarantor.organization_id),
    ).filter(
        SaccoLoanGuarantor.organization_id == membership.organization_id,
        SaccoLoanGuarantor.application_id == application_id,
    )
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            query = query.filter(SaccoMember.id == -1)
        else:
            query = query.filter(SaccoMember.branch_id.in_(allowed))
    return query


def _application_for_membership(
    db: Session, membership: Membership, application_id: int, *, for_update: bool = False
) -> SaccoLoanApplication:
    query = _application_query(db, membership).filter(SaccoLoanApplication.id == application_id)
    if for_update:
        query = query.with_for_update()
    application = query.first()
    if not application:
        raise HTTPException(404, "SACCO loan application not found")
    return application


def _product_for_application(
    db: Session, membership: Membership, application: SaccoLoanApplication
) -> SaccoLoanProduct:
    product = _product_query(db, membership).filter(
        SaccoLoanProduct.id == application.product_id
    ).first()
    if not product:
        raise HTTPException(404, "SACCO loan product not found")
    return product


def _audit(
    db: Session, user: User, membership: Membership, action: str,
    resource_type: str, resource_id: int, detail: str = "",
) -> None:
    db.add(AuditEvent(
        organization_id=membership.organization_id, actor_user_id=user.id,
        action=action, resource_type=resource_type, resource_id=str(resource_id),
        detail=detail[:500],
    ))


def _product_out(row: SaccoLoanProduct) -> dict:
    return {
        "id": row.id, "organization_id": row.organization_id, "branch_id": row.branch_id,
        "code": row.code, "name": row.name, "currency": row.currency,
        "minimum_principal": format(row.minimum_principal, ".2f"),
        "maximum_principal": format(row.maximum_principal, ".2f"),
        "annual_interest_rate_bps": row.annual_interest_rate_bps,
        "minimum_term_months": row.minimum_term_months,
        "maximum_term_months": row.maximum_term_months,
        "minimum_guarantors": row.minimum_guarantors,
        "maximum_debt_service_ratio_bps": row.maximum_debt_service_ratio_bps,
        "requires_collateral": row.requires_collateral, "is_active": row.is_active,
        "created_at": row.created_at,
    }


def _application_out(row: SaccoLoanApplication) -> dict:
    return {
        "id": row.id, "organization_id": row.organization_id, "product_id": row.product_id,
        "member_id": row.member_id, "branch_id": row.branch_id,
        "principal": format(row.principal, ".2f"), "term_months": row.term_months,
        "purpose": row.purpose, "monthly_net_income": format(row.monthly_net_income, ".2f"),
        "monthly_existing_debt": format(row.monthly_existing_debt, ".2f"),
        "first_repayment_date": row.first_repayment_date.isoformat(),
        "assessment_status": row.assessment_status,
        "debt_service_ratio_bps": row.debt_service_ratio_bps,
        "estimated_monthly_installment": (
            format(row.estimated_monthly_installment, ".2f")
            if row.estimated_monthly_installment is not None else None
        ),
        "assessment_note": row.assessment_note, "assessed_by": row.assessed_by,
        "assessed_at": row.assessed_at, "status": row.status,
        "decided_by": row.decided_by, "decided_at": row.decided_at,
        "decision_note": row.decision_note, "created_by": row.created_by,
        "created_at": row.created_at,
    }


def _guarantor_out(row: SaccoLoanGuarantor) -> dict:
    return {
        "id": row.id, "application_id": row.application_id, "member_id": row.member_id,
        "guaranteed_amount": format(row.guaranteed_amount, ".2f"),
        "consent_status": row.consent_status, "consent_method": row.consent_method,
        "consent_reference": row.consent_reference, "consent_note": row.consent_note,
        "consent_recorded_by": row.consent_recorded_by, "consent_at": row.consent_at,
        "created_by": row.created_by, "created_at": row.created_at,
    }


def _collateral_out(row: SaccoLoanCollateral) -> dict:
    return {
        "id": row.id, "application_id": row.application_id,
        "collateral_type": row.collateral_type, "description": row.description,
        "declared_value": format(row.declared_value, ".2f"),
        "document_reference": row.document_reference, "status": row.status,
        "verification_note": row.verification_note, "verified_by": row.verified_by,
        "verified_at": row.verified_at, "created_by": row.created_by,
    }


def _installment_out(row: SaccoLoanInstallment) -> dict:
    return {
        "id": row.id, "installment_number": row.installment_number,
        "due_date": row.due_date.isoformat(), "principal_due": format(row.principal_due, ".2f"),
        "interest_due": format(row.interest_due, ".2f"), "total_due": format(row.total_due, ".2f"),
        "currency": row.currency, "status": row.status,
        "principal_paid": format(row.principal_paid, ".2f"),
        "interest_paid": format(row.interest_paid, ".2f"),
        "principal_outstanding": format(row.principal_due - row.principal_paid, ".2f"),
        "interest_outstanding": format(row.interest_due - row.interest_paid, ".2f"),
        "total_outstanding": format(row.total_due - row.principal_paid - row.interest_paid, ".2f"),
    }


def _advance_application(db: Session, membership: Membership, application: SaccoLoanApplication, product: SaccoLoanProduct) -> None:
    guarantors = db.query(SaccoLoanGuarantor).filter_by(
        organization_id=membership.organization_id, application_id=application.id,
        consent_status="accepted",
    ).all()
    guarantor_total = sum((row.guaranteed_amount for row in guarantors), Decimal("0.00"))
    guarantors_ready = (
        len(guarantors) >= product.minimum_guarantors
        and (product.minimum_guarantors == 0 or guarantor_total >= application.principal)
    )
    collateral_ready = True
    if product.requires_collateral:
        collateral = db.query(SaccoLoanCollateral).filter_by(
            organization_id=membership.organization_id, application_id=application.id,
            status="verified",
        ).all()
        collateral_ready = sum((row.declared_value for row in collateral), Decimal("0.00")) >= application.principal
    if application.assessment_status != "eligible":
        application.status = "pending_assessment"
    elif not guarantors_ready or not collateral_ready:
        application.status = "pending_guarantors"
    else:
        application.status = "pending_approval"


@router.post("/loan-products", status_code=201)
def create_loan_product(
    payload: SaccoLoanProductCreateIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "manage_products")
    _validate_branch(db, membership, payload.branch_id)
    organization = db.get(Organization, membership.organization_id)
    if not organization:
        raise HTTPException(404, "Organization not found")
    if payload.currency != (organization.currency or "").upper():
        raise HTTPException(409, "Loan product currency must match the organization's configured currency")
    duplicate = _product_query(db, membership).filter(SaccoLoanProduct.code == payload.code).first()
    if duplicate:
        raise HTTPException(409, "Loan product code already exists")
    row = SaccoLoanProduct(
        organization_id=membership.organization_id, branch_id=payload.branch_id,
        code=payload.code, name=payload.name, currency=payload.currency,
        minimum_principal=payload.minimum_principal, maximum_principal=payload.maximum_principal,
        annual_interest_rate_bps=payload.annual_interest_rate_bps,
        minimum_term_months=payload.minimum_term_months, maximum_term_months=payload.maximum_term_months,
        minimum_guarantors=payload.minimum_guarantors,
        maximum_debt_service_ratio_bps=payload.maximum_debt_service_ratio_bps,
        requires_collateral=payload.requires_collateral, is_active=True, created_by=user.id,
    )
    db.add(row)
    try:
        db.flush()
        _audit(db, user, membership, "sacco.loan_product.created", "sacco_loan_product", row.id,
               f"code={row.code};currency={row.currency};branch_id={row.branch_id or ''}")
        db.commit()
        db.refresh(row)
        return _product_out(row)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Loan product code conflicts with an existing product")


@router.get("/loan-products")
def list_loan_products(
    active_only: bool = True,
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "read")
    query = _product_query(db, membership)
    if active_only:
        query = query.filter(SaccoLoanProduct.is_active.is_(True))
    rows = query.order_by(SaccoLoanProduct.code.asc(), SaccoLoanProduct.id.asc()).all()
    return {"items": [_product_out(row) for row in rows]}


@router.post("/loan-applications", status_code=201)
def create_loan_application(
    payload: SaccoLoanApplicationCreateIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "create_application")
    member = _member_for_membership(db, membership, payload.member_id, for_update=True)
    if member.status != "active":
        raise HTTPException(409, "Loan applications require an active, KYC-verified member")
    product = _product_query(db, membership).filter(
        SaccoLoanProduct.id == payload.product_id, SaccoLoanProduct.is_active.is_(True)
    ).first()
    if not product:
        raise HTTPException(404, "Active loan product not found")
    if product.branch_id and product.branch_id != member.branch_id:
        raise HTTPException(409, "Loan product is not available to the member's branch")
    if payload.principal < product.minimum_principal or payload.principal > product.maximum_principal:
        raise HTTPException(422, "Requested principal is outside the loan product limits")
    if not product.minimum_term_months <= payload.term_months <= product.maximum_term_months:
        raise HTTPException(422, "Requested term is outside the loan product limits")
    fingerprint = transaction_fingerprint(payload.model_dump(mode="json", exclude={"idempotency_key"}))
    replay = db.query(SaccoLoanApplication).filter_by(
        organization_id=membership.organization_id, idempotency_key=payload.idempotency_key
    ).first()
    if replay:
        if replay.request_fingerprint != fingerprint:
            raise HTTPException(409, "Idempotency key was already used for a different loan application")
        return _application_out(replay)
    row = SaccoLoanApplication(
        organization_id=membership.organization_id, product_id=product.id, member_id=member.id,
        branch_id=member.branch_id, principal=payload.principal, term_months=payload.term_months,
        purpose=payload.purpose, monthly_net_income=payload.monthly_net_income,
        monthly_existing_debt=payload.monthly_existing_debt,
        first_repayment_date=payload.first_repayment_date, assessment_status="pending",
        status="pending_assessment", created_by=user.id, idempotency_key=payload.idempotency_key,
        request_fingerprint=fingerprint,
    )
    db.add(row)
    try:
        db.flush()
        _audit(db, user, membership, "sacco.loan_application.created", "sacco_loan_application", row.id,
               f"product_id={product.id};member_id={member.id};status=pending_assessment")
        db.commit()
        db.refresh(row)
        return _application_out(row)
    except IntegrityError:
        db.rollback()
        replay = db.query(SaccoLoanApplication).filter_by(
            organization_id=membership.organization_id, idempotency_key=payload.idempotency_key
        ).first()
        if replay and replay.request_fingerprint == fingerprint:
            return _application_out(replay)
        raise HTTPException(409, "Loan application idempotency key conflicts with an existing request")


@router.get("/loan-applications")
def list_loan_applications(
    status: str | None = Query(default=None, pattern=r"^(pending_assessment|pending_guarantors|pending_approval|approved_pending_disbursement|active|rejected)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "read")
    query = _application_query(db, membership)
    if status:
        query = query.filter(SaccoLoanApplication.status == status)
    total = query.count()
    rows = query.order_by(SaccoLoanApplication.created_at.desc(), SaccoLoanApplication.id.desc()).offset(offset).limit(limit).all()
    return {"items": [_application_out(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/loan-applications/{application_id}")
def get_loan_application(
    application_id: int,
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "read")
    return _application_out(_application_for_membership(db, membership, application_id))


@router.post("/loan-applications/{application_id}/guarantors", status_code=201)
def add_loan_guarantor(
    application_id: int,
    payload: SaccoLoanGuarantorCreateIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "add_guarantor")
    application = _application_for_membership(db, membership, application_id, for_update=True)
    if application.status not in {"pending_assessment", "pending_guarantors"}:
        raise HTTPException(409, "Guarantors cannot be changed after an application reaches approval")
    member = _member_for_membership(db, membership, payload.member_id, for_update=True)
    if member.status != "active":
        raise HTTPException(409, "Only active members can guarantee a loan")
    if member.id == application.member_id:
        raise HTTPException(422, "A borrower cannot guarantee their own loan")
    duplicate = db.query(SaccoLoanGuarantor).filter_by(
        organization_id=membership.organization_id, application_id=application.id, member_id=member.id
    ).first()
    if duplicate:
        raise HTTPException(409, "This member is already recorded as a guarantor")
    product = _product_for_application(db, membership, application)
    existing_total = db.query(func.coalesce(func.sum(SaccoLoanGuarantor.guaranteed_amount), 0)).filter(
        SaccoLoanGuarantor.organization_id == membership.organization_id,
        SaccoLoanGuarantor.application_id == application.id,
        SaccoLoanGuarantor.consent_status.in_(["pending", "accepted"]),
    ).scalar()
    if Decimal(str(existing_total or "0")) + payload.guaranteed_amount > application.principal:
        raise HTTPException(422, "Combined pending and accepted guarantees cannot exceed the loan principal")
    row = SaccoLoanGuarantor(
        organization_id=membership.organization_id, application_id=application.id,
        member_id=member.id, guaranteed_amount=payload.guaranteed_amount,
        consent_status="pending", created_by=user.id,
    )
    db.add(row)
    _advance_application(db, membership, application, product)
    db.flush()
    _audit(db, user, membership, "sacco.loan_guarantor.added", "sacco_loan_guarantor", row.id,
           f"application_id={application.id};member_id={member.id};consent_status=pending")
    db.commit()
    db.refresh(row)
    return _guarantor_out(row)


@router.get("/loan-applications/{application_id}/guarantors")
def list_loan_guarantors(
    application_id: int,
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "read")
    application = _application_for_membership(db, membership, application_id)
    rows = _guarantor_query(db, membership, application.id).order_by(SaccoLoanGuarantor.id.asc()).all()
    return {"items": [_guarantor_out(row) for row in rows]}


@router.post("/loan-guarantors/{guarantor_id}/consent")
def record_loan_guarantor_consent(
    guarantor_id: int,
    payload: SaccoLoanGuarantorConsentIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "record_consent")
    row = db.query(SaccoLoanGuarantor).filter_by(
        organization_id=membership.organization_id, id=guarantor_id
    ).with_for_update().first()
    if not row:
        raise HTTPException(404, "Loan guarantor record not found")
    application = _application_for_membership(db, membership, row.application_id, for_update=True)
    guarantor_member = _member_for_membership(db, membership, row.member_id, for_update=True)
    if guarantor_member.status != "active":
        raise HTTPException(409, "Only active members can remain guarantors")
    if application.status in {"approved_pending_disbursement", "rejected"}:
        raise HTTPException(409, "Guarantor consent is locked after the credit decision")
    if row.consent_status != "pending":
        raise HTTPException(409, "Guarantor consent has already been recorded")
    if application.created_by == user.id or row.created_by == user.id:
        raise HTTPException(403, "The application or guarantor recorder cannot attest the guarantor's consent")
    row.consent_status = "accepted" if payload.decision == "accept" else "rejected"
    row.consent_method = "in_person_documented"
    row.consent_reference = payload.consent_reference
    row.consent_note = payload.note
    row.consent_recorded_by = user.id
    row.consent_at = datetime.now(timezone.utc)
    product = _product_for_application(db, membership, application)
    _advance_application(db, membership, application, product)
    _audit(db, user, membership, "sacco.loan_guarantor.consent_recorded", "sacco_loan_guarantor", row.id,
           f"application_id={application.id};decision={payload.decision};method=in_person_documented")
    db.commit()
    db.refresh(row)
    return _guarantor_out(row)


@router.post("/loan-applications/{application_id}/collateral", status_code=201)
def add_loan_collateral(
    application_id: int,
    payload: SaccoLoanCollateralCreateIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "add_collateral")
    application = _application_for_membership(db, membership, application_id, for_update=True)
    if application.status not in {"pending_assessment", "pending_guarantors"}:
        raise HTTPException(409, "Collateral cannot be changed after an application reaches approval")
    row = SaccoLoanCollateral(
        organization_id=membership.organization_id, application_id=application.id,
        collateral_type=payload.collateral_type, description=payload.description,
        declared_value=payload.declared_value, document_reference=payload.document_reference,
        status="pending_verification", created_by=user.id,
    )
    db.add(row)
    db.flush()
    _audit(db, user, membership, "sacco.loan_collateral.recorded", "sacco_loan_collateral", row.id,
           f"application_id={application.id};type={row.collateral_type};status=pending_verification")
    db.commit()
    db.refresh(row)
    return _collateral_out(row)


@router.get("/loan-applications/{application_id}/collateral")
def list_loan_collateral(
    application_id: int,
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "read")
    application = _application_for_membership(db, membership, application_id)
    rows = db.query(SaccoLoanCollateral).filter_by(
        organization_id=membership.organization_id, application_id=application.id
    ).order_by(SaccoLoanCollateral.id.asc()).all()
    return {"items": [_collateral_out(row) for row in rows]}


@router.post("/loan-collateral/{collateral_id}/verification")
def verify_loan_collateral(
    collateral_id: int,
    payload: SaccoLoanCollateralVerificationIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "verify_collateral")
    row = db.query(SaccoLoanCollateral).filter_by(
        organization_id=membership.organization_id, id=collateral_id
    ).with_for_update().first()
    if not row:
        raise HTTPException(404, "Loan collateral record not found")
    application = _application_for_membership(db, membership, row.application_id, for_update=True)
    if application.status in {"approved_pending_disbursement", "rejected"}:
        raise HTTPException(409, "Collateral verification is locked after the credit decision")
    if row.status != "pending_verification":
        raise HTTPException(409, "Collateral has already been verified or rejected")
    if application.created_by == user.id or row.created_by == user.id:
        raise HTTPException(403, "The application or collateral recorder cannot verify their own submission")
    row.status = "verified" if payload.decision == "verify" else "rejected"
    row.verification_note = payload.note
    row.verified_by = user.id
    row.verified_at = datetime.now(timezone.utc)
    product = _product_for_application(db, membership, application)
    _advance_application(db, membership, application, product)
    _audit(db, user, membership, "sacco.loan_collateral.verified", "sacco_loan_collateral", row.id,
           f"application_id={application.id};decision={payload.decision}")
    db.commit()
    db.refresh(row)
    return _collateral_out(row)


@router.post("/loan-applications/{application_id}/assessment")
def assess_loan_application(
    application_id: int,
    payload: SaccoLoanAssessmentIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "assess")
    application = _application_for_membership(db, membership, application_id, for_update=True)
    if application.status not in {"pending_assessment", "pending_guarantors"}:
        raise HTTPException(409, "Only applications awaiting assessment or guarantors can be assessed")
    if application.created_by == user.id:
        raise HTTPException(403, "The loan application creator cannot perform its credit assessment")
    product = _product_for_application(db, membership, application)
    payment = monthly_installment(application.principal, product.annual_interest_rate_bps, application.term_months)
    ratio = int((
        ((application.monthly_existing_debt + payment) / application.monthly_net_income) * Decimal("10000")
    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    application.estimated_monthly_installment = payment
    application.debt_service_ratio_bps = ratio
    application.assessment_status = "eligible" if ratio <= product.maximum_debt_service_ratio_bps else "ineligible"
    application.assessment_note = payload.note
    application.assessed_by = user.id
    application.assessed_at = datetime.now(timezone.utc)
    _advance_application(db, membership, application, product)
    _audit(db, user, membership, "sacco.loan_application.assessed", "sacco_loan_application", application.id,
           f"assessment={application.assessment_status};dsr_bps={ratio};status={application.status}")
    db.commit()
    db.refresh(application)
    return _application_out(application)


@router.post("/loan-applications/{application_id}/decision")
def decide_loan_application(
    application_id: int,
    payload: SaccoLoanDecisionIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "decide")
    application = _application_for_membership(db, membership, application_id, for_update=True)
    if application.status != "pending_approval" or application.assessment_status != "eligible":
        raise HTTPException(409, "Application must pass assessment, guarantor and collateral checks before approval")
    if application.created_by == user.id or application.assessed_by == user.id:
        raise HTTPException(403, "The application creator or credit assessor cannot decide the same loan")
    product = _product_for_application(db, membership, application)
    if payload.decision == "approve":
        schedule = projected_schedule(
            application.principal, product.annual_interest_rate_bps,
            application.term_months, application.first_repayment_date,
        )
        for item in schedule:
            db.add(SaccoLoanInstallment(
                organization_id=membership.organization_id, application_id=application.id,
                installment_number=item["installment_number"], due_date=item["due_date"],
                principal_due=item["principal_due"], interest_due=item["interest_due"],
                total_due=item["total_due"], currency=product.currency, status="projected",
            ))
        application.status = "approved_pending_disbursement"
    else:
        application.status = "rejected"
    application.decided_by = user.id
    application.decided_at = datetime.now(timezone.utc)
    application.decision_note = payload.note
    _audit(db, user, membership, "sacco.loan_application.decided", "sacco_loan_application", application.id,
           f"decision={payload.decision};status={application.status}")
    db.commit()
    db.refresh(application)
    return _application_out(application)


@router.get("/loan-applications/{application_id}/schedule")
def get_loan_schedule(
    application_id: int,
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "read")
    application = _application_for_membership(db, membership, application_id)
    rows = db.query(SaccoLoanInstallment).filter_by(
        organization_id=membership.organization_id, application_id=application.id
    ).order_by(SaccoLoanInstallment.installment_number.asc()).all()
    return {"application_id": application.id, "status": application.status,
            "schedule_type": (
                "settled" if application.status == "settled"
                else "activated_after_staff_verified_disbursement"
                if application.status == "active" else "projected_until_verified_disbursement"
            ),
            "balance": _loan_balance_values(db, membership, application),
            "items": [_installment_out(row) for row in rows]}


@router.get("/loan-applications/{application_id}/summary")
def get_loan_application_summary(
    application_id: int,
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "read")
    application = _application_for_membership(db, membership, application_id)
    product = _product_for_application(db, membership, application)
    guarantors = _guarantor_query(db, membership, application.id).all()
    collateral = db.query(SaccoLoanCollateral).filter_by(
        organization_id=membership.organization_id, application_id=application.id
    ).all()
    return {
        "application": _application_out(application),
        "product": _product_out(product),
        "guarantors": [_guarantor_out(row) for row in guarantors],
        "collateral": [_collateral_out(row) for row in collateral],
    }



def _disbursement_out(row: SaccoLoanDisbursement) -> dict:
    return {
        "id": row.id, "application_id": row.application_id,
        "amount": format(row.amount, ".2f"), "currency": row.currency,
        "channel": row.channel, "external_reference": row.external_reference,
        "value_date": row.value_date.isoformat(), "status": row.status,
        "request_note": row.request_note, "requested_by": row.requested_by,
        "reviewed_by": row.reviewed_by, "reviewed_at": row.reviewed_at,
        "review_note": row.review_note, "created_at": row.created_at,
    }


@router.post("/loan-applications/{application_id}/disbursements", status_code=201)
def request_loan_disbursement(
    application_id: int,
    payload: SaccoLoanDisbursementCreateIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "request_disbursement")
    application = _application_for_membership(db, membership, application_id, for_update=True)
    fingerprint = transaction_fingerprint(payload.model_dump(mode="json", exclude={"idempotency_key"}))
    replay = db.query(SaccoLoanDisbursement).filter_by(
        organization_id=membership.organization_id, idempotency_key=payload.idempotency_key
    ).first()
    if replay:
        if replay.application_id != application.id or replay.request_fingerprint != fingerprint:
            raise HTTPException(409, "Idempotency key was already used for different disbursement evidence")
        return _disbursement_out(replay)

    if application.status != "approved_pending_disbursement":
        raise HTTPException(409, "Only an approved loan awaiting disbursement can be disbursed")
    if user.id in {application.created_by, application.assessed_by, application.decided_by}:
        raise HTTPException(403, "The application creator, assessor or credit approver cannot request its disbursement")
    product = _product_for_application(db, membership, application)
    if payload.amount != application.principal:
        raise HTTPException(422, "This workflow requires one full-principal disbursement; partial disbursement is not supported")
    if payload.currency != product.currency:
        raise HTTPException(409, "Disbursement currency must match the approved loan product")
    if payload.value_date >= application.first_repayment_date:
        raise HTTPException(409, "Disbursement value date must precede the first contractual repayment date")
    if application.decided_at and payload.value_date < application.decided_at.date():
        raise HTTPException(409, "Disbursement value date cannot precede the credit approval date")

    pending = db.query(SaccoLoanDisbursement).filter_by(
        organization_id=membership.organization_id, application_id=application.id,
        status="pending_verification",
    ).first()
    if pending:
        raise HTTPException(409, "A disbursement evidence request is already awaiting review")
    verified = db.query(SaccoLoanDisbursement).filter_by(
        organization_id=membership.organization_id, application_id=application.id,
        status="verified",
    ).first()
    if verified:
        raise HTTPException(409, "This loan already has a verified disbursement")

    row = SaccoLoanDisbursement(
        organization_id=membership.organization_id, application_id=application.id,
        amount=payload.amount, currency=payload.currency, channel=payload.channel,
        external_reference=payload.external_reference, value_date=payload.value_date,
        status="pending_verification", request_note=payload.request_note,
        requested_by=user.id, idempotency_key=payload.idempotency_key,
        request_fingerprint=fingerprint,
    )
    db.add(row)
    try:
        db.flush()
        _audit(db, user, membership, "sacco.loan_disbursement.requested",
               "sacco_loan_disbursement", row.id,
               f"application_id={application.id};amount={row.amount};currency={row.currency};channel={row.channel}")
        db.commit()
        db.refresh(row)
        return _disbursement_out(row)
    except IntegrityError:
        db.rollback()
        replay = db.query(SaccoLoanDisbursement).filter_by(
            organization_id=membership.organization_id, idempotency_key=payload.idempotency_key
        ).first()
        if replay and replay.request_fingerprint == fingerprint:
            return _disbursement_out(replay)
        raise HTTPException(409, "A disbursement request is already pending or the idempotency key conflicts")


@router.get("/loan-applications/{application_id}/disbursements")
def list_loan_disbursements(
    application_id: int,
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "read")
    application = _application_for_membership(db, membership, application_id)
    rows = db.query(SaccoLoanDisbursement).filter_by(
        organization_id=membership.organization_id, application_id=application.id
    ).order_by(SaccoLoanDisbursement.created_at.desc(), SaccoLoanDisbursement.id.desc()).all()
    return {"items": [_disbursement_out(row) for row in rows]}


@router.post("/loan-disbursements/{disbursement_id}/verification")
def verify_loan_disbursement(
    disbursement_id: int,
    payload: SaccoLoanDisbursementVerificationIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "verify_disbursement")
    row = db.query(SaccoLoanDisbursement).filter_by(
        organization_id=membership.organization_id, id=disbursement_id
    ).with_for_update().first()
    if not row:
        raise HTTPException(404, "SACCO loan disbursement not found")
    application = _application_for_membership(db, membership, row.application_id, for_update=True)
    if row.status != "pending_verification":
        raise HTTPException(409, "Only pending disbursement evidence can be reviewed")
    if user.id in {
        row.requested_by, application.created_by, application.assessed_by, application.decided_by
    }:
        raise HTTPException(403, "Disbursement reviewer must be independent of application and evidence preparation")
    row.reviewed_by = user.id
    row.reviewed_at = datetime.now(timezone.utc)
    row.review_note = payload.note
    row.updated_at = datetime.now(timezone.utc)
    if payload.decision == "verify":
        if application.status != "approved_pending_disbursement":
            raise HTTPException(409, "Loan is no longer awaiting disbursement")
        if row.value_date >= application.first_repayment_date:
            raise HTTPException(409, "Disbursement date conflicts with the first contractual repayment date")
        row.status = "verified"
        # Flush evidence first: the PostgreSQL application trigger requires a
        # visible verified disbursement before allowing the loan to become active.
        db.flush()
        application.status = "active"
        db.query(SaccoLoanInstallment).filter(
            SaccoLoanInstallment.organization_id == membership.organization_id,
            SaccoLoanInstallment.application_id == application.id,
            SaccoLoanInstallment.status == "projected",
            SaccoLoanInstallment.due_date <= date.today(),
        ).update({"status": "due"}, synchronize_session=False)
        action = "sacco.loan_disbursement.verified"
    else:
        row.status = "rejected"
        action = "sacco.loan_disbursement.rejected"
    _audit(db, user, membership, action, "sacco_loan_disbursement", row.id,
           f"application_id={application.id};decision={payload.decision};application_status={application.status}")
    db.commit()
    db.refresh(row)
    return _disbursement_out(row)


def _repayment_query(db: Session, membership: Membership):
    query = db.query(SaccoLoanRepayment).join(
        SaccoLoanApplication,
        (SaccoLoanApplication.organization_id == SaccoLoanRepayment.organization_id)
        & (SaccoLoanApplication.id == SaccoLoanRepayment.application_id),
    ).filter(SaccoLoanRepayment.organization_id == membership.organization_id)
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            query = query.filter(SaccoLoanApplication.id == -1)
        else:
            query = query.filter(SaccoLoanApplication.branch_id.in_(allowed))
    return query


def _repayment_for_membership(
    db: Session, membership: Membership, repayment_id: int, *, for_update: bool = False,
) -> SaccoLoanRepayment:
    query = _repayment_query(db, membership).filter(SaccoLoanRepayment.id == repayment_id)
    if for_update:
        query = query.with_for_update()
    row = query.first()
    if not row:
        raise HTTPException(404, "SACCO loan repayment not found")
    return row


def _loan_balance_values(
    db: Session, membership: Membership, application: SaccoLoanApplication,
    as_of: date | None = None,
) -> dict:
    as_of = as_of or date.today()
    rows = db.query(SaccoLoanInstallment).filter_by(
        organization_id=membership.organization_id, application_id=application.id,
    ).order_by(SaccoLoanInstallment.due_date, SaccoLoanInstallment.installment_number).all()
    principal_outstanding = sum(
        (row.principal_due - row.principal_paid for row in rows if row.status != "waived"),
        Decimal("0.00"),
    )
    interest_outstanding = sum(
        (row.interest_due - row.interest_paid for row in rows if row.status != "waived"),
        Decimal("0.00"),
    )
    due_rows = [row for row in rows if row.due_date <= as_of and row.status not in {"paid", "waived"}]
    overdue_rows = [row for row in due_rows if row.due_date < as_of]
    due_amount = sum(
        (row.total_due - row.principal_paid - row.interest_paid for row in due_rows),
        Decimal("0.00"),
    )
    overdue_amount = sum(
        (row.total_due - row.principal_paid - row.interest_paid for row in overdue_rows),
        Decimal("0.00"),
    )
    next_due = next(
        (row.due_date for row in rows
         if row.due_date > as_of and row.status not in {"paid", "waived"}
         and row.total_due - row.principal_paid - row.interest_paid > 0),
        None,
    )
    currency = rows[0].currency if rows else _product_for_application(db, membership, application).currency
    return {
        "application_id": application.id,
        "status": application.status,
        "currency": currency,
        "as_of_date": as_of.isoformat(),
        "principal_outstanding": format(principal_outstanding, ".2f"),
        "interest_outstanding": format(interest_outstanding, ".2f"),
        "scheduled_total_outstanding": format(principal_outstanding + interest_outstanding, ".2f"),
        "amount_due": format(due_amount, ".2f"),
        "overdue_amount": format(overdue_amount, ".2f"),
        "next_due_date": next_due.isoformat() if next_due else None,
    }


def _repayment_out(row: SaccoLoanRepayment) -> dict:
    return {
        "id": row.id, "application_id": row.application_id,
        "amount": format(row.amount, ".2f"), "currency": row.currency,
        "channel": row.channel, "external_reference": row.external_reference,
        "value_date": row.value_date.isoformat(), "status": row.status,
        "request_note": row.request_note, "requested_by": row.requested_by,
        "reviewed_by": row.reviewed_by, "reviewed_at": row.reviewed_at,
        "review_note": row.review_note, "created_at": row.created_at,
    }


def _repayment_allocation_out(row: SaccoLoanRepaymentAllocation) -> dict:
    return {
        "installment_id": row.installment_id,
        "principal_amount": format(row.principal_amount, ".2f"),
        "interest_amount": format(row.interest_amount, ".2f"),
        "currency": row.currency,
    }


def _repayment_journal_out(row: SaccoLoanRepaymentJournalLine) -> dict:
    return {
        "line_number": row.line_number, "account_code": row.account_code,
        "debit": format(row.debit, ".2f"), "credit": format(row.credit, ".2f"),
        "currency": row.currency, "branch_id": row.branch_id,
    }


@router.get("/loan-applications/{application_id}/balance")
def get_loan_balance(
    application_id: int,
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "read")
    application = _application_for_membership(db, membership, application_id)
    return _loan_balance_values(db, membership, application)


@router.post("/loan-applications/{application_id}/repayments", status_code=201)
def request_loan_repayment(
    application_id: int,
    payload: SaccoLoanRepaymentCreateIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "request_repayment")
    application = _application_for_membership(db, membership, application_id, for_update=True)
    fingerprint = transaction_fingerprint(
        payload.model_dump(mode="json", exclude={"idempotency_key"})
    )
    replay = db.query(SaccoLoanRepayment).filter_by(
        organization_id=membership.organization_id,
        idempotency_key=payload.idempotency_key,
    ).first()
    if replay:
        if replay.application_id != application.id or replay.request_fingerprint != fingerprint:
            raise HTTPException(409, "Idempotency key was already used for different repayment evidence")
        return _repayment_out(replay)

    if application.status != "active":
        raise HTTPException(409, "Only active loans can receive repayment evidence")
    if user.id in {application.created_by, application.assessed_by, application.decided_by}:
        raise HTTPException(403, "The loan creator, assessor or credit approver cannot prepare its repayment evidence")
    product = _product_for_application(db, membership, application)
    if payload.currency != product.currency:
        raise HTTPException(409, "Repayment currency must match the approved loan product")
    disbursement = db.query(SaccoLoanDisbursement).filter_by(
        organization_id=membership.organization_id,
        application_id=application.id,
        status="verified",
    ).first()
    if not disbursement:
        raise HTTPException(409, "Verified disbursement evidence is required before repayment")
    if payload.value_date < disbursement.value_date:
        raise HTTPException(422, "Repayment value date cannot precede the verified disbursement date")

    due_rows = db.query(SaccoLoanInstallment).filter(
        SaccoLoanInstallment.organization_id == membership.organization_id,
        SaccoLoanInstallment.application_id == application.id,
        SaccoLoanInstallment.due_date <= payload.value_date,
        SaccoLoanInstallment.status.in_(["due", "overdue", "partially_paid"]),
    ).order_by(
        SaccoLoanInstallment.due_date.asc(),
        SaccoLoanInstallment.installment_number.asc(),
    ).with_for_update().all()
    due_outstanding = sum(
        (row.total_due - row.principal_paid - row.interest_paid for row in due_rows),
        Decimal("0.00"),
    )
    if due_outstanding <= 0:
        raise HTTPException(409, "No contractual installment balance is due on this value date")
    if payload.amount > due_outstanding:
        raise HTTPException(422, "Repayment exceeds the outstanding installments due on its value date; advance and early-settlement payments are not enabled")

    pending = db.query(SaccoLoanRepayment).filter_by(
        organization_id=membership.organization_id,
        application_id=application.id,
        status="pending_verification",
    ).first()
    if pending:
        raise HTTPException(409, "A repayment receipt is already awaiting independent verification")

    row = SaccoLoanRepayment(
        organization_id=membership.organization_id,
        application_id=application.id,
        amount=payload.amount, currency=payload.currency,
        channel=payload.channel, external_reference=payload.external_reference,
        value_date=payload.value_date, status="pending_verification",
        request_note=payload.request_note, requested_by=user.id,
        idempotency_key=payload.idempotency_key, request_fingerprint=fingerprint,
    )
    db.add(row)
    try:
        db.flush()
        _audit(
            db, user, membership, "sacco.loan_repayment.requested",
            "sacco_loan_repayment", row.id,
            f"application_id={application.id};amount={row.amount};currency={row.currency};channel={row.channel}",
        )
        db.commit()
        db.refresh(row)
        return _repayment_out(row)
    except IntegrityError:
        db.rollback()
        replay = db.query(SaccoLoanRepayment).filter_by(
            organization_id=membership.organization_id,
            idempotency_key=payload.idempotency_key,
        ).first()
        if replay and replay.application_id == application.id and replay.request_fingerprint == fingerprint:
            return _repayment_out(replay)
        raise HTTPException(409, "A repayment receipt is already pending or the idempotency/reference conflicts")


@router.get("/loan-applications/{application_id}/repayments")
def list_loan_repayments(
    application_id: int,
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    _require_permission(membership, "read")
    application = _application_for_membership(db, membership, application_id)
    rows = _repayment_query(db, membership).filter(
        SaccoLoanRepayment.application_id == application.id
    ).order_by(SaccoLoanRepayment.created_at.desc(), SaccoLoanRepayment.id.desc()).all()
    items = []
    for row in rows:
        allocations = db.query(SaccoLoanRepaymentAllocation).filter_by(
            organization_id=membership.organization_id, repayment_id=row.id,
        ).order_by(SaccoLoanRepaymentAllocation.id).all()
        journal = db.query(SaccoLoanRepaymentJournalLine).filter_by(
            organization_id=membership.organization_id, repayment_id=row.id,
        ).order_by(SaccoLoanRepaymentJournalLine.line_number).all()
        items.append({
            **_repayment_out(row),
            "allocations": [_repayment_allocation_out(item) for item in allocations],
            "journal_lines": [_repayment_journal_out(item) for item in journal],
        })
    return {"application_id": application.id, "items": items}


@router.post("/loan-repayments/{repayment_id}/verification")
def verify_loan_repayment(
    repayment_id: int,
    payload: SaccoLoanRepaymentVerificationIn,
    user: User = Depends(current_user),
    membership: Membership = Depends(active_membership),
    db: Session = Depends(get_db),
):
    action_permission = "verify_repayment"
    _require_permission(membership, action_permission)
    row = _repayment_for_membership(db, membership, repayment_id, for_update=True)
    application = _application_for_membership(
        db, membership, row.application_id, for_update=True,
    )
    if row.status != "pending_verification":
        raise HTTPException(409, "Only pending repayment evidence can be reviewed")
    if user.id in {
        row.requested_by, application.created_by, application.assessed_by, application.decided_by,
    }:
        raise HTTPException(403, "Repayment reviewer must be independent of receipt preparation and loan approval")

    now = datetime.now(timezone.utc)
    row.reviewed_by = user.id
    row.reviewed_at = now
    row.review_note = payload.note

    if payload.decision == "reject":
        row.status = "rejected"
        action = "sacco.loan_repayment.rejected"
    else:
        if application.status != "active":
            raise HTTPException(409, "Only an active loan can receive a verified repayment")
        disbursement = db.query(SaccoLoanDisbursement).filter_by(
            organization_id=membership.organization_id,
            application_id=application.id, status="verified",
        ).first()
        if not disbursement or row.value_date < disbursement.value_date:
            raise HTTPException(409, "Verified disbursement evidence and a valid repayment value date are required")
        installments = db.query(SaccoLoanInstallment).filter(
            SaccoLoanInstallment.organization_id == membership.organization_id,
            SaccoLoanInstallment.application_id == application.id,
            SaccoLoanInstallment.due_date <= row.value_date,
            SaccoLoanInstallment.status.in_(["due", "overdue", "partially_paid"]),
        ).order_by(
            SaccoLoanInstallment.due_date.asc(),
            SaccoLoanInstallment.installment_number.asc(),
        ).with_for_update().all()
        try:
            allocations = allocate_due_repayment(row.amount, installments)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        if not allocations or sum(
            (item["principal_amount"] + item["interest_amount"] for item in allocations),
            Decimal("0.00"),
        ) != row.amount:
            raise HTTPException(409, "The verified receipt cannot be fully allocated to contractual installments")

        row.status = "verified"
        row.updated_at = now
        try:
            db.flush()
            allocation_rows = []
            allocation_by_installment = {}
            principal_total = Decimal("0.00")
            interest_total = Decimal("0.00")
            for item in allocations:
                allocation = SaccoLoanRepaymentAllocation(
                    organization_id=membership.organization_id,
                    repayment_id=row.id, application_id=application.id,
                    installment_id=item["installment_id"],
                    principal_amount=item["principal_amount"],
                    interest_amount=item["interest_amount"],
                    currency=row.currency,
                )
                allocation_rows.append(allocation)
                allocation_by_installment[item["installment_id"]] = item
                principal_total += item["principal_amount"]
                interest_total += item["interest_amount"]
            db.add_all(allocation_rows)
            db.flush()

            for installment in installments:
                item = allocation_by_installment.get(installment.id)
                if not item:
                    continue
                installment.principal_paid += item["principal_amount"]
                installment.interest_paid += item["interest_amount"]
                paid_total = installment.principal_paid + installment.interest_paid
                if paid_total == installment.total_due:
                    installment.status = "paid"
                elif paid_total > 0:
                    installment.status = "partially_paid"
                elif installment.due_date < date.today():
                    installment.status = "overdue"
                else:
                    installment.status = "due"
            db.flush()

            journal_lines = [
                SaccoLoanRepaymentJournalLine(
                    organization_id=membership.organization_id,
                    repayment_id=row.id, line_number=1,
                    account_code="cash_clearing", debit=row.amount,
                    credit=Decimal("0.00"), currency=row.currency,
                    branch_id=application.branch_id,
                )
            ]
            line_number = 2
            if principal_total > 0:
                journal_lines.append(SaccoLoanRepaymentJournalLine(
                    organization_id=membership.organization_id,
                    repayment_id=row.id, line_number=line_number,
                    account_code="loan_principal_receivable",
                    debit=Decimal("0.00"), credit=principal_total,
                    currency=row.currency, branch_id=application.branch_id,
                ))
                line_number += 1
            if interest_total > 0:
                journal_lines.append(SaccoLoanRepaymentJournalLine(
                    organization_id=membership.organization_id,
                    repayment_id=row.id, line_number=line_number,
                    account_code="loan_interest_income",
                    debit=Decimal("0.00"), credit=interest_total,
                    currency=row.currency, branch_id=application.branch_id,
                ))
            db.add_all(journal_lines)
            db.flush()
            remaining_installments = db.query(SaccoLoanInstallment).filter(
                SaccoLoanInstallment.organization_id == membership.organization_id,
                SaccoLoanInstallment.application_id == application.id,
                ~SaccoLoanInstallment.status.in_(["paid", "waived"]),
            ).count()
            if remaining_installments == 0:
                application.status = "settled"
            action = "sacco.loan_repayment.verified"
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Repayment allocation or journal posting conflicted with a concurrent update")

    row.updated_at = datetime.now(timezone.utc)
    _audit(
        db, user, membership, action, "sacco_loan_repayment", row.id,
        f"application_id={application.id};decision={payload.decision};amount={row.amount};status={row.status}",
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Repayment evidence could not be committed; refresh the loan balance and retry")
    db.refresh(row)
    return _repayment_out(row)
