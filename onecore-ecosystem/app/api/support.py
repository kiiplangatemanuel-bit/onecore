import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import and_, or_, text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import (
    AuditEvent, Membership, Organization, SupportMessage, SupportTicket, User,
)
from app.core.schemas import SupportMessageIn, SupportStatusIn, SupportTicketCreateIn
from app.core.security import current_user, require_platform_admin
from app.core.public_rate_limit import enforce_public_write_limit

router = APIRouter(prefix="/api/v1/support", tags=["support"])


def _hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ticket_number() -> str:
    return "OCS-" + uuid.uuid4().hex[:12].upper()


def _message_out(message: SupportMessage) -> dict:
    return {
        "id": message.id, "author_name": message.author_name,
        "body": message.body, "is_staff": message.is_staff,
        "created_at": message.created_at.isoformat(),
    }


def _ticket_out(ticket: SupportTicket, db: Session, include_messages: bool = False) -> dict:
    result = {
        "ticket_number": ticket.ticket_number, "subject": ticket.subject,
        "category": ticket.category, "status": ticket.status, "priority": ticket.priority,
        "contact_name": ticket.contact_name, "contact_email": ticket.contact_email,
        "organization_id": ticket.organization_id,
        "created_at": ticket.created_at.isoformat(), "updated_at": ticket.updated_at.isoformat(),
    }
    if include_messages:
        messages = db.query(SupportMessage).filter_by(ticket_id=ticket.id).order_by(
            SupportMessage.created_at.asc(), SupportMessage.id.asc()
        ).all()
        result["messages"] = [_message_out(item) for item in messages]
    return result


def _set_guest_context(db: Session, token: str) -> str:
    token_hash = _hash_token(token)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT set_config('app.support_guest_token_hash', :token_hash, true)"),
                   {"token_hash": token_hash})
    return token_hash


def _guest_ticket(db: Session, ticket_number: str, token: str) -> SupportTicket:
    if not token or len(token) < 32:
        raise HTTPException(401, "A valid support access token is required")
    # Bind guest access only after hashing the supplied token; RLS scopes the rows.
    token_hash = _set_guest_context(db, token)
    ticket = db.query(SupportTicket).filter_by(ticket_number=ticket_number).first()
    if not ticket or not ticket.guest_token_hash or not secrets.compare_digest(
        ticket.guest_token_hash, token_hash
    ):
        raise HTTPException(404, "Support ticket not found")
    return ticket


def _user_ticket(db: Session, ticket_number: str, user: User) -> SupportTicket:
    ticket = db.query(SupportTicket).filter_by(ticket_number=ticket_number).first()
    if not ticket:
        raise HTTPException(404, "Support ticket not found")
    membership = None
    if ticket.organization_id is not None:
        membership = db.query(Membership).filter_by(
            user_id=user.id, organization_id=ticket.organization_id, is_active=True
        ).first()
        # Organization tickets are inaccessible immediately after membership revocation,
        # including to the original creator.
        if not membership:
            raise HTTPException(404, "Support ticket not found")
    if ticket.created_by_user_id == user.id:
        return ticket
    if membership and membership.role == "org_admin":
        return ticket
    raise HTTPException(404, "Support ticket not found")


def _audit(db: Session, user_id: int | None, organization_id: int | None,
           action: str, ticket: SupportTicket, detail: str = ""):
    db.add(AuditEvent(
        actor_user_id=user_id, organization_id=organization_id, action=action,
        resource_type="support_ticket", resource_id=ticket.ticket_number, detail=detail,
    ))


