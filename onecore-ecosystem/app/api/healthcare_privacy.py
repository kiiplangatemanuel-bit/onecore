"""Privacy-first healthcare records with encrypted PHI and patient-scoped authorization."""
import json
from datetime import datetime, timezone
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.core.models import (User, Branch, HealthcarePatient, HealthcareEncounter, HealthcarePatientAccess,
    HealthcareConsent, HealthcareAccessAudit)
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import can_access_branch

router=APIRouter(prefix="/api/v1/healthcare",tags=["Healthcare privacy"])
CLINICAL={"org_admin","healthcare_admin","physician","nurse"}
READ_ROLES=CLINICAL|{"clinical_auditor"}
WRITE_ROLES=CLINICAL
def cipher():
    key=settings.healthcare_phi_encryption_key
    if not key: raise HTTPException(503,"Healthcare PHI encryption key is not configured")
    try: return Fernet(key.encode())
    except Exception: raise HTTPException(503,"Healthcare PHI encryption key must be a valid Fernet key")
def encrypt(value): return cipher().encrypt(json.dumps(value,separators=(",",":"),ensure_ascii=False).encode()).decode()
def decrypt(value):
    try: return json.loads(cipher().decrypt(value.encode()).decode())
    except (InvalidToken,ValueError,TypeError): raise HTTPException(503,"Patient data cannot be decrypted; verify key configuration")
def role(m,allowed):
    if (m.role or "").lower() not in allowed: raise HTTPException(403,"Healthcare role is not authorized")
def patient(db,pid,m):
    p=db.query(HealthcarePatient).filter_by(id=pid,organization_id=m.organization_id).first()
    if not p: raise HTTPException(404,"Patient not found")
    return p
def access(db,p,m,u,level="read"):
    role(m,READ_ROLES)
    if (m.role or "").lower() in {"healthcare_admin","org_admin"}: return
    now=datetime.now(timezone.utc)
    q=db.query(HealthcarePatientAccess).filter_by(organization_id=m.organization_id,patient_id=p.id,user_id=u.id,revoked_at=None)
    grants=q.all()
    if not any(g.access_level in ({"write","admin"} if level=="write" else {"read","write","admin"}) and (g.expires_at is None or g.expires_at>now) for g in grants):
        raise HTTPException(403,"No active patient-specific care-team grant")
def audit(db,p,m,u,action,reason=""):
    db.add(HealthcareAccessAudit(organization_id=m.organization_id,patient_id=p.id,actor_user_id=u.id,action=action,reason=reason[:500]))
    db.commit()

