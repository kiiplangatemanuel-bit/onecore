import hashlib, secrets, smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.core.models import User, Organization, Membership, AuditEvent
from app.core.portal_models import EmailVerification, SupportTicket, SupportMessage
from app.core.security import current_user, hash_password, create_access_token
from app.core.tenancy import active_membership
from app.core.authorization import require_permission

router=APIRouter(prefix="/api/v1")
def _hash(value:str)->str:return hashlib.sha256(value.encode("utf-8")).hexdigest()
def _audit(db,actor,org,action,kind,resource,detail=""):
    db.add(AuditEvent(actor_user_id=actor,organization_id=org,action=action,resource_type=kind,resource_id=str(resource),detail=detail))
def _send_verification(email,token):
    if not (settings.integration_email_enabled and settings.email_host and settings.email_from):
        raise HTTPException(503,"Email verification is unavailable: configure the OneCore email provider before enabling public registration.")
    base=(settings.public_site_url or "").strip().rstrip("/")
    if not base: raise HTTPException(503,"PUBLIC_SITE_URL must be configured before public registration.")
    from urllib.parse import urlsplit
    parsed=urlsplit(base)
    if parsed.scheme not in ({"https"} if settings.app_env.lower() in {"production","prod"} else {"https","http"}) or not parsed.netloc or parsed.username or parsed.password:
        raise HTTPException(503,"PUBLIC_SITE_URL must be a valid public URL.")
    message=EmailMessage();message["From"]=settings.email_from;message["To"]=email;message["Subject"]="Verify your OneCore email address"
    message.set_content(f"Welcome to OneCore. Verify your email using this one-time link:\n\n{base}/verify-email?token={token}\n\nThis link expires in 30 minutes. If you did not request this account, ignore this message.")
    try:
        with smtplib.SMTP(settings.email_host,settings.email_port,timeout=20) as server:
            server.starttls()
            if settings.email_username:server.login(settings.email_username,settings.email_password)
            server.send_message(message)
    except Exception as exc:
        raise HTTPException(503,"Unable to send the verification email. Check the configured email provider and try again.") from exc

class PublicRegistrationIn(BaseModel):
    organization_name:str=Field(min_length=2,max_length=200)
    organization_slug:str=Field(min_length=3,max_length=120,pattern=r"^[a-z0-9][a-z0-9-]{1,118}[a-z0-9]$")
    industry:str=Field(default="general",min_length=2,max_length=100)
    country:str=Field(default="KE",min_length=2,max_length=2,pattern=r"^[A-Z]{2}$")
    registration_number:str=Field(default="",max_length=100)
    contact_person:str=Field(min_length=2,max_length=180)
    phone:str=Field(min_length=7,max_length=32)
    email:EmailStr
    password:str=Field(min_length=14,max_length=128)

class VerifyEmailIn(BaseModel):
    token:str=Field(min_length=32,max_length=200)

class PublicTicketIn(BaseModel):
    name:str=Field(min_length=2,max_length=180)
    email:EmailStr
    subject:str=Field(min_length=4,max_length=180)
    message:str=Field(min_length=10,max_length=10000)
    category:str=Field(default="general",pattern=r"^(general|technical|billing|security|sales)$")

class TicketIn(BaseModel):
    subject:str=Field(min_length=4,max_length=180)
    message:str=Field(min_length=10,max_length=10000)
    category:str=Field(default="general",pattern=r"^(general|technical|billing|security|sales)$")
    priority:str=Field(default="normal",pattern=r"^(low|normal|high|urgent)$")

class TicketMessageIn(BaseModel):
    message:str=Field(min_length=1,max_length=10000)

