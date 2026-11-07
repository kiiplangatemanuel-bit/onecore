"""Healthcare privacy boundary: explicit roles, patient grants, consent, encryption and audited access."""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.models import (User, Membership, HealthcareRoleAssignment, HealthcarePatient,
    HealthcarePatientAccessGrant, HealthcarePatientConsent, HealthcareBreakGlassSession,
    HealthcareAccessAudit, HealthcareAppointment, HealthcareEncounter, AuditEvent)
from app.core.automation_healthcare_schemas import (HealthcareRoleAssignmentIn, HealthcarePatientIn,
    HealthcarePatientGrantIn, HealthcareConsentIn, HealthcareBreakGlassIn,
    HealthcareEncounterIn, HealthcareAppointmentIn)
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import can_access_branch
from app.services.healthcare_crypto import encrypt_health_data, decrypt_health_data
from app.services.datetime_utils import as_utc

router=APIRouter(prefix="/api/v1/healthcare",tags=["Healthcare privacy"])

ROLE_PERMISSIONS={
 "healthcare_admin":{"patient.register","patient.read","clinical.read","clinical.write","appointment.manage","access.manage","privacy.manage","consent.manage","audit.read","breakglass"},
 "clinician":{"patient.read","clinical.read","clinical.write","appointment.manage","breakglass"},
 "nurse":{"patient.read","clinical.read","appointment.manage","breakglass"},
 "receptionist":{"patient.register","patient.read","appointment.manage"},
 "privacy_officer":{"access.manage","privacy.manage","consent.manage","audit.read"},
 "lab_technician":{"patient.read","clinical.read"},
 "pharmacist":{"patient.read","clinical.read"},
}


def _branch_ok(membership,branch_id):
    if not can_access_branch(membership,branch_id):
        raise HTTPException(403,"Healthcare branch is outside your assigned scope")


def _roles(db,membership,user,branch_id):
    if branch_id is not None:
        _branch_ok(membership,branch_id)
    rows=db.query(HealthcareRoleAssignment).filter_by(
        organization_id=membership.organization_id,user_id=user.id,is_active=True).all()
    allowed=(membership.branch_scope or "").strip()
    if branch_id is None:
        if allowed=="*":
            return {x.role for x in rows}
        branch_ids={x.strip() for x in allowed.split(",") if x.strip()}
        return {x.role for x in rows if x.branch_id is None or x.branch_id in branch_ids}
    return {x.role for x in rows if x.branch_id is None or x.branch_id==branch_id}


def _breakglass(db,org,user,patient_id):
    now=datetime.now(timezone.utc)
    rows=db.query(HealthcareBreakGlassSession).filter(
        HealthcareBreakGlassSession.organization_id==org,
        HealthcareBreakGlassSession.user_id==user.id,
        HealthcareBreakGlassSession.patient_id==patient_id,
        HealthcareBreakGlassSession.ended_at.is_(None),
    ).order_by(HealthcareBreakGlassSession.id.desc()).all()
    return next((row for row in rows if as_utc(row.expires_at)>now),None)


def _has_grant(db,org,user,patient_id,permission):
    now=datetime.now(timezone.utc)
    rows=db.query(HealthcarePatientAccessGrant).filter_by(
        organization_id=org,user_id=user.id,patient_id=patient_id,revoked_at=None).all()
    return any(permission in (x.permissions or []) and (x.expires_at is None or as_utc(x.expires_at)>now) for x in rows)


def _authorize(db,membership,user,permission,branch_id=None,patient_id=None,allow_breakglass=False,allow_unscoped=False):
    if branch_id is None and (membership.branch_scope or "").strip()!="*" and not allow_unscoped:
        raise HTTPException(403,"A branch must be selected for branch-scoped healthcare access")
    roles=_roles(db,membership,user,branch_id)
    if branch_id is None and not allow_unscoped:
        org_roles=db.query(HealthcareRoleAssignment).filter_by(
            organization_id=membership.organization_id,user_id=user.id,is_active=True,branch_id=None).all()
        roles={x.role for x in org_roles}
    if not roles:
        raise HTTPException(403,"No active healthcare role assigned for this branch")
    if not any(permission in ROLE_PERMISSIONS.get(role,set()) for role in roles):
        raise HTTPException(403,"Healthcare role does not grant this action")
    emergency=False
    if patient_id is not None and allow_breakglass and "breakglass" in set.union(*(ROLE_PERMISSIONS.get(r,set()) for r in roles)):
        emergency=_breakglass(db,membership.organization_id,user,patient_id) is not None
    if patient_id is not None and "healthcare_admin" not in roles:
        if not emergency and not _has_grant(db,membership.organization_id,user,patient_id,permission):
            raise HTTPException(403,"No active patient-specific access grant for this action")
    return emergency,roles


