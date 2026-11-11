import re, secrets, ssl, socket, hashlib
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.models import CustomDomain, SystemNotice, NoticeDismissal, Organization, Membership, OrganizationInvitation, User, AuditEvent, Branch
from app.core.security import current_user, require_platform_admin
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, ROLE_PERMISSIONS

router = APIRouter(prefix="/api/v1")

def _audit(db, actor, org_id, action, kind, resource_id, detail=""):
    db.add(AuditEvent(actor_user_id=actor, organization_id=org_id, action=action,
                      resource_type=kind, resource_id=str(resource_id), detail=detail))
    db.commit()

def _hostname(value: str) -> str:
    host = value.strip().lower().rstrip(".")
    if len(host) > 253 or not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", host):
        raise HTTPException(422, "Enter a valid fully-qualified domain name")
    if host in {"localhost", "onecore.co.ke", "www.onecore.co.ke"} or host.endswith(".onecore.co.ke"):
        raise HTTPException(409, "This hostname is reserved by OneCore")
    return host

class DomainIn(BaseModel):
    hostname: str = Field(min_length=4, max_length=253)

class NoticeIn(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    message: str = Field(min_length=1, max_length=5000)
    severity: str = Field(default="info", pattern="^(info|success|warning|critical)$")
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    audience: dict = Field(default_factory=dict)
    organization_id: int | None = None

@router.post("/domains", status_code=201)
def request_domain(payload: DomainIn, membership=Depends(active_membership), user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    host = _hostname(payload.hostname)
    if db.query(CustomDomain).filter_by(hostname=host).first():
        raise HTTPException(409, "Hostname is already registered")
    token = secrets.token_urlsafe(24)
    row = CustomDomain(organization_id=membership.organization_id, hostname=host, verification_token=token)
    db.add(row); db.commit(); db.refresh(row)
    _audit(db,user.id,membership.organization_id,"domain.requested","custom_domain",row.id,host)
    return {"id":row.id,"hostname":host,"status":row.status,"tls_status":row.tls_status,
            "dns_record":{"type":"TXT","name":f"_onecore-verification.{host}","value":token}}

@router.get("/domains")
def list_domains(membership=Depends(active_membership), db:Session=Depends(get_db)):
    require_permission(membership,"read")
    rows=db.query(CustomDomain).filter_by(organization_id=membership.organization_id).order_by(CustomDomain.id.desc()).all()
    return [{"id":x.id,"hostname":x.hostname,"status":x.status,"tls_status":x.tls_status,"is_primary":x.is_primary,
             "verified_at":x.verified_at.isoformat() if x.verified_at else None} for x in rows]

@router.post("/domains/{domain_id}/verify")
def verify_domain(domain_id:int,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(CustomDomain).filter_by(id=domain_id,organization_id=membership.organization_id).first()
    if not row: raise HTTPException(404,"Domain not found")
    try:
        import dns.resolver
        answers=dns.resolver.resolve(f"_onecore-verification.{row.hostname}","TXT",lifetime=4)
        found=any(row.verification_token in "".join(part.decode() if isinstance(part,bytes) else str(part) for part in answer.strings) for answer in answers)
    except Exception:
        found=False
    if not found:
        raise HTTPException(409,"DNS TXT verification record not found. Allow DNS propagation and retry.")
    row.status="verified"; row.verified_at=datetime.now(timezone.utc)
    db.commit()
    _audit(db,user.id,membership.organization_id,"domain.verified","custom_domain",row.id,row.hostname)
    return {"id":row.id,"hostname":row.hostname,"status":row.status,"tls_status":row.tls_status,
            "next_step":"Configure the verified hostname in the hosting ingress and provision TLS before activation."}

@router.post("/admin/domains/{domain_id}/activate")
def activate_domain(domain_id:int,user:User=Depends(require_platform_admin),db:Session=Depends(get_db)):
    row=db.get(CustomDomain,domain_id)
    if not row or row.status!="verified":
        raise HTTPException(409,"Domain must pass DNS verification before activation")
    try:
        context=ssl.create_default_context()
        with socket.create_connection((row.hostname,443),timeout=5) as raw:
            with context.wrap_socket(raw,server_hostname=row.hostname) as secured:
                if not secured.getpeercert():
                    raise ssl.SSLError("No peer certificate")
    except Exception:
        raise HTTPException(409,"A valid HTTPS certificate for this hostname is not available")
    row.status="active";row.tls_status="active";db.commit()
    _audit(db,user.id,row.organization_id,"domain.activated","custom_domain",row.id,row.hostname)
    return {"id":row.id,"hostname":row.hostname,"status":row.status,"tls_status":row.tls_status}

@router.post("/domains/{domain_id}/primary")
def set_primary_domain(domain_id:int,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(CustomDomain).filter_by(id=domain_id,organization_id=membership.organization_id,status="active",tls_status="active").first()
    if not row: raise HTTPException(409,"Only active HTTPS domains can be primary")
    db.query(CustomDomain).filter_by(organization_id=membership.organization_id).update({"is_primary":False})
    row.is_primary=True; db.commit()
    _audit(db,user.id,membership.organization_id,"domain.primary_changed","custom_domain",row.id,row.hostname)
    return {"id":row.id,"hostname":row.hostname,"is_primary":True}

@router.delete("/domains/{domain_id}",status_code=204)
def remove_domain(domain_id:int,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(CustomDomain).filter_by(id=domain_id,organization_id=membership.organization_id).first()
    if not row: raise HTTPException(404,"Domain not found")
    host=row.hostname; db.delete(row); db.commit()
    _audit(db,user.id,membership.organization_id,"domain.removed","custom_domain",domain_id,host)

@router.post("/admin/notices",status_code=201)
def create_notice(payload:NoticeIn,user:User=Depends(require_platform_admin),db:Session=Depends(get_db)):
    starts=payload.starts_at or datetime.now(timezone.utc)
    expires=payload.expires_at
    if starts.tzinfo is None: starts=starts.replace(tzinfo=timezone.utc)
    if expires is not None and expires.tzinfo is None: expires=expires.replace(tzinfo=timezone.utc)
    if expires and expires<=starts:
        raise HTTPException(422,"Expiry must be after publication time")
    if payload.organization_id and not db.get(Organization,payload.organization_id):
        raise HTTPException(404,"Organization not found")
    row=SystemNotice(title=payload.title,message=payload.message,severity=payload.severity,
        audience=payload.audience,organization_id=payload.organization_id,status="draft",
        starts_at=starts,expires_at=expires,created_by=user.id)
    db.add(row);db.commit();db.refresh(row)
    _audit(db,user.id,payload.organization_id,"notice.created","system_notice",row.id)
    return {"id":row.id,"status":row.status,"starts_at":row.starts_at.isoformat()}

@router.put("/admin/notices/{notice_id}")
def edit_notice(notice_id:int,payload:NoticeIn,user:User=Depends(require_platform_admin),db:Session=Depends(get_db)):
    row=db.get(SystemNotice,notice_id)
    if not row: raise HTTPException(404,"Notice not found")
    if row.status!="draft": raise HTTPException(409,"Only draft notices can be edited")
    starts=payload.starts_at or row.starts_at
    expires=payload.expires_at
    if starts.tzinfo is None: starts=starts.replace(tzinfo=timezone.utc)
    if expires is not None and expires.tzinfo is None: expires=expires.replace(tzinfo=timezone.utc)
    if expires and expires<=starts: raise HTTPException(422,"Expiry must be after publication time")
    if payload.organization_id and not db.get(Organization,payload.organization_id):
        raise HTTPException(404,"Organization not found")
    row.title=payload.title;row.message=payload.message;row.severity=payload.severity
    row.audience=payload.audience;row.organization_id=payload.organization_id
    row.starts_at=starts;row.expires_at=expires;row.updated_at=datetime.now(timezone.utc)
    db.commit()
    _audit(db,user.id,row.organization_id,"notice.edited","system_notice",row.id)
    return {"id":row.id,"status":row.status}

@router.post("/admin/notices/{notice_id}/publish")
def publish_notice(notice_id:int,user:User=Depends(require_platform_admin),db:Session=Depends(get_db)):
    row=db.get(SystemNotice,notice_id)
    if not row or row.status!="draft": raise HTTPException(404,"Draft notice not found")
    if row.created_by==user.id:
        raise HTTPException(403,"A different platform administrator must approve and publish this notice")
    row.status="published";row.approved_by=user.id;db.commit()
    _audit(db,user.id,row.organization_id,"notice.published","system_notice",row.id)
    return {"id":row.id,"status":row.status,"approved_by":user.id}

@router.get("/notices")
def active_notices(user:User=Depends(current_user),x_organization_id:int|None=Header(default=None,alias="X-Organization-ID"),db:Session=Depends(get_db)):
    if x_organization_id is not None:
        membership=db.query(Membership).filter_by(user_id=user.id,organization_id=x_organization_id,is_active=True).first()
        if not membership:
            raise HTTPException(404,"Organization not found")
    now=datetime.now(timezone.utc)
    q=db.query(SystemNotice).filter(SystemNotice.status=="published",SystemNotice.starts_at<=now)
    q=q.filter((SystemNotice.expires_at.is_(None))|(SystemNotice.expires_at>now))
    rows=q.order_by(SystemNotice.created_at.desc()).all()
    dismissed={x.notice_id for x in db.query(NoticeDismissal).filter_by(user_id=user.id).all()}
    result=[]
    for x in rows:
        if x.id in dismissed: continue
        if x.organization_id is not None and x.organization_id != x_organization_id: continue
        aud=x.audience or {}
        if aud.get("user_ids") and user.id not in aud["user_ids"]: continue
        if aud.get("platform_roles") and user.platform_role not in aud["platform_roles"]: continue
        result.append({"id":x.id,"title":x.title,"message":x.message,"severity":x.severity,
                       "starts_at":x.starts_at.isoformat(),"expires_at":x.expires_at.isoformat() if x.expires_at else None})
    return result

@router.post("/notices/{notice_id}/dismiss",status_code=204)
def dismiss_notice(notice_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=db.get(SystemNotice,notice_id)
    if not row or row.status!="published": raise HTTPException(404,"Notice not found")
    if row.organization_id is not None:
        if not db.query(Membership).filter_by(user_id=user.id,organization_id=row.organization_id,is_active=True).first():
            raise HTTPException(404,"Notice not found")
    if not db.query(NoticeDismissal).filter_by(notice_id=notice_id,user_id=user.id).first():
        db.add(NoticeDismissal(notice_id=notice_id,user_id=user.id));db.commit()
    return

@router.post("/admin/notices/{notice_id}/withdraw")
def withdraw_notice(notice_id:int,user:User=Depends(require_platform_admin),db:Session=Depends(get_db)):
    row=db.get(SystemNotice,notice_id)
    if not row: raise HTTPException(404,"Notice not found")
    row.status="withdrawn";db.commit()
    _audit(db,user.id,row.organization_id,"notice.withdrawn","system_notice",row.id)
    return {"id":row.id,"status":row.status}


class InvitationIn(BaseModel):
    email: EmailStr
    role: str = Field(pattern="^(org_admin|branch_admin|manager|accountant|staff|viewer|hr_admin|hr_manager|payroll_manager|payroll_approver|payroll_payment|payroll_accounting|sacco_officer|sacco_manager|sacco_kyc_approver|sacco_treasurer|sacco_auditor)$")
    branch_scope: str = Field(default="*", max_length=500)

class AcceptInvitationIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)

def _validated_branch_scope(db, organization_id: int, scope: str, status_code: int = 422) -> str:
    """Return a canonical branch scope after checking active branches belong to the tenant."""
    normalized = scope.strip()
    if normalized == "*":
        return "*"
    branch_ids = [part.strip() for part in normalized.split(",")]
    if (not branch_ids or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", part) for part in branch_ids)
            or len(branch_ids) != len(set(branch_ids))):
        raise HTTPException(status_code, "Branch scope must contain unique valid branch IDs")
    rows = db.query(Branch.id).filter(
        Branch.organization_id == organization_id,
        Branch.is_active.is_(True),
        Branch.id.in_(branch_ids),
    ).all()
    found = {row[0] for row in rows}
    if found != set(branch_ids):
        raise HTTPException(status_code, "Branch scope must reference active branches in this organization")
    return ",".join(branch_ids)

@router.post("/invitations", status_code=201)
def create_invitation(payload:InvitationIn,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    email=str(payload.email).lower()
    scope=_validated_branch_scope(db,membership.organization_id,payload.branch_scope)
    pending=db.query(OrganizationInvitation).filter_by(organization_id=membership.organization_id,email=email,accepted_at=None,revoked_at=None).first()
    if pending:
        raise HTTPException(409,"An active invitation already exists for this email")
    token=secrets.token_urlsafe(32)
    row=OrganizationInvitation(organization_id=membership.organization_id,email=email,role=payload.role,
        branch_scope=scope,token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=datetime.now(timezone.utc)+timedelta(days=7),created_by=user.id)
    db.add(row);db.commit();db.refresh(row)
    _audit(db,user.id,membership.organization_id,"invitation.created","organization_invitation",row.id,email)
    return {"id":row.id,"email":email,"role":row.role,"expires_at":row.expires_at.isoformat(),
            "invitation_token":token,"delivery":"Token returned once; deliver it using the configured secure email service."}

@router.get("/invitations")
def list_invitations(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    rows=db.query(OrganizationInvitation).filter_by(organization_id=membership.organization_id).order_by(OrganizationInvitation.id.desc()).all()
    return [{"id":x.id,"email":x.email,"role":x.role,"branch_scope":x.branch_scope,
             "expires_at":x.expires_at.isoformat(),"accepted_at":x.accepted_at.isoformat() if x.accepted_at else None,
             "revoked_at":x.revoked_at.isoformat() if x.revoked_at else None} for x in rows]

@router.post("/invitations/accept")
def accept_invitation(payload:AcceptInvitationIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    digest=hashlib.sha256(payload.token.encode()).hexdigest()
    row=db.query(OrganizationInvitation).filter_by(token_hash=digest).first()
    if not row or row.accepted_at or row.revoked_at:
        raise HTTPException(404,"Invitation is invalid or no longer active")
    expiry=row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expiry<=datetime.now(timezone.utc):
        raise HTTPException(410,"Invitation has expired")
    if user.email.lower()!=row.email.lower():
        raise HTTPException(403,"Sign in with the email address that received this invitation")
    org=db.get(Organization,row.organization_id)
    if not org or not org.is_active:
        raise HTTPException(404,"Organization not found")
    validated_scope=_validated_branch_scope(db,row.organization_id,row.branch_scope,status_code=409)
    existing=db.query(Membership).filter_by(user_id=user.id,organization_id=row.organization_id).first()
    if existing and existing.is_active:
        raise HTTPException(409,"You already have active access to this organization")
    if existing:
        existing.role=row.role;existing.branch_scope=validated_scope;existing.is_active=True
    else:
        db.add(Membership(user_id=user.id,organization_id=row.organization_id,role=row.role,branch_scope=validated_scope))
    row.accepted_at=datetime.now(timezone.utc);db.commit()
    _audit(db,user.id,row.organization_id,"invitation.accepted","organization_invitation",row.id,row.email)
    return {"organization_id":row.organization_id,"organization_name":org.name,"role":row.role}

@router.delete("/invitations/{invitation_id}",status_code=204)
def revoke_invitation(invitation_id:int,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(OrganizationInvitation).filter_by(id=invitation_id,organization_id=membership.organization_id).first()
    if not row: raise HTTPException(404,"Invitation not found")
    if row.accepted_at: raise HTTPException(409,"Accepted invitations cannot be revoked")
    row.revoked_at=datetime.now(timezone.utc);db.commit()
    _audit(db,user.id,membership.organization_id,"invitation.revoked","organization_invitation",row.id,row.email)

@router.get("/branding/footer")
def mandatory_footer():
    return {"text":"Powered by OneCore Technologies Ltd","mandatory":True}