@router.post("/auth/register",status_code=202)
def register_organization(payload:PublicRegistrationIn,db:Session=Depends(get_db)):
    email=str(payload.email).lower().strip()
    if db.query(User).filter(User.email==email).first():raise HTTPException(409,"An account with this email already exists.")
    if db.query(Organization).filter(Organization.slug==payload.organization_slug).first():raise HTTPException(409,"That organization URL is already in use.")
    raw=secrets.token_urlsafe(36)
    user=User(email=email,full_name=payload.contact_person.strip(),password_hash=hash_password(payload.password),is_active=False,platform_role="customer")
    org=Organization(name=payload.organization_name.strip(),slug=payload.organization_slug,industry=payload.industry,country=payload.country,registration_number=payload.registration_number.strip(),contact_phone=payload.phone.strip())
    try:
        db.add(user);db.add(org);db.flush()
        db.add(Membership(user_id=user.id,organization_id=org.id,role="org_admin",branch_scope="*",is_active=True))
        db.add(EmailVerification(user_id=user.id,token_hash=_hash(raw),expires_at=datetime.now(timezone.utc)+timedelta(minutes=30)))
        _send_verification(email,raw)
        _audit(db,user.id,org.id,"organization.registration.pending","organization",org.id)
        db.commit()
    except HTTPException:
        db.rollback();raise
    except Exception:
        db.rollback();raise
    return {"status":"verification_required","message":"Check your email for a verification link. Your organization administrator account will be activated after verification."}

@router.post("/auth/verify-email")
def verify_registration_email(payload:VerifyEmailIn,db:Session=Depends(get_db)):
    now=datetime.now(timezone.utc)
    row=db.query(EmailVerification).filter_by(token_hash=_hash(payload.token),used_at=None).with_for_update().first()
    if not row or row.expires_at.replace(tzinfo=timezone.utc)<now:raise HTTPException(400,"Verification link is invalid, expired or already used.")
    user=db.get(User,row.user_id)
    if not user:raise HTTPException(400,"Verification account no longer exists.")
    user.is_active=True;row.used_at=now
    db.add(AuditEvent(actor_user_id=user.id,organization_id=None,action="user.email.verified",resource_type="user",resource_id=str(user.id)))
    db.commit()
    return {"status":"verified","access_token":create_access_token(user.id),"token_type":"bearer","user":{"id":user.id,"email":user.email,"full_name":user.full_name}}

@router.post("/public/support/tickets",status_code=201)
def create_public_support_ticket(payload:PublicTicketIn,db:Session=Depends(get_db)):
    access=secrets.token_urlsafe(32);reference="OC-"+secrets.token_hex(6).upper()
    row=SupportTicket(reference=reference,requester_name=payload.name.strip(),requester_email=str(payload.email).lower(),subject=payload.subject.strip(),category=payload.category,priority="normal",status="open",public_access_hash=_hash(access))
    db.add(row);db.flush();db.add(SupportMessage(ticket_id=row.id,author_type="requester",body=payload.message.strip(),is_internal=False));db.commit()
    return {"reference":reference,"access_token":access,"status":"open","message":"Keep this access token private. It is required to view or reply to this public ticket."}

@router.get("/public/support/tickets/{reference}")
def get_public_support_ticket(reference:str,access_token:str=Query(min_length=32,max_length=200),db:Session=Depends(get_db)):
    row=db.query(SupportTicket).filter_by(reference=reference,public_access_hash=_hash(access_token),organization_id=None).first()
    if not row:raise HTTPException(404,"Ticket not found.")
    return {"reference":row.reference,"subject":row.subject,"category":row.category,"status":row.status,"created_at":row.created_at.isoformat(),"messages":[{"author":m.author_type,"message":m.body,"created_at":m.created_at.isoformat()} for m in db.query(SupportMessage).filter_by(ticket_id=row.id,is_internal=False).order_by(SupportMessage.id).all()]}

@router.post("/public/support/tickets/{reference}/messages",status_code=201)
def reply_public_support_ticket(reference:str,payload:TicketMessageIn,access_token:str=Query(min_length=32,max_length=200),db:Session=Depends(get_db)):
    row=db.query(SupportTicket).filter_by(reference=reference,public_access_hash=_hash(access_token),organization_id=None).with_for_update().first()
    if not row:raise HTTPException(404,"Ticket not found.")
    if row.status in {"resolved","closed"}:raise HTTPException(409,"This ticket is closed. Open a new ticket for further assistance.")
    db.add(SupportMessage(ticket_id=row.id,author_type="requester",body=payload.message.strip(),is_internal=False));row.status="open";db.commit()
    return {"status":row.status,"message":"Reply added."}

@router.post("/support/tickets",status_code=201)
def create_authenticated_ticket(payload:TicketIn,m=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"read")
    reference="OC-"+secrets.token_hex(6).upper()
    row=SupportTicket(reference=reference,organization_id=m.organization_id,requester_user_id=user.id,requester_name=user.full_name,requester_email=user.email,subject=payload.subject.strip(),category=payload.category,priority=payload.priority,status="open")
    db.add(row);db.flush();db.add(SupportMessage(ticket_id=row.id,author_type="requester",author_user_id=user.id,body=payload.message.strip(),is_internal=False));_audit(db,user.id,m.organization_id,"support.ticket.created","support_ticket",row.id);db.commit()
    return {"id":row.id,"reference":row.reference,"status":row.status}

