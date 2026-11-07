"""Campaign dispatch, delivery callbacks, one-click unsubscribe and reporting."""
import hashlib, secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.core.models import User, CRMCampaign, CRMCampaignRecipient, CRMContactConsent, CRMCampaignDelivery
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, can_access_branch
from app.services.crm_delivery import build_unsubscribe_url, send_campaign_message

router=APIRouter(prefix="/api/v1/crm",tags=["CRM communications"])

def campaign_or_404(db,cid,org,membership):
    row=db.query(CRMCampaign).filter_by(id=cid,organization_id=org).first()
    if not row or not can_access_branch(membership,row.branch_id): raise HTTPException(404,"Campaign not found")
    return row

def latest_consent(db,r,c):
    return db.query(CRMContactConsent).filter_by(organization_id=r.organization_id,
        contact_id=r.contact_id,channel=c.channel,purpose=c.purpose).order_by(CRMContactConsent.id.desc()).first()

@router.post("/campaigns/{campaign_id}/dispatch")
def dispatch_campaign(campaign_id:int,batch_size:int=Query(100,ge=1,le=500),
    membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    c=campaign_or_404(db,campaign_id,membership.organization_id,membership)
    if c.status not in {"ready","sending","partial","failed"}:
        raise HTTPException(409,"Prepare campaign before dispatch")
    if c.purpose=="marketing":
        build_unsubscribe_url("configuration-check",settings.crm_public_base_url)
    now=datetime.now(timezone.utc)
    lease_expired=now-timedelta(minutes=10)
    eligible=or_(
        CRMCampaignRecipient.status.in_(["prepared","failed"]),
        and_(
            CRMCampaignRecipient.status=="sending",
            or_(CRMCampaignRecipient.claimed_at.is_(None),
                CRMCampaignRecipient.claimed_at<lease_expired),
        ),
    )
    rows=db.query(CRMCampaignRecipient).filter_by(
        organization_id=membership.organization_id,campaign_id=c.id
    ).filter(eligible).order_by(CRMCampaignRecipient.id).limit(batch_size).with_for_update().all()
    processed=accepted=failed=suppressed=0
    for recipient in rows:
        recipient.status="sending"
        recipient.claimed_at=now
    c.status="sending"
    db.commit()
    for r in rows:
        processed+=1
        consent=latest_consent(db,r,c)
        checked_at=datetime.now(timezone.utc)
        if not consent or consent.decision!="granted" or (
            consent.expires_at and consent.expires_at<=checked_at
        ):
            r.status="suppressed"
            r.claimed_at=None
            db.add(CRMCampaignDelivery(organization_id=r.organization_id,recipient_id=r.id,
                attempt_number=0,status="suppressed",error_message="Consent revoked or expired"))
            db.commit()
            suppressed+=1
            continue
        attempts=db.query(func.count(CRMCampaignDelivery.id)).filter_by(
            organization_id=r.organization_id,recipient_id=r.id
        ).scalar() or 0
        if attempts>=5:
            r.status="exhausted"
            r.claimed_at=None
            db.commit()
            failed+=1
            continue
        token=secrets.token_urlsafe(32)
        unsubscribe_url=build_unsubscribe_url(token,settings.crm_public_base_url) if c.purpose=="marketing" else None
        digest=hashlib.sha256(token.encode()).hexdigest()
        d=CRMCampaignDelivery(organization_id=r.organization_id,recipient_id=r.id,
            attempt_number=attempts+1,status="sending",unsubscribe_token_hash=digest)
        db.add(d)
        db.commit()
        try:
            result=send_campaign_message(c.channel,r.address_snapshot,c.name,c.message,
                f"onecore-crm-{c.id}-{r.id}",unsubscribe_url)
            d.status="accepted"
            d.provider_message_id=result["provider_message_id"]
            d.accepted_at=datetime.now(timezone.utc)
            r.status="sent"
            r.claimed_at=None
            db.commit()
            accepted+=1
        except Exception as exc:
            d.status="failed"
            d.error_message=str(exc)[:1000]
            r.status="failed"
            r.claimed_at=None
            db.commit()
            failed+=1
    remaining=db.query(CRMCampaignRecipient).filter_by(
        organization_id=membership.organization_id,campaign_id=c.id
    ).filter(or_(
        CRMCampaignRecipient.status.in_(["prepared","failed"]),
        CRMCampaignRecipient.status=="sending",
    )).count()
    statuses={x[0] for x in db.query(CRMCampaignRecipient.status).filter_by(
        organization_id=membership.organization_id,campaign_id=c.id).all()}
    c.status=("sent" if remaining==0 and statuses <= {"sent","delivered","suppressed"}
              else "partial")
    db.commit()
    return {"campaign_id":c.id,"status":c.status,"processed":processed,
        "accepted":accepted,"failed":failed,"suppressed":suppressed,"remaining":remaining}


@router.post("/delivery-events")
def delivery_event(payload:dict,x_crm_delivery_secret:str|None=Header(None),db:Session=Depends(get_db)):
    if not settings.crm_delivery_callback_secret or not secrets.compare_digest(
        x_crm_delivery_secret or "",settings.crm_delivery_callback_secret): raise HTTPException(401,"Invalid callback credentials")
    pid=str(payload.get("provider_message_id") or "").strip(); state=str(payload.get("status") or "").lower()
    if not pid or state not in {"delivered","failed"}: raise HTTPException(422,"Valid provider_message_id and status required")
    d=db.query(CRMCampaignDelivery).filter_by(provider_message_id=pid).order_by(CRMCampaignDelivery.id.desc()).first()
    if not d: raise HTTPException(404,"Delivery not found")
    r=db.query(CRMCampaignRecipient).filter_by(id=d.recipient_id,organization_id=d.organization_id).first()
    if not r: raise HTTPException(404,"Recipient not found")
    if d.status=="delivered": return {"accepted":True,"duplicate":True}
    d.status=state; d.error_message=str(payload.get("reason") or "")[:1000] if state=="failed" else None
    d.delivered_at=datetime.now(timezone.utc) if state=="delivered" else None; r.status=state; db.commit()
    return {"accepted":True,"status":state}

@router.get("/campaigns/{campaign_id}/report")
def campaign_report(campaign_id:int,membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read"); c=campaign_or_404(db,campaign_id,membership.organization_id,membership)
    rows=db.query(CRMCampaignRecipient.status,func.count(CRMCampaignRecipient.id)).filter_by(
        organization_id=membership.organization_id,campaign_id=c.id).group_by(CRMCampaignRecipient.status).all()
    counts={s:n for s,n in rows}
    attempts=db.query(func.count(CRMCampaignDelivery.id)).join(CRMCampaignRecipient,
        CRMCampaignRecipient.id==CRMCampaignDelivery.recipient_id).filter(
        CRMCampaignRecipient.organization_id==membership.organization_id,
        CRMCampaignRecipient.campaign_id==c.id).scalar() or 0
    return {"campaign_id":c.id,"status":c.status,"recipient_count":sum(counts.values()),
        "statuses":counts,"attempt_count":attempts,"delivered":counts.get("delivered",0),
        "accepted":counts.get("sent",0)+counts.get("delivered",0),"failed":counts.get("failed",0),
        "suppressed":counts.get("suppressed",0),"exhausted":counts.get("exhausted",0)}

@router.post("/unsubscribe/{token}")
def unsubscribe(token:str,db:Session=Depends(get_db)):
    d=db.query(CRMCampaignDelivery).filter_by(unsubscribe_token_hash=hashlib.sha256(token.encode()).hexdigest()).first()
    if not d: raise HTTPException(404,"Unsubscribe link is invalid")
    r=db.query(CRMCampaignRecipient).filter_by(id=d.recipient_id,organization_id=d.organization_id).first()
    c=db.query(CRMCampaign).filter_by(id=r.campaign_id,organization_id=r.organization_id).first() if r else None
    if not r or not c: raise HTTPException(404,"Subscription not found")
    latest=latest_consent(db,r,c)
    if latest and latest.decision=="granted":
        db.add(CRMContactConsent(organization_id=r.organization_id,contact_id=r.contact_id,
            channel=c.channel,purpose="marketing",decision="revoked",source="one-click-unsubscribe",
            recorded_by=c.created_by,recorded_at=datetime.now(timezone.utc)))
    r.status="suppressed"; db.commit()
    return {"unsubscribed":True,"channel":c.channel}