@router.post("/patients")
def create_patient(payload:dict,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    role(m,{"org_admin","healthcare_admin"}); mrn=str(payload.get("medical_record_number","")).strip()
    profile=payload.get("profile")
    if not mrn or len(mrn)>60 or not isinstance(profile,dict): raise HTTPException(422,"medical_record_number and profile object required")
    branch_id=payload.get("branch_id")\n    if branch_id:\n        b=db.query(Branch).filter_by(id=branch_id,organization_id=m.organization_id,is_active=True).first()\n        if not b or not can_access_branch(m,branch_id): raise HTTPException(404,"Branch not found")\n    p=HealthcarePatient(organization_id=m.organization_id,branch_id=branch_id,medical_record_number=mrn,
        encrypted_profile=encrypt(profile),created_by=u.id)
    db.add(p); db.flush(); audit(db,p,m,u,"patient_created"); return {"id":p.id,"medical_record_number":p.medical_record_number}

@router.get("/patients/{patient_id}")
def get_patient(patient_id:int,reason:str="",m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    p=patient(db,patient_id,m); access(db,p,m,u)
    if m.role=="clinical_auditor" and not reason.strip(): raise HTTPException(422,"Audit reason required")
    audit(db,p,m,u,"patient_read",reason)
    return {"id":p.id,"medical_record_number":p.medical_record_number,"status":p.status,"profile":decrypt(p.encrypted_profile)}

@router.put("/patients/{patient_id}")
def update_patient(patient_id:int,payload:dict,reason:str,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    role(m,WRITE_ROLES); p=patient(db,patient_id,m); access(db,p,m,u,"write")
    if not isinstance(payload.get("profile"),dict) or not reason.strip(): raise HTTPException(422,"profile and reason required")
    p.encrypted_profile=encrypt(payload["profile"]); audit(db,p,m,u,"patient_updated",reason); return {"updated":True}

@router.post("/patients/{patient_id}/access")
def grant_access(patient_id:int,payload:dict,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    role(m,{"org_admin","healthcare_admin"}); p=patient(db,patient_id,m); uid=int(payload.get("user_id",0)); level=payload.get("access_level","read")
    if uid<=0 or level not in {"read","write"}: raise HTTPException(422,"Valid user_id and access_level required")
    from app.core.models import Membership
    member=db.query(Membership).filter_by(user_id=uid,organization_id=m.organization_id,is_active=True).first()
    if not member: raise HTTPException(422,"User is not an active member of this organization")
    expires=None\n    if payload.get("expires_at"):\n        try:\n            expires=datetime.fromisoformat(str(payload["expires_at"]).replace("Z","+00:00"))\n            if expires.tzinfo is None or expires<=datetime.now(timezone.utc): raise ValueError()\n        except Exception: raise HTTPException(422,"expires_at must be a future timezone-aware timestamp")\n    g=HealthcarePatientAccess(organization_id=m.organization_id,patient_id=p.id,user_id=uid,access_level=level,granted_by=u.id,expires_at=expires)
    db.add(g); audit(db,p,m,u,"access_granted",str(uid)); return {"grant_id":g.id}

@router.post("/patients/{patient_id}/encounters")
def create_encounter(patient_id:int,payload:dict,reason:str,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    role(m,WRITE_ROLES); p=patient(db,patient_id,m); access(db,p,m,u,"write")
    note=payload.get("clinical_note")
    if not isinstance(note,dict) or not reason.strip(): raise HTTPException(422,"clinical_note object and reason required")
    e=HealthcareEncounter(organization_id=m.organization_id,patient_id=p.id,branch_id=p.branch_id,
        encounter_type=str(payload.get("encounter_type","consultation"))[:32],encrypted_clinical_note=encrypt(note),clinician_user_id=u.id)
    db.add(e); db.flush(); audit(db,p,m,u,"encounter_created",reason); return {"encounter_id":e.id,"status":e.status}

@router.get("/patients/{patient_id}/encounters")
def list_encounters(patient_id:int,reason:str="",m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    p=patient(db,patient_id,m); access(db,p,m,u)
    if m.role=="clinical_auditor" and not reason.strip(): raise HTTPException(422,"Audit reason required")
    rows=db.query(HealthcareEncounter).filter_by(organization_id=m.organization_id,patient_id=p.id).order_by(HealthcareEncounter.id.desc()).limit(100).all()
    audit(db,p,m,u,"encounters_read",reason)
    return [{"id":e.id,"type":e.encounter_type,"status":e.status,"clinical_note":decrypt(e.encrypted_clinical_note),"created_at":e.created_at.isoformat()} for e in rows]

@router.post("/patients/{patient_id}/consents")
def record_consent(patient_id:int,payload:dict,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    role(m,{"healthcare_admin","physician"}); p=patient(db,patient_id,m)
    decision=payload.get("decision")
    if decision not in {"granted","denied","withdrawn"} or not payload.get("consent_type"): raise HTTPException(422,"Valid consent_type and decision required")
    x=HealthcareConsent(organization_id=m.organization_id,patient_id=p.id,consent_type=str(payload["consent_type"])[:40],
        decision=decision,recorded_by=u.id,notes=str(payload.get("notes",""))[:500])
    db.add(x); audit(db,p,m,u,"consent_recorded",decision); return {"consent_id":x.id,"decision":decision}

@router.get("/patients/{patient_id}/audit")
def patient_audit(patient_id:int,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    role(m,{"healthcare_admin","clinical_auditor"}); p=patient(db,patient_id,m)
    rows=db.query(HealthcareAccessAudit).filter_by(organization_id=m.organization_id,patient_id=p.id).order_by(HealthcareAccessAudit.id.desc()).limit(500).all()
    return [{"actor_user_id":x.actor_user_id,"action":x.action,"reason":x.reason,"created_at":x.created_at.isoformat()} for x in rows]

@router.post("/patients/{patient_id}/access/{grant_id}/revoke")
def revoke_access(patient_id:int,grant_id:int,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    role(m,{"org_admin","healthcare_admin"}); p=patient(db,patient_id,m)
    g=db.query(HealthcarePatientAccess).filter_by(id=grant_id,organization_id=m.organization_id,patient_id=p.id,revoked_at=None).first()
    if not g: raise HTTPException(404,"Active access grant not found")
    g.revoked_at=datetime.now(timezone.utc); audit(db,p,m,u,"access_revoked",str(g.user_id))
    return {"revoked":True}
