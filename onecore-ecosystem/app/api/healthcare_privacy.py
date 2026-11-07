"""Patient privacy, explicit clinical access grants and emergency access."""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.models import (User, Membership, HealthcarePatient, HealthcareAccessGrant,
    HealthcareConsent, HealthcareBreakGlass, HealthcareAccessAudit)
from app.core.schemas import (HealthcarePatientIn, HealthcareAccessGrantIn, HealthcareConsentIn,
    HealthcareBreakGlassIn, HealthcareBreakGlassReviewIn)
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import can_access_branch
from app.services.healthcare_crypto import encrypt_identifier, decrypt_identifier, patient_number_digest

router = APIRouter(prefix="/api/v1/healthcare", tags=["Healthcare privacy and access"])
CLINICAL_ROLES = {"doctor", "nurse", "clinician", "healthcare_professional", "pharmacist",
                  "lab_technician", "radiologist", "midwife", "health_records"}
ADMIN_ROLES = {"org_admin", "branch_admin", "healthcare_admin", "privacy_officer"}
PRIVACY_ROLES = {"org_admin", "healthcare_admin", "privacy_officer"}
GRANTABLE_ROLES = CLINICAL_ROLES


def _role(membership):
    return (membership.role or "").strip().lower()


def _require_role(membership, roles):
    if _role(membership) not in roles:
        raise HTTPException(403, "Healthcare role is not authorized for this operation")


def _patient(db, patient_id, membership):
    row = db.query(HealthcarePatient).filter_by(
        id=patient_id, organization_id=membership.organization_id, status="active"
    ).first()
    if not row or not can_access_branch(membership, row.branch_id):
        raise HTTPException(404, "Patient not found")
    return row


def _active_grant(db, patient, user, membership, write=False):
    now = datetime.now(timezone.utc)
    grants = db.query(HealthcareAccessGrant).filter(
        HealthcareAccessGrant.organization_id == membership.organization_id,
        HealthcareAccessGrant.patient_id == patient.id,
        HealthcareAccessGrant.user_id == user.id,
        HealthcareAccessGrant.revoked_at.is_(None),
        HealthcareAccessGrant.expires_at > now,
    ).all()
    allowed = {"write", "clinical"} if write else {"read", "write", "clinical"}
    grant = next((g for g in grants if g.access_level in allowed), None)
    if grant: return "grant", grant.reason
    emergency = db.query(HealthcareBreakGlass).filter(
        HealthcareBreakGlass.organization_id == membership.organization_id,
        HealthcareBreakGlass.patient_id == patient.id,
        HealthcareBreakGlass.user_id == user.id,
        HealthcareBreakGlass.expires_at > now,
    ).order_by(HealthcareBreakGlass.id.desc()).first()
    if emergency: return "break_glass", emergency.reason
    raise HTTPException(403, "No active patient-specific healthcare access grant")


def _audit(db, patient, user, action, mode, reason=""):
    db.add(HealthcareAccessAudit(organization_id=patient.organization_id,
        patient_id=patient.id, actor_user_id=user.id, action=action,
        access_mode=mode, reason=(reason or "")[:1000]))
    db.commit()


def _patient_out(row):
    return {"id": row.id, "patient_number": decrypt_identifier(row.patient_number_hash)
            if False else None,
            "full_name": decrypt_identifier(row.full_name_encrypted),
            "date_of_birth": decrypt_identifier(row.date_of_birth_encrypted),
            "phone": decrypt_identifier(row.phone_encrypted),
            "branch_id": row.branch_id, "status": row.status}


@router.post("/patients", status_code=201)
def register_patient(payload: HealthcarePatientIn, membership=Depends(active_membership),
                     user: User=Depends(current_user), db: Session=Depends(get_db)):
    _require_role(membership, ADMIN_ROLES | {"health_records"})
    if payload.branch_id and not can_access_branch(membership, payload.branch_id):
        raise HTTPException(403, "Branch is outside your healthcare scope")
    digest = patient_number_digest(payload.patient_number)
    if db.query(HealthcarePatient.id).filter_by(
        organization_id=membership.organization_id, patient_number_hash=digest
    ).first():
        raise HTTPException(409, "Patient number already exists in this organization")
    row = HealthcarePatient(organization_id=membership.organization_id,
        branch_id=payload.branch_id, patient_number_hash=digest,
        full_name_encrypted=encrypt_identifier(payload.full_name.strip()),
        date_of_birth_encrypted=encrypt_identifier(payload.date_of_birth.isoformat() if payload.date_of_birth else None),
        phone_encrypted=encrypt_identifier(payload.phone.strip() if payload.phone else None),
        created_by=user.id)
    db.add(row); db.commit(); db.refresh(row)
    # Registering a patient does not silently grant the registrar access to the chart.
    _audit(db, row, user, "patient.registered", "administrative", "Patient registration")
    return {"id": row.id, "status": row.status, "access_grant_required": True}


