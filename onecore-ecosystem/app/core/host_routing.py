"""Tenant-safe host resolution. Only verified, TLS-ready domains are routable."""
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.core.models import CustomDomain, Organization

def organization_for_host(db: Session, hostname: str):
    host=(hostname or "").split(":")[0].strip().lower().rstrip(".")
    if host in {"localhost","127.0.0.1","onecore.co.ke","www.onecore.co.ke"}:
        return None
    domain=db.query(CustomDomain).filter_by(hostname=host,status="active",tls_status="active").first()
    if not domain:
        raise HTTPException(404,"Unknown or inactive host")
    org=db.get(Organization,domain.organization_id)
    if not org or not org.is_active:
        raise HTTPException(404,"Unknown or inactive host")
    return org
