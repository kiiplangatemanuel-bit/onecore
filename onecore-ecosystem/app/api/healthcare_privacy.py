"""Healthcare PHI boundary: branch roles, patient grants, consent and audited emergency access."""
import json
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.core.models import (User, Branch, Membership, HealthcarePatient, HealthcareEncounter,
    HealthcarePatientAccess, HealthcareConsent, HealthcareAccessAudit, HealthcareRoleAssignment,
    HealthcareBreakGlassSession, HealthcareAppointment, AuditEvent)
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import can_access_branch
from app.services.datetime_utils import as_utc
from cryptography.fernet import Fernet, InvalidToken

router=APIRouter(prefix="/api/v1/healthcare",tags=["Healthcare privacy"])
ROLE_PERMISSIONS={
    "healthcare_admin":{"patient.register","patient.read","patient.write","clinical.read","clinical.write",
        "appointment.manage","access.manage","consent.manage","audit.read","breakglass"},
    "clinician":{"patient.read","clinical.read","clinical.write","appointment.manage","breakglass"},
    "nurse":{"patient.read","clinical.read","appointment.manage","breakglass"},
    "receptionist":{"patient.register","appointment.manage"},
    "privacy_officer":{"access.manage","consent.manage","audit.read"},
    "clinical_auditor":{"patient.read","clinical.read","audit.read"},
    "lab_technician":{"patient.read","clinical.read"},
    "pharmacist":{"patient.read","clinical.read"},
}
CONSENT_TYPES={"treatment","data_processing","data_sharing","research","marketing"}


def cipher():
    key=(settings.healthcare_phi_encryption_key or "").strip()
    if not key:
        raise HTTPException(503,"HEALTHCARE_PHI_ENCRYPTION_KEY must be configured before storing patient data")
    try:return Fernet(key.encode("ascii"))
    except Exception:raise HTTPException(503,"HEALTHCARE_PHI_ENCRYPTION_KEY must be a valid Fernet key")


