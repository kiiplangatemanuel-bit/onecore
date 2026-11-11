"""SACCO membership onboarding and auditable four-eyes KYC review."""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.authorization import branch_scope_ids, can_access_branch
from app.core.database import get_db
from app.core.models import AuditEvent, Branch, Membership, User
from app.core.sacco_models import SaccoMember
from app.core.sacco_schemas import SaccoKycReviewIn, SaccoMemberCreateIn
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.services.sacco_membership import KYCConfigurationError, decrypt_kyc_payload, encrypt_kyc_payload, identity_fingerprint, request_fingerprint

router = APIRouter(prefix="/api/v1/sacco", tags=["sacco-membership"])
KYC_ACCESS_WINDOW = timedelta(minutes=30)
SACCO_ROLE_PERMISSIONS = {
    "org_admin": {"read", "create", "update", "review"},
    "sacco_manager": {"read", "create", "update", "review"},
    "sacco_officer": {"read", "create"},
    "sacco_kyc_approver": {"read", "review"},
    "sacco_treasurer": {"read", "create"},
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
