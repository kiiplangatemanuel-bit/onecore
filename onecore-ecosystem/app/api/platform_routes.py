import re, secrets, ssl, socket
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.models import CustomDomain, SystemNotice, NoticeDismissal, Organization, User, AuditEvent
from app.core.security import current_user, require_platform_admin
from app.core.tenancy import active_membership
from app.core.authorization import require_permission

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
    if payload.expires_at and payload.starts_at and payload.expires_at <= payload.starts_at:
        raise HTTPException(422,"Expiry must be after publication time")
    if payload.organization_id and not db.get(Organization,payload.organization_id):
        raise HTTPException(404,"Organization not found")
    row=SystemNotice(title=payload.title,message=payload.message,severity=payload.severity,
        audience=payload.audience,organization_id=payload.organization_id,status="published",
        starts_at=payload.starts_at or datetime.now(timezone.utc),expires_at=payload.expires_at,
        created_by=user.id,approved_by=user.id)
    db.add(row);db.commit();db.refresh(row)
    _audit(db,user.id,payload.organization_id,"notice.published","system_notice",row.id)
    return {"id":row.id,"status":row.status,"starts_at":row.starts_at.isoformat()}

@router.get("/notices")
def active_notices(user:User=Depends(current_user),x_organization_id:int|None=Header(default=None,alias="X-Organization-ID"),db:Session=Depends(get_db)):
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
        from app.core.models import Membership
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

@router.get("/branding/footer")
def mandatory_footer():
    return {"text":"Powered by OneCore Technologies Ltd","mandatory":True}
