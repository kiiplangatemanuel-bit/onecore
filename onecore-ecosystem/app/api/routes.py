import json, re, uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.models import User, Organization, Membership, Branch, Record, AuditEvent
from app.core.schemas import OrganizationIn, RecordIn, BranchIn
from app.core.security import current_user, verify_password, create_access_token, require_platform_admin
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, branch_scope_ids, can_access_branch
from app.integrations.registry import public_provider_status

router = APIRouter(prefix="/api/v1")
CATALOG_PATH = Path(__file__).resolve().parents[1] / "modules" / "catalog.json"

def audit(db, user_id, org_id, action, resource_type="", resource_id="", detail=""):
    db.add(AuditEvent(actor_user_id=user_id, organization_id=org_id, action=action,
                      resource_type=resource_type, resource_id=str(resource_id), detail=detail))
    db.commit()

def validate_module_key(module_key: str):
    if not re.fullmatch(r"[a-z0-9-]{2,100}", module_key):
        raise HTTPException(400, "Invalid module key")

@router.post("/auth/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form.username.lower()).first()
    if not user or not verify_password(form.password, user.password_hash) or not user.is_active:
        raise HTTPException(401, "Incorrect email or password")
    return {"access_token": create_access_token(user.id), "token_type": "bearer"}

@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "platform_role": user.platform_role}

@router.post("/organizations", status_code=201)
def create_organization(payload: OrganizationIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if db.query(Organization).filter_by(slug=payload.slug).first():
        raise HTTPException(409, "Organization slug already exists")
    org = Organization(**payload.model_dump())
    db.add(org); db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role="org_admin", branch_scope="*"))
    db.commit(); db.refresh(org)
    audit(db, user.id, org.id, "organization.created", "organization", org.id)
    return {"id": org.id, "name": org.name, "slug": org.slug, "role": "org_admin"}

@router.get("/organizations")
def list_organizations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Membership, Organization).join(Organization, Organization.id == Membership.organization_id).filter(
        Membership.user_id == user.id, Membership.is_active == True, Organization.is_active == True).all()
    return [{"id": o.id, "name": o.name, "slug": o.slug, "role": m.role} for m, o in rows]

@router.get("/modules")
def module_catalog(user: User = Depends(current_user)):
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

@router.get("/integrations")
def integrations(user: User = Depends(current_user)):
    return public_provider_status()