def encrypt(value):
    raw=json.dumps(value,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    return cipher().encrypt(raw).decode("ascii")


def decrypt(value):
    try:return json.loads(cipher().decrypt(value.encode("ascii")).decode("utf-8"))
    except (InvalidToken,ValueError,TypeError,UnicodeError):
        raise HTTPException(503,"Patient data cannot be decrypted; verify the healthcare encryption key")


def _roles(db,m,u,branch_id):
    if branch_id is not None and not can_access_branch(m,branch_id):
        raise HTTPException(403,"Healthcare branch is outside your assigned scope")
    rows=db.query(HealthcareRoleAssignment).filter_by(
        organization_id=m.organization_id,user_id=u.id,is_active=True).all()
    scope=(m.branch_scope or "").strip()
    if branch_id is None:
        if scope=="*":return {x.role for x in rows}
        allowed={x.strip() for x in scope.split(",") if x.strip()}
        return {x.role for x in rows if x.branch_id is None or x.branch_id in allowed}
    return {x.role for x in rows if x.branch_id is None or x.branch_id==branch_id}


def _require(db,m,u,permission,branch_id=None,patient_id=None,allow_breakglass=False,allow_unscoped=False):
    scope=(m.branch_scope or "").strip()
    if branch_id is None and scope!="*" and not allow_unscoped:
        raise HTTPException(403,"Select a branch within your assigned healthcare scope")
    roles=_roles(db,m,u,branch_id)
    if branch_id is None and not allow_unscoped:
        rows=db.query(HealthcareRoleAssignment).filter_by(
            organization_id=m.organization_id,user_id=u.id,is_active=True,branch_id=None).all()
        roles={x.role for x in rows}
    if not roles or not any(permission in ROLE_PERMISSIONS.get(role,set()) for role in roles):
        raise HTTPException(403,"Healthcare role does not grant this action")
    emergency=False
    if patient_id is not None and allow_breakglass and "breakglass" in set().union(*(ROLE_PERMISSIONS.get(r,set()) for r in roles)):
        emergency=_active_breakglass(db,m.organization_id,u.id,patient_id) is not None
    if patient_id is not None and "healthcare_admin" not in roles and not emergency:
        if not _has_access(db,m.organization_id,u.id,patient_id,"write" if permission in {"clinical.write","patient.write"} else "read"):
            raise HTTPException(403,"No active patient-specific care-team grant")
    return emergency,roles


def _active_breakglass(db,org,user_id,patient_id):
    now=datetime.now(timezone.utc)
    rows=db.query(HealthcareBreakGlassSession).filter_by(
        organization_id=org,user_id=user_id,patient_id=patient_id,ended_at=None
    ).order_by(HealthcareBreakGlassSession.id.desc()).all()
    return next((x for x in rows if as_utc(x.expires_at)>now),None)


def _has_access(db,org,user_id,patient_id,level):
    now=datetime.now(timezone.utc)
    rows=db.query(HealthcarePatientAccess).filter_by(
        organization_id=org,user_id=user_id,patient_id=patient_id,revoked_at=None).all()
    return any(x.access_level in ({"write","admin"} if level=="write" else {"read","write","admin"})
        and (x.expires_at is None or as_utc(x.expires_at)>now) for x in rows)


def _patient(db,pid,m):
    row=db.query(HealthcarePatient).filter_by(id=pid,organization_id=m.organization_id).first()
    if not row or not can_access_branch(m,row.branch_id):
        raise HTTPException(404,"Patient not found")
    return row


def _audit(db,m,u,p,action,reason="",emergency=False):
    db.add(HealthcareAccessAudit(organization_id=m.organization_id,patient_id=p.id,
        actor_user_id=u.id,action=action,reason=str(reason)[:500],emergency=emergency))


def _latest_consent(db,org,patient_id,consent_type):
    return db.query(HealthcareConsent).filter_by(
        organization_id=org,patient_id=patient_id,consent_type=consent_type
    ).order_by(HealthcareConsent.id.desc()).first()


def _treatment_allowed(db,org,patient_id):
    row=_latest_consent(db,org,patient_id,"treatment")
    return bool(row and row.decision=="granted" and (row.expires_at is None or as_utc(row.expires_at)>datetime.now(timezone.utc)))


def _branch(db,m,branch_id):
    if branch_id:
        row=db.query(Branch.id).filter_by(id=branch_id,organization_id=m.organization_id,is_active=True).first()
        if not row or not can_access_branch(m,branch_id):raise HTTPException(404,"Branch not found")


@router.post("/access/roles",status_code=201)
def assign_role(payload:dict,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    if m.role not in {"org_admin","branch_admin"}:raise HTTPException(403,"Only organization or branch admins may assign healthcare roles")
    uid=int(payload.get("user_id",0));role=str(payload.get("role",""));branch_id=payload.get("branch_id") or None
    if uid<=0 or role not in ROLE_PERMISSIONS:raise HTTPException(422,"Valid user_id and healthcare role required")
    if m.role=="branch_admin" and (branch_id is None or role in {"healthcare_admin","privacy_officer","clinical_auditor"}):
        raise HTTPException(403,"Branch admins may assign only branch-scoped operational healthcare roles")
    _branch(db,m,branch_id)
    member=db.query(Membership).filter_by(organization_id=m.organization_id,user_id=uid,is_active=True).first()
    target_user=db.query(User).filter_by(id=uid,is_active=True).first()
    if not member or not target_user:raise HTTPException(404,"Active organization member not found")
    allowed={x.strip() for x in (member.branch_scope or "*").split(",") if x.strip()}
    if branch_id and "*" not in allowed and branch_id not in allowed:
        raise HTTPException(403,"Target user is not assigned to this branch")
    duplicate=db.query(HealthcareRoleAssignment.id).filter_by(
        organization_id=m.organization_id,user_id=uid,branch_id=branch_id,role=role,is_active=True).first()
    if duplicate:raise HTTPException(409,"An active healthcare role assignment already exists")
    row=HealthcareRoleAssignment(organization_id=m.organization_id,user_id=uid,branch_id=branch_id,
        role=role,assigned_by=u.id,is_active=True)
    db.add(row)
    try:db.commit()
    except Exception:db.rollback();raise HTTPException(409,"Healthcare role assignment already exists")
    db.refresh(row)
    db.add(AuditEvent(actor_user_id=u.id,organization_id=m.organization_id,action="healthcare.role.assigned",
        resource_type="healthcare_role_assignment",resource_id=str(row.id),detail=f"user:{uid};role:{role};branch:{branch_id or '*'}"))
    db.commit()
    return {"id":row.id,"user_id":uid,"role":role,"branch_id":branch_id}


@router.get("/access/roles")
def list_roles(m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    if m.role not in {"org_admin","branch_admin"}:raise HTTPException(403,"Only organization or branch admins may view healthcare roles")
    rows=db.query(HealthcareRoleAssignment).filter_by(organization_id=m.organization_id,is_active=True).all()
    if m.role=="branch_admin":
        rows=[x for x in rows if x.branch_id is not None and can_access_branch(m,x.branch_id)]
    return [{"id":x.id,"user_id":x.user_id,"branch_id":x.branch_id,"role":x.role}
        for x in rows if m.role=="org_admin" or can_access_branch(m,x.branch_id)]


@router.post("/access/roles/{role_id}/revoke")
def revoke_role(role_id:int,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    if m.role not in {"org_admin","branch_admin"}:raise HTTPException(403,"Only organization or branch admins may revoke healthcare roles")
    row=db.query(HealthcareRoleAssignment).filter_by(
        id=role_id,organization_id=m.organization_id,is_active=True).first()
    if not row or (row.branch_id is not None and not can_access_branch(m,row.branch_id)):
        raise HTTPException(404,"Active healthcare role not found")
    if m.role=="branch_admin" and (row.branch_id is None or row.role in {"healthcare_admin","privacy_officer","clinical_auditor"}):
        raise HTTPException(403,"Branch admins cannot revoke privileged or organization-wide roles")
    row.is_active=False
    db.add(AuditEvent(actor_user_id=u.id,organization_id=m.organization_id,action="healthcare.role.revoked",
        resource_type="healthcare_role_assignment",resource_id=str(row.id)))
    db.commit()
    return {"id":row.id,"status":"revoked"}


@router.post("/patients")
def create_patient(payload:dict,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    branch_id=payload.get("branch_id") or None
    _require(db,m,u,"patient.register",branch_id)
    mrn=str(payload.get("medical_record_number","")).strip()
    profile=payload.get("profile")
    if not mrn or len(mrn)>60 or not isinstance(profile,dict) or len(json.dumps(profile,ensure_ascii=False))>65536:
        raise HTTPException(422,"medical_record_number and profile object (max 64 KiB) are required")
    row=HealthcarePatient(organization_id=m.organization_id,branch_id=branch_id,
        medical_record_number=mrn,encrypted_profile=encrypt(profile),created_by=u.id)
    db.add(row)
    try:db.flush()
    except Exception:db.rollback();raise HTTPException(409,"Medical record number already exists")
    roles=_roles(db,m,u,branch_id)
    if "healthcare_admin" not in roles:
        db.add(HealthcarePatientAccess(organization_id=m.organization_id,patient_id=row.id,user_id=u.id,
            access_level="write" if "clinician" in roles else "read",granted_by=u.id,reason="Patient registration access"))
    _audit(db,m,u,row,"patient.created")
    db.commit()
    return {"id":row.id,"medical_record_number":row.medical_record_number,"status":row.status}


@router.get("/patients")
def list_patients(q:str="",reason:str="",limit:int=Query(100,ge=1,le=500),m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    _,list_roles=_require(db,m,u,"patient.read",allow_unscoped=True)
    if "clinical_auditor" in list_roles and not reason.strip():
        raise HTTPException(422,"Audit reason required for patient directory access")
    query=db.query(HealthcarePatient).filter_by(organization_id=m.organization_id)
    allowed=(m.branch_scope or "").strip()
    if allowed!="*":
        branches=[x.strip() for x in allowed.split(",") if x.strip()]
        query=query.filter(HealthcarePatient.branch_id.in_(branches)) if branches else query.filter(HealthcarePatient.id==-1)
    rows=query.order_by(HealthcarePatient.id.desc()).limit(limit).all()
    out=[]
    for p in rows:
        emergency,patient_roles=_require(db,m,u,"patient.read",p.branch_id,p.id,True)
        if "clinical_auditor" in patient_roles and not reason.strip():
            raise HTTPException(422,"Audit reason required for patient directory access")
        profile=decrypt(p.encrypted_profile)
        if q and q.casefold() not in (p.medical_record_number+" "+json.dumps(profile,ensure_ascii=False)).casefold():continue
        out.append({"id":p.id,"medical_record_number":p.medical_record_number,"status":p.status,
            "branch_id":p.branch_id,"profile":profile})
        _audit(db,m,u,p,"patient.listed",reason,emergency)
    if out:db.commit()
    return out


@router.get("/patients/{patient_id}")
def get_patient(patient_id:int,reason:str="",m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    p=_patient(db,patient_id,m)
    emergency,roles=_require(db,m,u,"patient.read",p.branch_id,p.id,True)
    if "clinical_auditor" in roles and not reason.strip():raise HTTPException(422,"Audit reason required")
    profile=decrypt(p.encrypted_profile)
    _audit(db,m,u,p,"patient.read",reason,emergency);db.commit()
    return {"id":p.id,"medical_record_number":p.medical_record_number,"status":p.status,"profile":profile}


@router.put("/patients/{patient_id}")
def update_patient(patient_id:int,payload:dict,reason:str,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    p=_patient(db,patient_id,m)
    emergency,_=_require(db,m,u,"patient.write",p.branch_id,p.id,True)
    profile=payload.get("profile")
    if not isinstance(profile,dict) or len(json.dumps(profile,ensure_ascii=False))>65536 or not reason.strip():
        raise HTTPException(422,"profile object and change reason are required")
    p.encrypted_profile=encrypt(profile)
    _audit(db,m,u,p,"patient.updated",reason,emergency);db.commit()
    return {"updated":True}


@router.post("/patients/{patient_id}/access",status_code=201)
def grant_access(patient_id:int,payload:dict,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    p=_patient(db,patient_id,m);_require(db,m,u,"access.manage",p.branch_id)
    uid=int(payload.get("user_id",0));level=payload.get("access_level","read")
    reason=str(payload.get("reason","")).strip()
    if uid<=0 or level not in {"read","write"} or not 5<=len(reason)<=500:raise HTTPException(422,"Valid user_id, access_level and a 5–500 character reason are required")
    member=db.query(Membership).filter_by(organization_id=m.organization_id,user_id=uid,is_active=True).first()
    if not member:raise HTTPException(404,"Active organization member not found")
    allowed={x.strip() for x in (member.branch_scope or "*").split(",") if x.strip()}
    if p.branch_id is None and "*" not in allowed:
        raise HTTPException(403,"Organization-wide patient access requires an organization-wide member")
    if p.branch_id and "*" not in allowed and p.branch_id not in allowed:
        raise HTTPException(403,"Target user is outside the patient branch")
    expires=None
    if payload.get("expires_at"):
        try:
            expires=datetime.fromisoformat(str(payload["expires_at"]).replace("Z","+00:00"))
            if expires.tzinfo is None or expires.utcoffset() is None or expires<=datetime.now(timezone.utc):raise ValueError()
        except Exception:raise HTTPException(422,"expires_at must be a future timezone-aware timestamp")
    row=HealthcarePatientAccess(organization_id=m.organization_id,patient_id=p.id,user_id=uid,
        access_level=level,granted_by=u.id,expires_at=expires,reason=reason)
    db.add(row);db.flush()
    _audit(db,m,u,p,"access.granted",reason);db.commit()
    return {"grant_id":row.id,"patient_id":p.id,"user_id":uid,"access_level":level,
        "expires_at":row.expires_at.isoformat() if row.expires_at else None}


@router.get("/patients/{patient_id}/access")
def list_access(patient_id:int,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    p=_patient(db,patient_id,m);_require(db,m,u,"access.manage",p.branch_id)
    rows=db.query(HealthcarePatientAccess).filter_by(
        organization_id=m.organization_id,patient_id=p.id).order_by(HealthcarePatientAccess.id.desc()).all()
    return [{"id":x.id,"user_id":x.user_id,"access_level":x.access_level,"reason":x.reason,
        "expires_at":x.expires_at.isoformat() if x.expires_at else None,
        "revoked_at":x.revoked_at.isoformat() if x.revoked_at else None} for x in rows]


@router.post("/patients/{patient_id}/access/{grant_id}/revoke")
def revoke_access(patient_id:int,grant_id:int,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    p=_patient(db,patient_id,m);_require(db,m,u,"access.manage",p.branch_id)
    row=db.query(HealthcarePatientAccess).filter_by(
        id=grant_id,organization_id=m.organization_id,patient_id=p.id,revoked_at=None).first()
    if not row:raise HTTPException(404,"Active patient access grant not found")
    row.revoked_at=datetime.now(timezone.utc)
    _audit(db,m,u,p,"access.revoked",f"user:{row.user_id}");db.commit()
    return {"revoked":True,"grant_id":row.id}


@router.post("/patients/{patient_id}/consents",status_code=201)
def record_consent(patient_id:int,payload:dict,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    p=_patient(db,patient_id,m);_require(db,m,u,"consent.manage",p.branch_id)
    consent_type=str(payload.get("consent_type",""))
    decision=payload.get("decision")
    if consent_type not in CONSENT_TYPES or decision not in {"granted","denied","withdrawn"}:
        raise HTTPException(422,"Valid consent_type and decision required")
    expires=None
    if payload.get("expires_at"):
        try:
            expires=datetime.fromisoformat(str(payload["expires_at"]).replace("Z","+00:00"))
            if expires.tzinfo is None or expires.utcoffset() is None or expires<=datetime.now(timezone.utc):raise ValueError()
        except Exception:raise HTTPException(422,"expires_at must be a future timezone-aware timestamp")
    row=HealthcareConsent(organization_id=m.organization_id,patient_id=p.id,
        consent_type=consent_type,decision=decision,recorded_by=u.id,
        notes=str(payload.get("notes",""))[:500],
        evidence_reference=str(payload.get("evidence_reference",""))[:180],expires_at=expires)
    db.add(row);_audit(db,m,u,p,"consent.recorded",f"{consent_type}:{decision}");db.commit()
    return {"consent_id":row.id,"consent_type":consent_type,"decision":decision}


@router.get("/patients/{patient_id}/consents")
def list_consents(patient_id:int,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    p=_patient(db,patient_id,m);_require(db,m,u,"consent.manage",p.branch_id)
    rows=db.query(HealthcareConsent).filter_by(
        organization_id=m.organization_id,patient_id=p.id).order_by(HealthcareConsent.id.desc()).all()
    _audit(db,m,u,p,"consent.history.read");db.commit()
    return [{"id":x.id,"consent_type":x.consent_type,"decision":x.decision,"notes":x.notes,
        "evidence_reference":x.evidence_reference,"recorded_at":x.recorded_at.isoformat(),
        "expires_at":x.expires_at.isoformat() if x.expires_at else None} for x in rows]


@router.post("/patients/{patient_id}/break-glass",status_code=201)
def open_break_glass(patient_id:int,payload:dict,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    p=_patient(db,patient_id,m);roles=_roles(db,m,u,p.branch_id)
    if p.branch_id is None:
        roles={x.role for x in db.query(HealthcareRoleAssignment).filter_by(
            organization_id=m.organization_id,user_id=u.id,is_active=True,branch_id=None).all()}
    if not roles.intersection({"healthcare_admin","clinician","nurse"}):
        raise HTTPException(403,"Only clinical staff may request emergency access")
    reason=str(payload.get("justification","")).strip()
    if not 15<=len(reason)<=1000:raise HTTPException(422,"A clinical emergency justification of 15–1000 characters is required")
    active=_active_breakglass(db,m.organization_id,u.id,p.id)
    if active:return {"id":active.id,"expires_at":active.expires_at.isoformat(),"already_active":True}
    now=datetime.now(timezone.utc)
    row=HealthcareBreakGlassSession(organization_id=m.organization_id,patient_id=p.id,user_id=u.id,
        justification=reason,started_at=now,expires_at=now+timedelta(minutes=15))
    db.add(row);_audit(db,m,u,p,"break_glass.opened",reason,True);db.commit()
    return {"id":row.id,"expires_at":row.expires_at.isoformat(),"warning":"Emergency access expires in 15 minutes and is audited."}


@router.post("/break-glass/{session_id}/close")
def close_break_glass(session_id:int,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    row=db.query(HealthcareBreakGlassSession).filter_by(
        id=session_id,organization_id=m.organization_id,user_id=u.id,ended_at=None).first()
    if not row:raise HTTPException(404,"Active emergency session not found")
    row.ended_at=datetime.now(timezone.utc)
    p=_patient(db,row.patient_id,m);_audit(db,m,u,p,"break_glass.closed",emergency=True);db.commit()
    return {"id":row.id,"ended_at":row.ended_at.isoformat()}


@router.post("/patients/{patient_id}/appointments",status_code=201)
def create_appointment(patient_id:int,payload:dict,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    p=_patient(db,patient_id,m);_require(db,m,u,"appointment.manage",p.branch_id,p.id)
    provider_id=int(payload.get("provider_user_id",0))
    try:
        starts=datetime.fromisoformat(str(payload["starts_at"]).replace("Z","+00:00"))
        ends=datetime.fromisoformat(str(payload["ends_at"]).replace("Z","+00:00"))
        if starts.tzinfo is None or starts.utcoffset() is None or ends.tzinfo is None or ends.utcoffset() is None:raise ValueError()
    except Exception:raise HTTPException(422,"Timezone-aware starts_at and ends_at are required")
    if provider_id<=0 or ends<=starts or starts<=datetime.now(timezone.utc):raise HTTPException(422,"Valid provider and future appointment window required")
    member=db.query(Membership).filter_by(organization_id=m.organization_id,user_id=provider_id,is_active=True).first()
    if not member:raise HTTPException(404,"Active provider membership not found")
    allowed={x.strip() for x in (member.branch_scope or "*").split(",") if x.strip()}
    if p.branch_id is None and "*" not in allowed:
        raise HTTPException(403,"Organization-wide appointments require an organization-wide provider")
    if p.branch_id and "*" not in allowed and p.branch_id not in allowed:
        raise HTTPException(403,"Provider is outside the patient branch")
    provider_user=db.query(User).filter_by(id=provider_id,is_active=True).first()
    if not provider_user:raise HTTPException(404,"Active provider user not found")
    provider_roles=_roles(db,member,provider_user,p.branch_id)
    if p.branch_id is None:
        provider_roles={x.role for x in db.query(HealthcareRoleAssignment).filter_by(
            organization_id=m.organization_id,user_id=provider_id,is_active=True,branch_id=None).all()}
    if not provider_roles.intersection({"healthcare_admin","clinician","nurse"}):
        raise HTTPException(422,"Appointment provider must have an active clinical role")
    conflict=db.query(HealthcareAppointment.id).filter(
        HealthcareAppointment.organization_id==m.organization_id,
        HealthcareAppointment.provider_user_id==provider_id,
        HealthcareAppointment.status=="scheduled",
        HealthcareAppointment.starts_at<ends,
        HealthcareAppointment.ends_at>starts).first()
    if conflict:raise HTTPException(409,"Provider already has an appointment in this time window")
    row=HealthcareAppointment(organization_id=m.organization_id,patient_id=p.id,branch_id=p.branch_id,
        provider_user_id=provider_id,starts_at=starts.astimezone(timezone.utc),
        ends_at=ends.astimezone(timezone.utc),created_by=u.id)
    db.add(row);_audit(db,m,u,p,"appointment.created");db.commit()
    return {"id":row.id,"patient_id":p.id,"provider_user_id":provider_id,
        "starts_at":row.starts_at.isoformat(),"ends_at":row.ends_at.isoformat(),"status":row.status}


@router.post("/patients/{patient_id}/encounters",status_code=201)
def create_encounter(patient_id:int,payload:dict,reason:str,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    p=_patient(db,patient_id,m);emergency,_=_require(db,m,u,"clinical.write",p.branch_id,p.id,True)
    note=payload.get("clinical_note")
    if not isinstance(note,dict) or len(json.dumps(note,ensure_ascii=False))>65536 or not reason.strip():
        raise HTTPException(422,"clinical_note object (max 64 KiB) and reason are required")
    if not emergency and not _treatment_allowed(db,m.organization_id,p.id):
        raise HTTPException(403,"Current treatment consent is required for new clinical notes")
    row=HealthcareEncounter(organization_id=m.organization_id,patient_id=p.id,branch_id=p.branch_id,
        encounter_type=str(payload.get("encounter_type","consultation"))[:32],
        encrypted_clinical_note=encrypt(note),clinician_user_id=u.id)
    db.add(row);_audit(db,m,u,p,"encounter.created",reason,emergency);db.commit()
    return {"encounter_id":row.id,"status":row.status}


@router.get("/patients/{patient_id}/encounters")
def list_encounters(patient_id:int,reason:str="",m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    p=_patient(db,patient_id,m);emergency,roles=_require(db,m,u,"clinical.read",p.branch_id,p.id,True)
    if "clinical_auditor" in roles and not reason.strip():raise HTTPException(422,"Audit reason required")
    rows=db.query(HealthcareEncounter).filter_by(
        organization_id=m.organization_id,patient_id=p.id).order_by(HealthcareEncounter.id.desc()).limit(200).all()
    result=[{"id":x.id,"type":x.encounter_type,"status":x.status,
        "clinical_note":decrypt(x.encrypted_clinical_note),"created_at":x.created_at.isoformat(),
        "closed_at":x.closed_at.isoformat() if x.closed_at else None} for x in rows]
    _audit(db,m,u,p,"encounters.read",reason,emergency);db.commit()
    return result


@router.post("/encounters/{encounter_id}/close")
def close_encounter(encounter_id:int,reason:str,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    row=db.query(HealthcareEncounter).filter_by(
        id=encounter_id,organization_id=m.organization_id).first()
    if not row:raise HTTPException(404,"Encounter not found")
    p=_patient(db,row.patient_id,m);emergency,roles=_require(db,m,u,"clinical.write",p.branch_id,p.id,True)
    if row.status!="open":raise HTTPException(409,"Only open encounters can be closed")
    if row.clinician_user_id!=u.id and "healthcare_admin" not in roles:
        raise HTTPException(403,"Only the encounter author or healthcare administrator may close it")
    if not reason.strip():raise HTTPException(422,"Clinical close reason is required")
    if not emergency and not _treatment_allowed(db,m.organization_id,p.id):
        raise HTTPException(403,"Current treatment consent is required to close an encounter")
    row.status="closed";row.closed_at=datetime.now(timezone.utc)
    _audit(db,m,u,p,"encounter.closed",reason,emergency);db.commit()
    return {"id":row.id,"status":row.status,"closed_at":row.closed_at.isoformat()}


@router.get("/audit")
def healthcare_audit(limit:int=Query(100,ge=1,le=500),patient_id:int|None=None,
    m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    _require(db,m,u,"audit.read",allow_unscoped=True)
    q=db.query(HealthcareAccessAudit).filter_by(organization_id=m.organization_id)
    if patient_id is not None:
        p=_patient(db,patient_id,m);q=q.filter(HealthcareAccessAudit.patient_id==p.id)
    assignments=db.query(HealthcareRoleAssignment).filter_by(
        organization_id=m.organization_id,user_id=u.id,is_active=True).all()
    org_audit=any(x.role in {"healthcare_admin","privacy_officer","clinical_auditor"} and x.branch_id is None for x in assignments)
    if not org_audit:
        branches=[x.branch_id for x in assignments if x.role in {"healthcare_admin","privacy_officer","clinical_auditor"} and x.branch_id]
        if not branches:raise HTTPException(403,"No healthcare audit role assigned")
        q=q.join(HealthcarePatient,HealthcarePatient.id==HealthcareAccessAudit.patient_id)
        q=q.filter(HealthcarePatient.branch_id.in_(branches))
    scope=(m.branch_scope or "").strip()
    if scope!="*":
        branches=[x.strip() for x in scope.split(",") if x.strip()]
        q=q.join(HealthcarePatient,HealthcarePatient.id==HealthcareAccessAudit.patient_id) if not org_audit and not branches else q
        if branches:
            if org_audit:q=q.join(HealthcarePatient,HealthcarePatient.id==HealthcareAccessAudit.patient_id)
            q=q.filter(HealthcarePatient.branch_id.in_(branches))
        else:q=q.filter(HealthcareAccessAudit.id==-1)
    rows=q.order_by(HealthcareAccessAudit.created_at.desc(),HealthcareAccessAudit.id.desc()).limit(limit).all()
    return [{"id":x.id,"patient_id":x.patient_id,"actor_user_id":x.actor_user_id,
        "action":x.action,"reason":x.reason,"emergency":x.emergency,"created_at":x.created_at.isoformat()} for x in rows]
