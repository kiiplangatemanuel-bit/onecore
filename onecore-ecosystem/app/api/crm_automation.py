"""CRM templates, saved audience segments and scheduled dispatch controls."""
import re
import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.core.models import (User, Membership, CRMCampaign, CRMCampaignTemplate,
    CRMContactSegment, CRMContact, CRMContactConsent)
from app.core.schemas import (CRMCampaignTemplateIn, CRMContactSegmentIn,
    CRMTemplateApplyIn, CRMSegmentApplyIn, CRMCampaignScheduleIn)
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, can_access_branch, branch_scope_ids
from app.services.crm_audience import validate_segment_definition, apply_segment
from app.api.crm_campaigns import dispatch_campaign

router = APIRouter(prefix="/api/v1/crm", tags=["CRM campaign automation"])
VARIABLES = {"first_name", "full_name", "company", "email", "phone"}
TOKEN = re.compile(r"{{\s*([a-z_]+)\s*}}")


def _campaign(db, campaign_id, membership):
    row = db.query(CRMCampaign).filter_by(id=campaign_id,
        organization_id=membership.organization_id).first()
    if not row or not can_access_branch(membership, row.branch_id):
        raise HTTPException(404, "Campaign not found")
    return row


def _render(text, contact):
    values = {"full_name": contact.full_name or "", "first_name": (contact.full_name or "").split(" ")[0],
              "company": contact.company or "", "email": contact.email or "", "phone": contact.phone or ""}
    def replace(match):
        key = match.group(1)
        if key not in VARIABLES:
            raise HTTPException(422, f"Unsupported template variable: {key}")
        return values[key]
    return TOKEN.sub(replace, text or "")


@router.post("/templates", status_code=201)
def create_template(payload: CRMCampaignTemplateIn, membership=Depends(active_membership),
                    user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    row = CRMCampaignTemplate(organization_id=membership.organization_id,
        name=payload.name.strip(), channel=payload.channel, purpose=payload.purpose,
        subject=payload.subject.strip(), body=payload.body.strip(),
        created_by=user.id, updated_by=user.id)
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "name": row.name, "channel": row.channel,
            "purpose": row.purpose, "is_active": row.is_active}


@router.get("/templates")
def list_templates(membership=Depends(active_membership), db: Session=Depends(get_db),
                   limit: int=Query(100, ge=1, le=500)):
    require_permission(membership, "read")
    rows = db.query(CRMCampaignTemplate).filter_by(
        organization_id=membership.organization_id, is_active=True
    ).order_by(CRMCampaignTemplate.name).limit(limit).all()
    return [{"id": r.id, "name": r.name, "channel": r.channel, "purpose": r.purpose,
             "subject": r.subject, "body": r.body, "is_active": r.is_active} for r in rows]