@router.get("/branches")
def list_branches(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    query=db.query(Branch).filter_by(organization_id=membership.organization_id,is_active=True)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        if not allowed: return []
        query=query.filter(Branch.id.in_(allowed))
    return [{"id":b.id,"code":b.code,"name":b.name,"address":b.address} for b in query.order_by(Branch.name).all()]

@router.post("/branches",status_code=201)
def create_branch(payload:BranchIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    if db.query(Branch).filter_by(organization_id=membership.organization_id,code=payload.code).first():
        raise HTTPException(409,"Branch code already exists in this organization")
    row=Branch(id=str(uuid.uuid4()),organization_id=membership.organization_id,code=payload.code,name=payload.name,address=payload.address)
    db.add(row);db.commit();db.refresh(row)
    audit(db,user.id,membership.organization_id,"branch.created","branch",row.id)
    return {"id":row.id,"code":row.code,"name":row.name,"address":row.address}

@router.put("/branches/{branch_id}")
def update_branch(branch_id:str,payload:BranchIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(Branch).filter_by(id=branch_id,organization_id=membership.organization_id,is_active=True).first()
    if not row: raise HTTPException(404,"Branch not found")
    duplicate=db.query(Branch).filter(Branch.organization_id==membership.organization_id,Branch.code==payload.code,Branch.id!=branch_id).first()
    if duplicate: raise HTTPException(409,"Branch code already exists in this organization")
    row.code=payload.code;row.name=payload.name;row.address=payload.address;db.commit()
    audit(db,user.id,membership.organization_id,"branch.updated","branch",row.id)
    return {"id":row.id,"code":row.code,"name":row.name,"address":row.address}

@router.delete("/branches/{branch_id}",status_code=204)
def deactivate_branch(branch_id:str,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(Branch).filter_by(id=branch_id,organization_id=membership.organization_id,is_active=True).first()
    if not row: raise HTTPException(404,"Branch not found")
    row.is_active=False;db.commit()
    audit(db,user.id,membership.organization_id,"branch.deactivated","branch",row.id)

@router.get("/records/{module_key}")
def list_records(module_key: str, membership=Depends(active_membership), db: Session = Depends(get_db),
                 limit: int = Query(default=100, ge=1, le=500)):
    validate_module_key(module_key)
    require_permission(membership, "read")
    query = db.query(Record).filter_by(organization_id=membership.organization_id, module_key=module_key)
    allowed_branches = branch_scope_ids(membership)
    if allowed_branches is not None:
        if not allowed_branches:
            return []
        query = query.filter(Record.branch_id.in_(allowed_branches))
    rows = query.order_by(Record.id.desc()).limit(limit).all()
    return [{"id": r.id, "module_key": r.module_key, "record_type": r.record_type, "data": r.data,
             "branch_id": r.branch_id, "created_at": r.created_at.isoformat(),
             "updated_at": r.updated_at.isoformat()} for r in rows]

@router.post("/records/{module_key}", status_code=201)
def create_record(module_key: str, payload: RecordIn, membership=Depends(active_membership),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    validate_module_key(module_key)
    require_permission(membership, "create")
    if not can_access_branch(membership, payload.branch_id):
        raise HTTPException(403, "Your membership is not authorized for this branch")
    if payload.branch_id is not None and not db.query(Branch).filter_by(id=payload.branch_id, organization_id=membership.organization_id, is_active=True).first():
        raise HTTPException(404, "Branch not found")
    row = Record(organization_id=membership.organization_id, module_key=module_key, record_type=payload.record_type,
                 data=payload.data, branch_id=payload.branch_id, created_by=user.id)
    db.add(row); db.commit(); db.refresh(row)
    audit(db, user.id, membership.organization_id, "record.created", module_key, row.id)
    return {"id": row.id, "module_key": row.module_key, "record_type": row.record_type,
            "data": row.data, "branch_id": row.branch_id}

@router.put("/records/{module_key}/{record_id}")
def update_record(module_key: str, record_id: int, payload: RecordIn,
                  membership=Depends(active_membership), user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    validate_module_key(module_key)
    require_permission(membership, "update")
    row = db.query(Record).filter_by(id=record_id, organization_id=membership.organization_id,
                                     module_key=module_key).first()
    if not row:
        raise HTTPException(404, "Record not found")
    if not can_access_branch(membership, row.branch_id) or not can_access_branch(membership, payload.branch_id):
        raise HTTPException(404, "Record not found")
    if payload.branch_id is not None and not db.query(Branch).filter_by(id=payload.branch_id, organization_id=membership.organization_id, is_active=True).first():
        raise HTTPException(404, "Branch not found")
    row.record_type = payload.record_type
    row.data = payload.data
    row.branch_id = payload.branch_id
    db.commit(); db.refresh(row)
    audit(db, user.id, membership.organization_id, "record.updated", module_key, row.id)
    return {"id": row.id, "module_key": row.module_key, "record_type": row.record_type,
            "data": row.data, "branch_id": row.branch_id}

@router.delete("/records/{module_key}/{record_id}", status_code=204)
def delete_record(module_key: str, record_id: int, membership=Depends(active_membership),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    validate_module_key(module_key)
    require_permission(membership, "delete")
    row = db.query(Record).filter_by(id=record_id, organization_id=membership.organization_id,
                                     module_key=module_key).first()
    if not row or not can_access_branch(membership, row.branch_id):
        raise HTTPException(404, "Record not found")
    resource_id = row.id
    db.delete(row); db.commit()
    audit(db, user.id, membership.organization_id, "record.deleted", module_key, resource_id)

@router.get("/operations/audit")
def audit_log(membership=Depends(active_membership), db: Session = Depends(get_db),
              limit: int = Query(default=100, ge=1, le=500)):
    require_permission(membership, "read")
    rows = db.query(AuditEvent).filter_by(organization_id=membership.organization_id).order_by(
        AuditEvent.id.desc()).limit(limit).all()
    return [{"id": x.id, "actor_user_id": x.actor_user_id, "action": x.action, "resource_type": x.resource_type,
             "resource_id": x.resource_id, "detail": x.detail, "created_at": x.created_at.isoformat()} for x in rows]

@router.get("/admin/overview")
def admin_overview(user: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return {"organizations": db.query(Organization).count(), "users": db.query(User).count(),
            "providers": public_provider_status()}