@router.get("/support/tickets")
def list_authenticated_tickets(m=Depends(active_membership),db:Session=Depends(get_db),limit:int=Query(100,ge=1,le=200)):
    require_permission(m,"read")
    rows=db.query(SupportTicket).filter(SupportTicket.organization_id==m.organization_id).order_by(SupportTicket.updated_at.desc()).limit(limit).all()
    return [{"id":x.id,"reference":x.reference,"subject":x.subject,"category":x.category,"priority":x.priority,"status":x.status,"created_at":x.created_at.isoformat(),"updated_at":x.updated_at.isoformat()} for x in rows]

@router.get("/support/tickets/{ticket_id}")
def get_authenticated_ticket(ticket_id:int,m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"read")
    row=db.query(SupportTicket).filter_by(id=ticket_id,organization_id=m.organization_id).first()
    if not row:raise HTTPException(404,"Ticket not found.")
    return {"id":row.id,"reference":row.reference,"subject":row.subject,"category":row.category,"priority":row.priority,"status":row.status,"messages":[{"author":x.author_type,"message":x.body,"created_at":x.created_at.isoformat()} for x in db.query(SupportMessage).filter_by(ticket_id=row.id,is_internal=False).order_by(SupportMessage.id).all()]}

@router.post("/support/tickets/{ticket_id}/messages",status_code=201)
def reply_authenticated_ticket(ticket_id:int,payload:TicketMessageIn,m=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"read")
    row=db.query(SupportTicket).filter_by(id=ticket_id,organization_id=m.organization_id).with_for_update().first()
    if not row:raise HTTPException(404,"Ticket not found.")
    if row.status in {"resolved","closed"}:raise HTTPException(409,"This ticket is closed.")
    db.add(SupportMessage(ticket_id=row.id,author_type="requester",author_user_id=user.id,body=payload.message.strip(),is_internal=False));row.status="open";db.commit()
    return {"status":"open","message":"Reply added."}

@router.get("/support/agent/tickets")
def support_agent_queue(status:str|None=None,user:User=Depends(current_user),db:Session=Depends(get_db),limit:int=Query(100,ge=1,le=200)):
    if user.platform_role not in {"support_agent","platform_admin","root_superadmin"}:raise HTTPException(403,"Support agent access required.")
    q=db.query(SupportTicket)
    if status:q=q.filter(SupportTicket.status==status)
    rows=q.order_by(SupportTicket.updated_at.desc()).limit(limit).all()
    return [{"id":x.id,"reference":x.reference,"organization_id":x.organization_id,"requester_email":x.requester_email,"subject":x.subject,"category":x.category,"priority":x.priority,"status":x.status} for x in rows]

@router.post("/support/agent/tickets/{ticket_id}/messages",status_code=201)
def support_agent_reply(ticket_id:int,payload:TicketMessageIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    if user.platform_role not in {"support_agent","platform_admin","root_superadmin"}:raise HTTPException(403,"Support agent access required.")
    row=db.get(SupportTicket,ticket_id)
    if not row:raise HTTPException(404,"Ticket not found.")
    db.add(SupportMessage(ticket_id=row.id,author_type="agent",author_user_id=user.id,body=payload.message.strip(),is_internal=False));row.status="in_progress";db.commit()
    return {"status":row.status}

@router.patch("/support/agent/tickets/{ticket_id}")
def update_support_ticket(ticket_id:int,status:str=Query(pattern=r"^(open|in_progress|waiting_customer|resolved|closed)$"),priority:str|None=Query(None,pattern=r"^(low|normal|high|urgent)$"),user:User=Depends(current_user),db:Session=Depends(get_db)):
    if user.platform_role not in {"support_agent","platform_admin","root_superadmin"}:raise HTTPException(403,"Support agent access required.")
    row=db.get(SupportTicket,ticket_id)
    if not row:raise HTTPException(404,"Ticket not found.")
    row.status=status
    if priority:row.priority=priority
    db.commit()
    return {"id":row.id,"reference":row.reference,"status":row.status,"priority":row.priority}