@router.post("/patients/{patient_id}/access-grants", status_code=201)
def grant_patient_access(patient_id: int, payload: HealthcareAccessGrantIn,
                         membership=Depends(active_membership), user: User=Depends(current_user),
                         db: Session=Depends(get_db)):
    _require_role(membership, ADMIN_ROLES)
    patient = _patient(db, patient_id, membership)
    if payload.expires_at.tzinfo is None or payload.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(422, "Grant expiry must be a future timezone-aware timestamp")
    if payload.expires_at > datetime.now(timezone.utc) + timedelta(days=365):
        raise HTTPException(422, "Healthcare grants cannot exceed 365 days")
    target = db.query(Membership).filter_by(user_id=payload.user_id,
        organization_id=membership.organization_id, is_active=True).first()
    if not target or _role(target) not in GRANTABLE_ROLES:
        raise HTTPException(422, "Target user must have an active clinical/health-records membership")
    if not can_access_branch(target, patient.branch_id):
        raise HTTPException(422, "Target user's branch scope does not include this patient")
    row = HealthcareAccessGrant(organization_id=membership.organization_id,
        patient_id=patient.id, user_id=payload.user_id, access_level=payload.access_level,
        reason=payload.reason.strip(), granted_by=user.id, expires_at=payload.expires_at)
    db.add(row); db.commit(); db.refresh(row)
    _audit(db, patient, user, "access.granted", "administrative", payload.reason)
    return {"id": row.id, "patient_id": patient.id, "user_id": row.user_id,
            "access_level": row.access_level, "expires_at": row.expires_at.isoformat()}


@router.post("/patients/{patient_id}/access-grants/{grant_id}/revoke")
def revoke_patient_access(patient_id: int, grant_id: int, membership=Depends(active_membership),
                          user: User=Depends(current_user), db: Session=Depends(get_db)):
    _require_role(membership, ADMIN_ROLES)
    patient = _patient(db, patient_id, membership)
    row = db.query(HealthcareAccessGrant).filter_by(id=grant_id,
        organization_id=membership.organization_id, patient_id=patient.id,
        revoked_at=None).first()
    if not row: raise HTTPException(404, "Active access grant not found")
    row.revoked_at = datetime.now(timezone.utc)
    db.commit()
    _audit(db, patient, user, "access.revoked", "administrative", f"grant:{grant_id}")
    return {"revoked": True, "grant_id": grant_id}


@router.get("/patients")
def list_assigned_patients(membership=Depends(active_membership), user: User=Depends(current_user),
                           db: Session=Depends(get_db), limit: int=Query(100, ge=1, le=500)):
    _require_role(membership, CLINICAL_ROLES)
    now = datetime.now(timezone.utc)
    patient_ids = db.query(HealthcareAccessGrant.patient_id).filter(
        HealthcareAccessGrant.organization_id == membership.organization_id,
        HealthcareAccessGrant.user_id == user.id, HealthcareAccessGrant.revoked_at.is_(None),
        HealthcareAccessGrant.expires_at > now).distinct().subquery()
    rows = db.query(HealthcarePatient).filter(
        HealthcarePatient.organization_id == membership.organization_id,
        HealthcarePatient.status == "active", HealthcarePatient.id.in_(patient_ids)
    ).order_by(HealthcarePatient.id.desc()).limit(limit).all()
    rows = [r for r in rows if can_access_branch(membership, r.branch_id)]
    for row in rows: _audit(db, row, user, "patient.listed", "grant", "Assigned patient list")
    return [_patient_out(r) for r in rows]


@router.get("/patients/{patient_id}")
def read_patient(patient_id: int, membership=Depends(active_membership),
                 user: User=Depends(current_user), db: Session=Depends(get_db)):
    _require_role(membership, CLINICAL_ROLES)
    patient = _patient(db, patient_id, membership)
    mode, reason = _active_grant(db, patient, user, membership)
    result = _patient_out(patient)
    _audit(db, patient, user, "patient.read", mode, reason)
    return result