@router.put("/templates/{template_id}")
def update_template(template_id: int, payload: CRMCampaignTemplateIn,
                    membership=Depends(active_membership), user: User=Depends(current_user),
                    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    row = db.query(CRMCampaignTemplate).filter_by(
        id=template_id, organization_id=membership.organization_id, is_active=True
    ).first()
    if not row: raise HTTPException(404, "Template not found")
    row.name=payload.name.strip(); row.channel=payload.channel; row.purpose=payload.purpose
    row.subject=payload.subject.strip(); row.body=payload.body.strip(); row.updated_by=user.id
    row.updated_at=datetime.now(timezone.utc)
    db.commit()
    return {"id": row.id, "updated": True}


@router.post("/segments", status_code=201)
def create_segment(payload: CRMContactSegmentIn, membership=Depends(active_membership),
                   user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    if payload.branch_id and not can_access_branch(membership, payload.branch_id):
        raise HTTPException(403, "Branch is outside your scope")
    try: definition=validate_segment_definition(payload.definition)
    except ValueError as exc: raise HTTPException(422, str(exc))
    row=CRMContactSegment(organization_id=membership.organization_id,
        branch_id=payload.branch_id, name=payload.name.strip(), definition=definition,
        created_by=user.id)
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "name": row.name, "definition": row.definition}


@router.get("/segments")
def list_segments(membership=Depends(active_membership), db: Session=Depends(get_db),
                  limit: int=Query(100, ge=1, le=500)):
    require_permission(membership, "read")
    q=db.query(CRMContactSegment).filter_by(organization_id=membership.organization_id,is_active=True)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        if not allowed: return []
        q=q.filter((CRMContactSegment.branch_id.is_(None)) | CRMContactSegment.branch_id.in_(allowed))
    return [{"id":x.id,"name":x.name,"branch_id":x.branch_id,"definition":x.definition}
            for x in q.order_by(CRMContactSegment.name).limit(limit).all()]


@router.post("/segments/{segment_id}/preview")
def preview_segment(segment_id: int, membership=Depends(active_membership),
                    db: Session=Depends(get_db)):
    require_permission(membership, "read")
    segment=db.query(CRMContactSegment).filter_by(
        id=segment_id,organization_id=membership.organization_id,is_active=True).first()
    if not segment or not can_access_branch(membership,segment.branch_id):
        raise HTTPException(404,"Segment not found")
    q=db.query(CRMContact).filter_by(organization_id=membership.organization_id)
    if segment.branch_id: q=q.filter(CRMContact.branch_id==segment.branch_id)
    else:
        allowed=branch_scope_ids(membership)
        if allowed is not None:
            if not allowed: return {"segment_id":segment.id,"matching_contacts":0}
            q=q.filter(CRMContact.branch_id.in_(allowed))
    try: q=apply_segment(q,segment.definition)
    except ValueError as exc: raise HTTPException(422,str(exc))
    return {"segment_id":segment.id,"matching_contacts":q.count()}


@router.post("/campaigns/{campaign_id}/template")
def apply_template(campaign_id: int, payload: CRMTemplateApplyIn,
                   membership=Depends(active_membership), user: User=Depends(current_user),
                   db: Session=Depends(get_db)):
    require_permission(membership,"manage")
    campaign=_campaign(db,campaign_id,membership)
    if campaign.status!="draft": raise HTTPException(409,"Templates can only be applied to draft campaigns")
    template=db.query(CRMCampaignTemplate).filter_by(
        id=payload.template_id,organization_id=membership.organization_id,is_active=True).first()
    if not template: raise HTTPException(404,"Template not found")
    if template.channel!=campaign.channel or template.purpose!=campaign.purpose:
        raise HTTPException(422,"Template channel and purpose must match the campaign")
    campaign.template_id=template.id
    campaign.message=template.body
    campaign.subject=template.subject
    db.commit()
    return {"campaign_id":campaign.id,"template_id":template.id,"applied":True}


@router.post("/campaigns/{campaign_id}/segment")
def apply_campaign_segment(campaign_id: int, payload: CRMSegmentApplyIn,
                           membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership,"manage")
    campaign=_campaign(db,campaign_id,membership)
    if campaign.status!="draft": raise HTTPException(409,"Audience segments can only be changed on draft campaigns")
    segment=db.query(CRMContactSegment).filter_by(
        id=payload.segment_id,organization_id=membership.organization_id,is_active=True).first()
    if not segment or not can_access_branch(membership,segment.branch_id):
        raise HTTPException(404,"Segment not found")
    if campaign.branch_id and segment.branch_id and campaign.branch_id!=segment.branch_id:
        raise HTTPException(422,"Campaign and segment branches do not match")
    campaign.segment_id=segment.id
    db.commit()
    return {"campaign_id":campaign.id,"segment_id":segment.id,"applied":True}


@router.post("/campaigns/{campaign_id}/schedule")
def schedule_campaign(campaign_id: int, payload: CRMCampaignScheduleIn,
                      membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership,"manage")
    campaign=_campaign(db,campaign_id,membership)
    if campaign.status!="ready": raise HTTPException(409,"Prepare campaign before scheduling")
    if payload.scheduled_at.tzinfo is None or payload.scheduled_at<=datetime.now(timezone.utc):
        raise HTTPException(422,"Schedule time must be a future timezone-aware timestamp")
    campaign.scheduled_at=payload.scheduled_at.astimezone(timezone.utc)
    campaign.status="scheduled"
    db.commit()
    return {"campaign_id":campaign.id,"status":campaign.status,
            "scheduled_at":campaign.scheduled_at.isoformat()}


@router.post("/campaigns/{campaign_id}/unschedule")
def unschedule_campaign(campaign_id: int, membership=Depends(active_membership),
                        db: Session=Depends(get_db)):
    require_permission(membership,"manage")
    campaign=_campaign(db,campaign_id,membership)
    if campaign.status!="scheduled": raise HTTPException(409,"Only scheduled campaigns can be unscheduled")
    campaign.status="ready"; campaign.scheduled_at=None
    db.commit()
    return {"campaign_id":campaign.id,"status":campaign.status}


@router.post("/scheduler/run")
def run_due_campaigns(x_crm_scheduler_secret: str | None = Header(None),
                      db: Session=Depends(get_db)):
    if not settings.crm_scheduler_secret or not secrets.compare_digest(
        x_crm_scheduler_secret or "", settings.crm_scheduler_secret):
        raise HTTPException(401,"Invalid scheduler credentials")
    now=datetime.now(timezone.utc)
    due=db.query(CRMCampaign).filter(
        CRMCampaign.status.in_(["scheduled","partial"]),
        CRMCampaign.scheduled_at.is_not(None),
        CRMCampaign.scheduled_at<=now,
    ).order_by(CRMCampaign.scheduled_at,CRMCampaign.id).limit(50).all()
    results=[]
    for campaign in due:
        membership=db.query(Membership).filter_by(
            organization_id=campaign.organization_id,user_id=campaign.created_by,is_active=True).first()
        user=db.get(User,campaign.created_by)
        if not membership or not user or membership.role not in {"org_admin","branch_admin"}:
            campaign.status="failed"
            db.commit()
            results.append({"campaign_id":campaign.id,"status":"failed","reason":"No active authorized campaign owner"})
            continue
        try:
            result=dispatch_campaign(campaign.id,100,membership,user,db)
            results.append(result)
        except Exception as exc:
            db.rollback()
            results.append({"campaign_id":campaign.id,"status":"error","reason":str(exc)[:300]})
    return {"processed":len(results),"results":results}