def _audit(db,membership,user,action,resource_type,resource_id="",patient_id=None,reason="",emergency=False):
    db.add(HealthcareAccessAudit(organization_id=membership.organization_id,
        patient_id=patient_id,actor_user_id=user.id,action=action,resource_type=resource_type,
        resource_id=str(resource_id),reason=reason[:500],emergency=emergency))


def _patient(db,membership,patient_id):
    row=db.query(HealthcarePatient).filter_by(
        id=patient_id,organization_id=membership.organization_id).first()
    if not row or not can_access_branch(membership,row.branch_id):
        raise HTTPException(404,"Patient not found")
    return row


def _active_consent(db,org,patient_id,purpose):
    row=db.query(HealthcarePatientConsent).filter_by(
        organization_id=org,patient_id=patient_id,purpose=purpose).order_by(
        HealthcarePatientConsent.id.desc()).first()
    return bool(row and row.decision=="granted" and (row.expires_at is None or as_utc(row.expires_at)>datetime.now(timezone.utc)))


@router.post("/access/roles",status_code=201)
def assign_healthcare_role(payload:HealthcareRoleAssignmentIn,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    if membership.role not in {"org_admin","branch_admin"}:
        raise HTTPException(403,"Only organization or branch administrators may assign healthcare roles")
    _branch_ok(membership,payload.branch_id)
    if membership.role=="branch_admin" and payload.branch_id is None:
        raise HTTPException(403,"Branch administrators must assign a branch-specific role")
    if membership.role=="branch_admin" and payload.role in {"healthcare_admin","privacy_officer"}:
        raise HTTPException(403,"Only organization administrators may assign healthcare administrator or privacy officer roles")
    target=db.query(Membership).filter_by(organization_id=membership.organization_id,
        user_id=payload.user_id,is_active=True).first()
    if not target:raise HTTPException(404,"Active organization member not found")
    row=HealthcareRoleAssignment(organization_id=membership.organization_id,user_id=payload.user_id,
        branch_id=payload.branch_id,role=payload.role,assigned_by=user.id)
    db.add(row)
    try:db.commit()
    except Exception:
        db.rollback();raise HTTPException(409,"Healthcare role assignment already exists or conflicts")
    db.refresh(row)
    db.add(AuditEvent(actor_user_id=user.id,organization_id=membership.organization_id,
        action="healthcare.role.assigned",resource_type="healthcare_role_assignment",
        resource_id=str(row.id),detail=f"user:{payload.user_id};role:{payload.role};branch:{payload.branch_id or '*'}"))
    db.commit()
    return {"id":row.id,"user_id":row.user_id,"branch_id":row.branch_id,"role":row.role}


@router.get("/access/roles")
def list_healthcare_roles(membership=Depends(active_membership),db:Session=Depends(get_db)):
    if membership.role not in {"org_admin","branch_admin"}:
        raise HTTPException(403,"Only organization or branch administrators may view role assignments")
    q=db.query(HealthcareRoleAssignment).filter_by(organization_id=membership.organization_id,is_active=True)
    rows=q.all()
    return [{"id":x.id,"user_id":x.user_id,"branch_id":x.branch_id,"role":x.role}
        for x in rows if can_access_branch(membership,x.branch_id)]


@router.post("/access/roles/{role_id}/revoke")
def revoke_healthcare_role(role_id:int,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    if membership.role not in {"org_admin","branch_admin"}:
        raise HTTPException(403,"Only organization or branch administrators may revoke healthcare roles")
    row=db.query(HealthcareRoleAssignment).filter_by(
        id=role_id,organization_id=membership.organization_id,is_active=True).first()
    if not row or not can_access_branch(membership,row.branch_id):
        raise HTTPException(404,"Active healthcare role assignment not found")
    if membership.role=="branch_admin" and (row.branch_id is None or row.role in {"healthcare_admin","privacy_officer"}):
        raise HTTPException(403,"Branch administrators cannot revoke organization-wide or privileged roles")
    row.is_active=False
    db.add(AuditEvent(actor_user_id=user.id,organization_id=membership.organization_id,
        action="healthcare.role.revoked",resource_type="healthcare_role_assignment",
        resource_id=str(row.id),detail=f"user:{row.user_id};role:{row.role}"))
    db.commit()
    return {"id":row.id,"status":"revoked"}


@router.post("/patients",status_code=201)
def register_patient(payload:HealthcarePatientIn,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    branch_id=payload.branch_id or None
    _authorize(db,membership,user,"patient.register",branch_id)
    identity={"first_name":payload.first_name,"last_name":payload.last_name,
        "date_of_birth":payload.date_of_birth.isoformat() if payload.date_of_birth else None,
        "phone":payload.phone,"email":str(payload.email) if payload.email else None,
        "emergency_contact_name":payload.emergency_contact_name,
        "emergency_contact_phone":payload.emergency_contact_phone}
    row=HealthcarePatient(organization_id=membership.organization_id,branch_id=branch_id,
        patient_number=payload.patient_number.strip(),identity_ciphertext=encrypt_health_data(identity),
        created_by=user.id)
    db.add(row)
    try:db.commit()
    except Exception:
        db.rollback();raise HTTPException(409,"Patient number already exists in this organization")
    db.refresh(row)
    roles=_roles(db,membership,user,branch_id)
    if "healthcare_admin" not in roles:
        default_permissions=["patient.read","appointment.manage"]
        if "clinician" in roles or "nurse" in roles:default_permissions+=["clinical.read","clinical.write"]
        db.add(HealthcarePatientAccessGrant(organization_id=membership.organization_id,
            patient_id=row.id,user_id=user.id,permissions=default_permissions,
            reason="Patient registration access",granted_by=user.id))
    _audit(db,membership,user,"patient.registered","healthcare_patient",row.id,row.id)
    db.commit()
    return {"id":row.id,"patient_number":row.patient_number,"branch_id":row.branch_id}


@router.get("/patients")
def list_patients(q:str="",limit:int=Query(100,ge=1,le=500),membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    _authorize(db,membership,user,"patient.read",allow_unscoped=True)
    query=db.query(HealthcarePatient).filter_by(organization_id=membership.organization_id)
    allowed=(membership.branch_scope or "").strip()
    if allowed!="*":
        branches=[x.strip() for x in allowed.split(",") if x.strip()]
        query=query.filter(HealthcarePatient.branch_id.in_(branches)) if branches else query.filter(HealthcarePatient.id==-1)
    rows=query.order_by(HealthcarePatient.id.desc()).limit(limit).all()
    results=[]
    for row in rows:
        emergency,roles=_authorize(db,membership,user,"patient.read",row.branch_id,row.id,True)
        data=decrypt_health_data(row.identity_ciphertext)
        if q and q.casefold() not in (row.patient_number+" "+data["first_name"]+" "+data["last_name"]+" "+(data.get("phone") or "")).casefold():continue
        results.append({"id":row.id,"patient_number":row.patient_number,
            "first_name":data["first_name"],"last_name":data["last_name"],
            "phone":data.get("phone"),"branch_id":row.branch_id})
        _audit(db,membership,user,"patient.listed","healthcare_patient",row.id,row.id,emergency=emergency)
    if results:db.commit()
    return results


@router.get("/patients/{patient_id}")
def get_patient(patient_id:int,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=_patient(db,membership,patient_id)
    emergency,_=_authorize(db,membership,user,"patient.read",row.branch_id,row.id,True)
    data=decrypt_health_data(row.identity_ciphertext)
    _audit(db,membership,user,"patient.read","healthcare_patient",row.id,row.id,emergency=emergency)
    db.commit()
    return {"id":row.id,"patient_number":row.patient_number,"branch_id":row.branch_id,**data}


@router.post("/patients/{patient_id}/access-grants",status_code=201)
def grant_patient_access(patient_id:int,payload:HealthcarePatientGrantIn,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    patient=_patient(db,membership,patient_id)
    _authorize(db,membership,user,"access.manage",patient.branch_id)
    target=db.query(Membership).filter_by(organization_id=membership.organization_id,
        user_id=payload.user_id,is_active=True).first()
    if not target:raise HTTPException(404,"Active organization member not found")
    if patient.branch_id and (target.branch_scope or "").strip()!="*" and patient.branch_id not in {
        x.strip() for x in (target.branch_scope or "").split(",") if x.strip()
    }:
        raise HTTPException(403,"Target user does not have membership scope for this patient branch")
    if payload.expires_at and (payload.expires_at.tzinfo is None or payload.expires_at.utcoffset() is None or payload.expires_at<=datetime.now(timezone.utc)):
        raise HTTPException(422,"Grant expiry must be a future timezone-aware timestamp")
    row=HealthcarePatientAccessGrant(organization_id=membership.organization_id,patient_id=patient.id,
        user_id=payload.user_id,permissions=list(dict.fromkeys(payload.permissions)),
        reason=payload.reason.strip(),expires_at=payload.expires_at,granted_by=user.id)
    db.add(row);db.commit();db.refresh(row)
    _audit(db,membership,user,"patient.access_granted","healthcare_patient_access_grant",
        row.id,patient.id,payload.reason);db.commit()
    return {"id":row.id,"patient_id":patient.id,"user_id":row.user_id,
        "permissions":row.permissions,"expires_at":row.expires_at.isoformat() if row.expires_at else None}


@router.get("/patients/{patient_id}/access-grants")
def list_patient_access_grants(patient_id:int,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    patient=_patient(db,membership,patient_id)
    _authorize(db,membership,user,"access.manage",patient.branch_id)
    rows=db.query(HealthcarePatientAccessGrant).filter_by(
        organization_id=membership.organization_id,patient_id=patient.id).order_by(
        HealthcarePatientAccessGrant.id.desc()).all()
    return [{"id":x.id,"user_id":x.user_id,"permissions":x.permissions,"reason":x.reason,
        "created_at":x.created_at.isoformat(),"expires_at":x.expires_at.isoformat() if x.expires_at else None,
        "revoked_at":x.revoked_at.isoformat() if x.revoked_at else None} for x in rows]


@router.post("/patients/{patient_id}/access-grants/{grant_id}/revoke")
def revoke_patient_access(patient_id:int,grant_id:int,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    patient=_patient(db,membership,patient_id);_authorize(db,membership,user,"access.manage",patient.branch_id)
    row=db.query(HealthcarePatientAccessGrant).filter_by(
        id=grant_id,organization_id=membership.organization_id,patient_id=patient.id,revoked_at=None).first()
    if not row:raise HTTPException(404,"Active access grant not found")
    row.revoked_at=datetime.now(timezone.utc)
    _audit(db,membership,user,"patient.access_revoked","healthcare_patient_access_grant",row.id,patient.id)
    db.commit()
    return {"id":row.id,"revoked_at":row.revoked_at.isoformat()}


@router.post("/patients/{patient_id}/consents",status_code=201)
def record_patient_consent(patient_id:int,payload:HealthcareConsentIn,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    patient=_patient(db,membership,patient_id);_authorize(db,membership,user,"consent.manage",patient.branch_id)
    if payload.expires_at and (payload.expires_at.tzinfo is None or payload.expires_at.utcoffset() is None or payload.expires_at<=datetime.now(timezone.utc)):
        raise HTTPException(422,"Consent expiry must be a future timezone-aware timestamp")
    row=HealthcarePatientConsent(organization_id=membership.organization_id,patient_id=patient.id,
        purpose=payload.purpose,decision=payload.decision,evidence_reference=payload.evidence_reference,
        notes=payload.notes,recorded_by=user.id,expires_at=payload.expires_at)
    db.add(row);_audit(db,membership,user,"patient.consent_recorded","healthcare_patient_consent",
        "",patient.id,f"{payload.purpose}:{payload.decision}")
    db.commit();db.refresh(row)
    return {"id":row.id,"patient_id":patient.id,"purpose":row.purpose,
        "decision":row.decision,"recorded_at":row.recorded_at.isoformat()}


@router.get("/patients/{patient_id}/consents")
def list_patient_consents(patient_id:int,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    patient=_patient(db,membership,patient_id);_authorize(db,membership,user,"consent.manage",patient.branch_id)
    rows=db.query(HealthcarePatientConsent).filter_by(
        organization_id=membership.organization_id,patient_id=patient.id).order_by(
        HealthcarePatientConsent.id.desc()).all()
    _audit(db,membership,user,"patient.consent_history_read","healthcare_patient_consent","",patient.id)
    db.commit()
    return [{"id":x.id,"purpose":x.purpose,"decision":x.decision,"evidence_reference":x.evidence_reference,
        "notes":x.notes,"recorded_at":x.recorded_at.isoformat(),
        "expires_at":x.expires_at.isoformat() if x.expires_at else None} for x in rows]


@router.post("/patients/{patient_id}/break-glass",status_code=201)
def open_break_glass(patient_id:int,payload:HealthcareBreakGlassIn,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    patient=_patient(db,membership,patient_id)
    roles=_roles(db,membership,user,patient.branch_id)
    if patient.branch_id is None:
        roles={x.role for x in db.query(HealthcareRoleAssignment).filter_by(
            organization_id=membership.organization_id,user_id=user.id,is_active=True,branch_id=None).all()}
    if not roles.intersection({"healthcare_admin","clinician","nurse"}):
        raise HTTPException(403,"Only clinical staff may request emergency access")
    now=datetime.now(timezone.utc)
    active=_breakglass(db,membership.organization_id,user,patient.id)
    if active:return {"id":active.id,"expires_at":active.expires_at.isoformat(),"already_active":True}
    row=HealthcareBreakGlassSession(organization_id=membership.organization_id,
        patient_id=patient.id,user_id=user.id,justification=payload.justification.strip(),
        started_at=now,expires_at=now+timedelta(minutes=15))
    db.add(row);_audit(db,membership,user,"break_glass.opened","healthcare_break_glass_session",
        "",patient.id,payload.justification,True);db.commit();db.refresh(row)
    return {"id":row.id,"patient_id":patient.id,"expires_at":row.expires_at.isoformat(),
        "warning":"Emergency access is time-limited and fully audited."}


@router.post("/break-glass/{session_id}/close")
def close_break_glass(session_id:int,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=db.query(HealthcareBreakGlassSession).filter_by(
        id=session_id,organization_id=membership.organization_id,user_id=user.id,ended_at=None).first()
    if not row:raise HTTPException(404,"Active emergency session not found")
    row.ended_at=datetime.now(timezone.utc)
    _audit(db,membership,user,"break_glass.closed","healthcare_break_glass_session",
        row.id,row.patient_id,emergency=True);db.commit()
    return {"id":row.id,"ended_at":row.ended_at.isoformat()}


@router.post("/patients/{patient_id}/appointments",status_code=201)
def create_appointment(patient_id:int,payload:HealthcareAppointmentIn,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    patient=_patient(db,membership,patient_id)
    _authorize(db,membership,user,"appointment.manage",patient.branch_id,patient.id)
    if payload.patient_id!=patient.id:raise HTTPException(422,"Appointment patient does not match URL")
    if payload.starts_at<=datetime.now(timezone.utc):raise HTTPException(422,"Appointment must be in the future")
    provider_membership=db.query(Membership).filter_by(
        organization_id=membership.organization_id,user_id=payload.provider_user_id,is_active=True).first()
    if not provider_membership:raise HTTPException(404,"Active provider membership not found")
    if patient.branch_id and (provider_membership.branch_scope or "").strip()!="*" and patient.branch_id not in {
        x.strip() for x in (provider_membership.branch_scope or "").split(",") if x.strip()
    }:
        raise HTTPException(403,"Provider is not assigned to the patient branch")
    provider_roles=db.query(HealthcareRoleAssignment).filter_by(
        organization_id=membership.organization_id,user_id=payload.provider_user_id,is_active=True).all()
    if not any(x.role in {"healthcare_admin","clinician","nurse"} and (x.branch_id is None or x.branch_id==patient.branch_id) for x in provider_roles):
        raise HTTPException(422,"Appointment provider must have an active clinical role in this branch")
    row=HealthcareAppointment(organization_id=membership.organization_id,patient_id=patient.id,
        branch_id=patient.branch_id,provider_user_id=payload.provider_user_id,
        starts_at=payload.starts_at.astimezone(timezone.utc),ends_at=payload.ends_at.astimezone(timezone.utc),
        created_by=user.id)
    db.add(row);_audit(db,membership,user,"appointment.created","healthcare_appointment", "",patient.id)
    db.commit();db.refresh(row)
    return {"id":row.id,"patient_id":row.patient_id,"provider_user_id":row.provider_user_id,
        "starts_at":row.starts_at.isoformat(),"ends_at":row.ends_at.isoformat(),"status":row.status}


@router.post("/patients/{patient_id}/encounters",status_code=201)
def create_encounter(patient_id:int,payload:HealthcareEncounterIn,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    patient=_patient(db,membership,patient_id)
    emergency,_=_authorize(db,membership,user,"clinical.write",patient.branch_id,patient.id,True)
    if not emergency and not _active_consent(db,membership.organization_id,patient.id,"treatment"):
        raise HTTPException(403,"Current treatment consent is required; use documented emergency access only when clinically justified")
    ciphertext=encrypt_health_data(payload.model_dump())
    row=HealthcareEncounter(organization_id=membership.organization_id,patient_id=patient.id,
        provider_user_id=user.id,clinical_ciphertext=ciphertext,status="draft",created_by=user.id)
    db.add(row);_audit(db,membership,user,"encounter.created","healthcare_encounter","",patient.id,emergency=emergency)
    db.commit();db.refresh(row)
    return {"id":row.id,"patient_id":patient.id,"status":row.status}


@router.get("/patients/{patient_id}/encounters")
def list_encounters(patient_id:int,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    patient=_patient(db,membership,patient_id)
    emergency,_=_authorize(db,membership,user,"clinical.read",patient.branch_id,patient.id,True)
    rows=db.query(HealthcareEncounter).filter_by(
        organization_id=membership.organization_id,patient_id=patient.id).order_by(
        HealthcareEncounter.created_at.desc()).limit(200).all()
    results=[]
    for row in rows:
        data=decrypt_health_data(row.clinical_ciphertext)
        results.append({"id":row.id,"provider_user_id":row.provider_user_id,"status":row.status,
            "signed_at":row.signed_at.isoformat() if row.signed_at else None,**data})
    _audit(db,membership,user,"encounter.list_read","healthcare_encounter","",patient.id,emergency=emergency)
    db.commit()
    return results


@router.post("/encounters/{encounter_id}/sign")
def sign_encounter(encounter_id:int,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=db.query(HealthcareEncounter).filter_by(
        id=encounter_id,organization_id=membership.organization_id).first()
    if not row:raise HTTPException(404,"Encounter not found")
    patient=_patient(db,membership,row.patient_id)
    emergency,roles=_authorize(db,membership,user,"clinical.write",patient.branch_id,patient.id,True)
    if row.status!="draft":raise HTTPException(409,"Only draft encounters can be signed")
    if row.provider_user_id!=user.id and "healthcare_admin" not in roles:
        raise HTTPException(403,"Only the encounter author or healthcare administrator may sign")
    if not emergency and not _active_consent(db,membership.organization_id,patient.id,"treatment"):
        raise HTTPException(403,"Current treatment consent is required to sign")
    row.status="signed";row.signed_by=user.id;row.signed_at=datetime.now(timezone.utc)
    _audit(db,membership,user,"encounter.signed","healthcare_encounter",row.id,patient.id,emergency=emergency)
    db.commit()
    return {"id":row.id,"status":row.status,"signed_at":row.signed_at.isoformat()}


@router.get("/audit")
def healthcare_audit(limit:int=Query(100,ge=1,le=500),patient_id:int|None=None,
    membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    _authorize(db,membership,user,"audit.read",allow_unscoped=True)
    q=db.query(HealthcareAccessAudit).filter_by(organization_id=membership.organization_id)
    if patient_id is not None:
        patient=_patient(db,membership,patient_id);q=q.filter(HealthcareAccessAudit.patient_id==patient.id)
    allowed=(membership.branch_scope or "").strip()
    if allowed!="*":
        branches=[x.strip() for x in allowed.split(",") if x.strip()]
        q=q.join(HealthcarePatient,HealthcarePatient.id==HealthcareAccessAudit.patient_id,isouter=True)
        q=q.filter((HealthcareAccessAudit.patient_id.is_(None))|(HealthcarePatient.branch_id.in_(branches)))
    assignments=db.query(HealthcareRoleAssignment).filter_by(
        organization_id=membership.organization_id,user_id=user.id,is_active=True).all()
    if not any(x.role in {"healthcare_admin","privacy_officer"} and x.branch_id is None for x in assignments):
        privacy_branches=[x.branch_id for x in assignments if x.role in {"healthcare_admin","privacy_officer"} and x.branch_id]
        org_privacy=any(x.role in {"healthcare_admin","privacy_officer"} and x.branch_id is None for x in assignments)
        if not org_privacy:
            if not privacy_branches:
                raise HTTPException(403,"No privacy officer assignment for this organization")
            if allowed=="*":
                q=q.join(HealthcarePatient,HealthcarePatient.id==HealthcareAccessAudit.patient_id,isouter=True)
            q=q.filter(HealthcarePatient.branch_id.in_(privacy_branches))
    rows=q.order_by(HealthcareAccessAudit.created_at.desc(),HealthcareAccessAudit.id.desc()).limit(limit).all()
    return [{"id":x.id,"patient_id":x.patient_id,"actor_user_id":x.actor_user_id,
        "action":x.action,"resource_type":x.resource_type,"resource_id":x.resource_id,
        "reason":x.reason,"emergency":x.emergency,"created_at":x.created_at.isoformat()} for x in rows]