@router.post("/patients/{patient_id}/consents", status_code=201)
def record_patient_consent(patient_id: int, payload: HealthcareConsentIn,
                           membership=Depends(active_membership), user: User=Depends(current_user),
                           db: Session=Depends(get_db)):
    _require_role(membership, ADMIN_ROLES | CLINICAL_ROLES)
    patient = _patient(db, patient_id, membership)
    if payload.expires_at and (payload.expires_at.tzinfo is None or payload.expires_at <= datetime.now(timezone.utc)):
        raise HTTPException(422, "Consent expiry must be a future timezone-aware timestamp")
    row = HealthcareConsent(organization_id=membership.organization_id, patient_id=patient.id,
        purpose=payload.purpose, decision=payload.decision, scope=payload.scope,
        reason=payload.reason, recorded_by=user.id, expires_at=payload.expires_at)
    db.add(row); db.commit(); db.refresh(row)
    _audit(db, patient, user, "consent.recorded", "administrative", f"{row.purpose}:{row.decision}")
    return {"id": row.id, "purpose": row.purpose, "decision": row.decision,
            "created_at": row.created_at.isoformat()}


@router.get("/patients/{patient_id}/consents")
def list_patient_consents(patient_id: int, membership=Depends(active_membership),
                          user: User=Depends(current_user), db: Session=Depends(get_db)):
    _require_role(membership, PRIVACY_ROLES)
    patient = _patient(db, patient_id, membership)
    rows = db.query(HealthcareConsent).filter_by(
        organization_id=membership.organization_id, patient_id=patient.id
    ).order_by(HealthcareConsent.id.desc()).all()
    _audit(db, patient, user, "consent.viewed", "administrative", "Consent register viewed")
    return [{"id": r.id, "purpose": r.purpose, "decision": r.decision, "scope": r.scope,
             "reason": r.reason, "expires_at": r.expires_at.isoformat() if r.expires_at else None,
             "created_at": r.created_at.isoformat()} for r in rows]


@router.post("/patients/{patient_id}/break-glass", status_code=201)
def request_break_glass(patient_id: int, payload: HealthcareBreakGlassIn,
                        membership=Depends(active_membership), user: User=Depends(current_user),
                        db: Session=Depends(get_db)):
    _require_role(membership, CLINICAL_ROLES)
    patient = _patient(db, patient_id, membership)
    expires = datetime.now(timezone.utc) + timedelta(minutes=payload.duration_minutes)
    row = HealthcareBreakGlass(organization_id=membership.organization_id,
        patient_id=patient.id, user_id=user.id, reason=payload.reason.strip(), expires_at=expires)
    db.add(row); db.commit(); db.refresh(row)
    _audit(db, patient, user, "break_glass.activated", "break_glass", payload.reason)
    return {"id": row.id, "patient_id": patient.id, "expires_at": expires.isoformat(),
            "mandatory_independent_review": True}


@router.post("/break-glass/{event_id}/review")
def review_break_glass(event_id: int, payload: HealthcareBreakGlassReviewIn,
                       membership=Depends(active_membership), user: User=Depends(current_user),
                       db: Session=Depends(get_db)):
    _require_role(membership, PRIVACY_ROLES)
    event = db.query(HealthcareBreakGlass).filter_by(
        id=event_id, organization_id=membership.organization_id).first()
    if not event: raise HTTPException(404, "Emergency access event not found")
    if event.user_id == user.id: raise HTTPException(403, "Emergency access cannot be self-reviewed")
    if event.reviewed_at: raise HTTPException(409, "Emergency access event already reviewed")
    event.reviewed_by = user.id
    event.reviewed_at = datetime.now(timezone.utc)
    event.review_note = payload.review_note.strip()
    db.commit()
    patient = _patient(db, event.patient_id, membership)
    _audit(db, patient, user, "break_glass.reviewed", "administrative", payload.review_note)
    return {"reviewed": True, "event_id": event.id, "reviewed_at": event.reviewed_at.isoformat()}


@router.get("/access-audit")
def healthcare_access_audit(membership=Depends(active_membership), db: Session=Depends(get_db),
                            limit: int=Query(200, ge=1, le=1000)):
    _require_role(membership, PRIVACY_ROLES)
    rows = db.query(HealthcareAccessAudit).filter_by(
        organization_id=membership.organization_id).order_by(
        HealthcareAccessAudit.id.desc()).limit(limit).all()
    return [{"id": r.id, "patient_id": r.patient_id, "actor_user_id": r.actor_user_id,
             "action": r.action, "access_mode": r.access_mode, "reason": r.reason,
             "created_at": r.created_at.isoformat()} for r in rows]
