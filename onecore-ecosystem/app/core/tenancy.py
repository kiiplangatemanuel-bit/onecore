from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.models import User, Membership, Organization
from app.core.security import current_user, set_verified_organization_context
from app.core.host_routing import organization_for_host


def active_membership(
    request: Request,
    x_organization_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    host_org = organization_for_host(db, request.url.hostname or "")
    if host_org is not None:
        if x_organization_id is not None and x_organization_id != host_org.id:
            raise HTTPException(404, "Organization not found for this host")
        organization_id = host_org.id
    else:
        organization_id = x_organization_id
    if organization_id is None:
        raise HTTPException(400, "X-Organization-ID is required on the shared OneCore host")
    membership = db.query(Membership).filter_by(
        user_id=user.id, organization_id=organization_id, is_active=True
    ).first()
    org = db.get(Organization, organization_id)
    if not membership or not org or not org.is_active:
        raise HTTPException(403, "No active access to this organization")

    # The tenant GUC is deliberately set only after the server has verified an
    # active membership. PostgreSQL RLS policies use this transaction-local
    # context for tenant-scoped reads/writes made by downstream route handlers.
    set_verified_organization_context(db, organization_id)
    return membership