def _create_ticket(payload: SupportTicketCreateIn, db: Session,
                   user: User | None = None, guest_token_hash: str | None = None) -> SupportTicket:
    organization = None
    if payload.organization_id is not None:
        if user is None:
            raise HTTPException(401, "Sign in before attaching a support ticket to an organization")
        membership = db.query(Membership).filter_by(
            user_id=user.id, organization_id=payload.organization_id, is_active=True
        ).first()
        organization = db.query(Organization).filter_by(
            id=payload.organization_id, is_active=True
        ).first()
        if not membership or not organization:
            raise HTTPException(403, "You do not have access to this organization")
    ticket = SupportTicket(
        ticket_number=_ticket_number(), subject=payload.subject.strip(),
        category=payload.category, contact_name=payload.contact_name.strip(),
        contact_email=str(payload.contact_email).lower(), contact_phone=payload.contact_phone.strip(),
        organization_id=organization.id if organization else None,
        created_by_user_id=user.id if user else None,
        guest_token_hash=guest_token_hash,
    )
    db.add(ticket)
    db.flush()
    db.add(SupportMessage(
        ticket_id=ticket.id, author_user_id=user.id if user else None,
        author_name=ticket.contact_name, body=payload.message.strip(), is_staff=False,
    ))
    _audit(db, user.id if user else None, ticket.organization_id, "support.ticket.created", ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


@router.post("/public/tickets", status_code=201)
def create_public_ticket(payload: SupportTicketCreateIn, request: Request, db: Session = Depends(get_db)):
    enforce_public_write_limit(request, "support-ticket-create")
    access_token = secrets.token_urlsafe(36)
    ticket = _create_ticket(payload, db, guest_token_hash=_hash_token(access_token))
    _set_guest_context(db, access_token)
    return {**_ticket_out(ticket, db, include_messages=True), "access_token": access_token}


@router.get("/public/tickets/{ticket_number}")
def read_public_ticket(
    ticket_number: str,
    request: Request,
    x_support_access_token: str = Header(default="", alias="X-Support-Access-Token"),
    db: Session = Depends(get_db),
):
    ticket = _guest_ticket(db, ticket_number, x_support_access_token)
    return _ticket_out(ticket, db, include_messages=True)


@router.post("/public/tickets/{ticket_number}/messages", status_code=201)
def reply_public_ticket(
    ticket_number: str, payload: SupportMessageIn, request: Request,
    x_support_access_token: str = Header(default="", alias="X-Support-Access-Token"),
    db: Session = Depends(get_db),
):
    enforce_public_write_limit(request, "support-ticket-reply")
    ticket = _guest_ticket(db, ticket_number, x_support_access_token)
    if ticket.status in {"resolved", "closed"}:
        raise HTTPException(409, "This ticket is closed. Open a new ticket for further assistance.")
    db.add(SupportMessage(ticket_id=ticket.id, author_name=ticket.contact_name,
                          body=payload.body.strip(), is_staff=False))
    ticket.status = "open" if ticket.status == "waiting_on_customer" else ticket.status
    ticket.updated_at = datetime.now(timezone.utc)
    _audit(db, None, ticket.organization_id, "support.ticket.replied", ticket)
    db.commit()
    _set_guest_context(db, x_support_access_token)
    return _ticket_out(ticket, db, include_messages=True)


@router.post("/tickets", status_code=201)
def create_authenticated_ticket(
    payload: SupportTicketCreateIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    if str(payload.contact_email).lower() != user.email.lower():
        raise HTTPException(422, "Use the email address associated with your signed-in account")
    ticket = _create_ticket(payload, db, user=user)
    return _ticket_out(ticket, db, include_messages=True)


@router.get("/tickets")
def list_my_tickets(
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    active_org_ids = [row.organization_id for row in db.query(Membership).filter_by(
        user_id=user.id, is_active=True
    ).all()]
    admin_org_ids = [row.organization_id for row in db.query(Membership).filter_by(
        user_id=user.id, role="org_admin", is_active=True
    ).all()]
    visibility = [and_(
        SupportTicket.created_by_user_id == user.id,
        or_(SupportTicket.organization_id.is_(None),
            SupportTicket.organization_id.in_(active_org_ids) if active_org_ids else SupportTicket.organization_id.is_(None)),
    )]
    if admin_org_ids:
        visibility.append(SupportTicket.organization_id.in_(admin_org_ids))
    rows = db.query(SupportTicket).filter(or_(*visibility)).order_by(
        SupportTicket.updated_at.desc()
    ).limit(limit).all()
    return [_ticket_out(row, db) for row in rows]


@router.get("/tickets/{ticket_number}")
def read_my_ticket(
    ticket_number: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    ticket = _user_ticket(db, ticket_number, user)
    return _ticket_out(ticket, db, include_messages=True)


@router.post("/tickets/{ticket_number}/messages", status_code=201)
def reply_my_ticket(
    ticket_number: str, payload: SupportMessageIn,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    ticket = _user_ticket(db, ticket_number, user)
    if ticket.status in {"resolved", "closed"}:
        raise HTTPException(409, "This ticket is closed. Open a new ticket for further assistance.")
    db.add(SupportMessage(ticket_id=ticket.id, author_user_id=user.id,
                          author_name=user.full_name or user.email, body=payload.body.strip()))
    ticket.status = "open" if ticket.status == "waiting_on_customer" else ticket.status
    ticket.updated_at = datetime.now(timezone.utc)
    _audit(db, user.id, ticket.organization_id, "support.ticket.replied", ticket)
    db.commit()
    return _ticket_out(ticket, db, include_messages=True)


@router.get("/admin/tickets")
def list_support_queue(
    status: str | None = Query(default=None, pattern=r"^(open|in_progress|waiting_on_customer|resolved|closed)$"),
    limit: int = Query(default=100, ge=1, le=250),
    user: User = Depends(require_platform_admin), db: Session = Depends(get_db),
):
    query = db.query(SupportTicket)
    if status:
        query = query.filter_by(status=status)
    rows = query.order_by(SupportTicket.updated_at.asc()).limit(limit).all()
    return [_ticket_out(row, db) for row in rows]


@router.get("/admin/tickets/{ticket_number}")
def read_support_ticket_admin(
    ticket_number: str,
    user: User = Depends(require_platform_admin), db: Session = Depends(get_db),
):
    ticket = db.query(SupportTicket).filter_by(ticket_number=ticket_number).first()
    if not ticket:
        raise HTTPException(404, "Support ticket not found")
    return _ticket_out(ticket, db, include_messages=True)


@router.post("/admin/tickets/{ticket_number}/messages", status_code=201)
def reply_as_support(
    ticket_number: str, payload: SupportMessageIn,
    user: User = Depends(require_platform_admin), db: Session = Depends(get_db),
):
    ticket = db.query(SupportTicket).filter_by(ticket_number=ticket_number).first()
    if not ticket:
        raise HTTPException(404, "Support ticket not found")
    db.add(SupportMessage(ticket_id=ticket.id, author_user_id=user.id,
                          author_name=user.full_name or user.email, body=payload.body.strip(), is_staff=True))
    if ticket.status == "open":
        ticket.status = "in_progress"
    ticket.updated_at = datetime.now(timezone.utc)
    _audit(db, user.id, ticket.organization_id, "support.staff.replied", ticket)
    db.commit()
    return _ticket_out(ticket, db, include_messages=True)


@router.patch("/admin/tickets/{ticket_number}")
def update_support_ticket(
    ticket_number: str, payload: SupportStatusIn,
    user: User = Depends(require_platform_admin), db: Session = Depends(get_db),
):
    ticket = db.query(SupportTicket).filter_by(ticket_number=ticket_number).first()
    if not ticket:
        raise HTTPException(404, "Support ticket not found")
    ticket.status = payload.status
    if payload.priority is not None:
        ticket.priority = payload.priority
    if payload.assigned_to_user_id is not None:
        assignee = db.get(User, payload.assigned_to_user_id)
        if not assignee or not assignee.is_active or assignee.platform_role not in {"root_superadmin", "platform_admin"}:
            raise HTTPException(422, "Assignee must be an active platform administrator")
        ticket.assigned_to_user_id = assignee.id
    ticket.updated_at = datetime.now(timezone.utc)
    _audit(db, user.id, ticket.organization_id, "support.ticket.updated", ticket,
           f"status={ticket.status};priority={ticket.priority}")
    db.commit()
    return _ticket_out(ticket, db, include_messages=True)
