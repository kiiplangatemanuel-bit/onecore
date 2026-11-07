from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.models import User, Membership, Organization
from app.core.security import current_user

def active_membership(
    x_organization_id: int = Header(..., alias="X-Organization-ID"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    membership = db.query(Membership).filter_by(
        user_id=user.id, organization_id=x_organization_id, is_active=True
    ).first()
    org = db.get(Organization, x_organization_id)
    if not membership or not org or not org.is_active:
        raise HTTPException(403, "No active access to this organization")
    return membership
