"""Reusable CRM templates, audience segmentation and campaign scheduling."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.models import (User, CRMMessageTemplate, CRMAudienceSegment, CRMCampaignSchedule,
    CRMCampaign, CRMContact, AuditEvent)
from app.core.automation_healthcare_schemas import CRMTemplateIn, CRMSegmentIn, CRMCampaignScheduleIn
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, branch_scope_ids, can_access_branch
from app.services.crm_automation import validate_segment_filters, matches_segment, validate_template_content
from app.services.datetime_utils import as_utc

router=APIRouter(prefix="/api/v1/crm",tags=["CRM automation"])


def _branch(db,membership,branch_id):
    if branch_id and not can_access_branch(membership,branch_id):
        raise HTTPException(403,"Branch is outside your assigned scope")
    if branch_id:
        from app.core.models import Branch
        if not db.query(Branch.id).filter_by(id=branch_id,organization_id=membership.organization_id,is_active=True).first():
            raise HTTPException(404,"Branch not found")


def _template(db,template_id,org):
    row=db.query(CRMMessageTemplate).filter_by(id=template_id,organization_id=org,is_active=True).first()
    if not row: raise HTTPException(404,"Active template not found")
    return row


def _segment(db,segment_id,org,membership):
    row=db.query(CRMAudienceSegment).filter_by(id=segment_id,organization_id=org,is_active=True).first()
    if not row or not can_access_branch(membership,row.branch_id):
        raise HTTPException(404,"Active audience segment not found")
    return row


@router.post("/templates",status_code=201)
def create_template(payload:CRMTemplateIn,membership=Depends(active_membership),
                    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage");_branch(db,membership,payload.branch_id)
    validate_template_content(payload.subject,payload.body)
    version=(db.query(func.max(CRMMessageTemplate.version)).filter_by(
        organization_id=membership.organization_id,name=payload.name.strip()).scalar() or 0)+1
    row=CRMMessageTemplate(organization_id=membership.organization_id,branch_id=payload.branch_id or None,
        name=payload.name.strip(),channel=payload.channel,purpose=payload.purpose,
        subject=payload.subject,body=payload.body,version=version,is_active=True,created_by=user.id)
    db.add(row)
    try: db.commit()
    except IntegrityError: db.rollback();raise HTTPException(409,"Template version conflict; retry")
    db.refresh(row)
    db.add(AuditEvent(actor_user_id=user.id,organization_id=membership.organization_id,
        action="crm.template.created",resource_type="crm_message_template",resource_id=str(row.id),
        detail=f"channel:{row.channel};version:{row.version}"));db.commit()
    return {"id":row.id,"name":row.name,"channel":row.channel,"version":row.version,"is_active":row.is_active}


@router.get("/templates")
def list_templates(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    q=db.query(CRMMessageTemplate).filter_by(organization_id=membership.organization_id,is_active=True)
    allowed=branch_scope_ids(membership)
    if allowed is not None:q=q.filter((CRMMessageTemplate.branch_id.is_(None)) | CRMMessageTemplate.branch_id.in_(allowed))
    return [{"id":x.id,"name":x.name,"channel":x.channel,"purpose":x.purpose,
        "subject":x.subject,"body":x.body,"version":x.version,"branch_id":x.branch_id}
        for x in q.order_by(CRMMessageTemplate.name).all()]


@router.put("/templates/{template_id}")
def revise_template(template_id:int,payload:CRMTemplateIn,membership=Depends(active_membership),
                    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage");old=_template(db,template_id,membership.organization_id)
    if not can_access_branch(membership,old.branch_id):raise HTTPException(404,"Template not found")
    validate_template_content(payload.subject,payload.body)
    _branch(db,membership,payload.branch_id)
    version=(db.query(func.max(CRMMessageTemplate.version)).filter_by(
        organization_id=membership.organization_id,name=payload.name).scalar() or 0)+1
    old.is_active=False
    row=CRMMessageTemplate(organization_id=membership.organization_id,branch_id=payload.branch_id,
        name=payload.name.strip(),channel=payload.channel,purpose=payload.purpose,
        subject=payload.subject,body=payload.body,version=version,is_active=True,created_by=user.id)
    db.add(row);db.commit();db.refresh(row)
    db.add(AuditEvent(actor_user_id=user.id,organization_id=membership.organization_id,
        action="crm.template.revised",resource_type="crm_message_template",resource_id=str(row.id),
        detail=f"previous:{old.id};version:{version}"));db.commit()
    return {"id":row.id,"name":row.name,"version":row.version,"is_active":True}


@router.post("/segments",status_code=201)
def create_segment(payload:CRMSegmentIn,membership=Depends(active_membership),
                   user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage");_branch(db,membership,payload.branch_id)
    validate_segment_filters(payload.filters)
    row=CRMAudienceSegment(organization_id=membership.organization_id,branch_id=payload.branch_id or None,
        name=payload.name.strip(),filters=payload.filters,is_active=True,created_by=user.id)
    db.add(row)
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,"Segment name already exists")
    db.refresh(row)
    db.add(AuditEvent(actor_user_id=user.id,organization_id=membership.organization_id,
        action="crm.segment.created",resource_type="crm_audience_segment",resource_id=str(row.id)));db.commit()
    return {"id":row.id,"name":row.name,"branch_id":row.branch_id,"filters":row.filters}


@router.get("/segments")
def list_segments(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    q=db.query(CRMAudienceSegment).filter_by(organization_id=membership.organization_id,is_active=True)
    allowed=branch_scope_ids(membership)
    if allowed is not None:q=q.filter((CRMAudienceSegment.branch_id.is_(None)) | CRMAudienceSegment.branch_id.in_(allowed))
    return [{"id":x.id,"name":x.name,"branch_id":x.branch_id,"filters":x.filters}
        for x in q.order_by(CRMAudienceSegment.name).all()]


@router.post("/segments/{segment_id}/preview")
def preview_segment(segment_id:int,channel:str=Query("email",pattern="^(email|sms|whatsapp)$"),
                    membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read");segment=_segment(db,segment_id,membership.organization_id,membership)
    q=db.query(CRMContact).filter_by(organization_id=membership.organization_id)
    if segment.branch_id:q=q.filter(CRMContact.branch_id==segment.branch_id)
    else:
        allowed=branch_scope_ids(membership)
        if allowed is not None:q=q.filter(CRMContact.branch_id.in_(allowed))
    rows=q.order_by(CRMContact.id).limit(5000).all()
    matched=[x for x in rows if matches_segment(x,segment.filters)]
    addressable=[x for x in matched if (x.email if channel=="email" else x.phone)]
    return {"segment_id":segment.id,"matched_contacts":len(matched),
        "addressable_contacts":len(addressable),"sample":[{"id":x.id,"name":x.full_name} for x in addressable[:20]],
        "truncated":len(rows)==5000}


@router.post("/campaigns/{campaign_id}/schedule",status_code=201)
def schedule_campaign(campaign_id:int,payload:CRMCampaignScheduleIn,
    membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    campaign=db.query(CRMCampaign).filter_by(id=campaign_id,organization_id=membership.organization_id).first()
    if not campaign or not can_access_branch(membership,campaign.branch_id):raise HTTPException(404,"Campaign not found")
    if campaign.status!="draft":raise HTTPException(409,"Only draft campaigns can be scheduled")
    if payload.scheduled_at.astimezone(timezone.utc)<=datetime.now(timezone.utc):
        raise HTTPException(422,"scheduled_at must be in the future")
    try:ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError:raise HTTPException(422,"Unknown IANA timezone")
    template=_template(db,payload.template_id,membership.organization_id) if payload.template_id else None
    if template and (template.channel!=campaign.channel or template.purpose!=campaign.purpose):
        raise HTTPException(422,"Template channel and purpose must match the campaign")
    if template and not can_access_branch(membership,template.branch_id):raise HTTPException(404,"Template not found")
    if template and campaign.branch_id and template.branch_id and campaign.branch_id!=template.branch_id:
        raise HTTPException(422,"Campaign and template branches do not match")
    segment=_segment(db,payload.segment_id,membership.organization_id,membership) if payload.segment_id else None
    if segment and campaign.branch_id and segment.branch_id and campaign.branch_id!=segment.branch_id:
        raise HTTPException(422,"Campaign and audience segment branches do not match")
    row=CRMCampaignSchedule(organization_id=membership.organization_id,campaign_id=campaign.id,
        template_id=template.id if template else None,segment_id=segment.id if segment else None,
        scheduled_at=payload.scheduled_at.astimezone(timezone.utc),timezone=payload.timezone,
        recurrence=payload.recurrence,next_run_at=payload.scheduled_at.astimezone(timezone.utc),
        status="scheduled",created_by=user.id)
    campaign.status="scheduled";db.add(row)
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,"Campaign already has a schedule")
    db.refresh(row)
    db.add(AuditEvent(actor_user_id=user.id,organization_id=membership.organization_id,
        action="crm.campaign.scheduled",resource_type="crm_campaign_schedule",resource_id=str(row.id),
        detail=f"campaign:{campaign.id};recurrence:{row.recurrence}"));db.commit()
    return {"id":row.id,"campaign_id":campaign.id,"status":row.status,
        "scheduled_at":row.scheduled_at.isoformat(),"timezone":row.timezone,"recurrence":row.recurrence}


@router.get("/schedules")
def list_schedules(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    q=db.query(CRMCampaignSchedule,CRMCampaign).join(
        CRMCampaign,CRMCampaign.id==CRMCampaignSchedule.campaign_id
    ).filter(CRMCampaignSchedule.organization_id==membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:q=q.filter(CRMCampaign.branch_id.in_(allowed))
    return [{"id":s.id,"campaign_id":c.id,"campaign_name":c.name,"status":s.status,
        "scheduled_at":s.scheduled_at.isoformat(),"next_run_at":s.next_run_at.isoformat() if s.next_run_at else None,
        "recurrence":s.recurrence,"run_count":s.run_count,"last_run_campaign_id":s.last_run_campaign_id,"last_error":s.last_error}
        for s,c in q.order_by(CRMCampaignSchedule.next_run_at).all()]


@router.post("/schedules/{schedule_id}/pause")
def pause_schedule(schedule_id:int,membership=Depends(active_membership),
                   user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(CRMCampaignSchedule).filter_by(id=schedule_id,organization_id=membership.organization_id).with_for_update().first()
    if not row:raise HTTPException(404,"Schedule not found")
    campaign=db.query(CRMCampaign).filter_by(id=row.campaign_id,organization_id=membership.organization_id).first()
    if not campaign or not can_access_branch(membership,campaign.branch_id):raise HTTPException(404,"Schedule not found")
    if row.status not in {"scheduled","failed"}:raise HTTPException(409,"Schedule cannot be paused in its current state")
    row.status="paused";row.next_run_at=None;row.lease_until=None;db.commit()
    db.add(AuditEvent(actor_user_id=user.id,organization_id=membership.organization_id,
        action="crm.campaign.schedule_paused",resource_type="crm_campaign_schedule",resource_id=str(row.id)));db.commit()
    return {"id":row.id,"status":row.status}


@router.post("/schedules/{schedule_id}/resume")
def resume_schedule(schedule_id:int,membership=Depends(active_membership),
                    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(CRMCampaignSchedule).filter_by(id=schedule_id,organization_id=membership.organization_id).with_for_update().first()
    if not row:raise HTTPException(404,"Schedule not found")
    campaign=db.query(CRMCampaign).filter_by(id=row.campaign_id,organization_id=membership.organization_id).first()
    if not campaign or not can_access_branch(membership,campaign.branch_id):raise HTTPException(404,"Schedule not found")
    if row.status not in {"paused","failed"}:raise HTTPException(409,"Schedule is not paused or failed")
    if row.recurrence=="once" and row.run_count>0:raise HTTPException(409,"One-time schedule has already run")
    row.status="scheduled";row.next_run_at=max(as_utc(row.scheduled_at),datetime.now(timezone.utc));row.lease_until=None;row.last_error=None;db.commit()
    db.add(AuditEvent(actor_user_id=user.id,organization_id=membership.organization_id,
        action="crm.campaign.schedule_resumed",resource_type="crm_campaign_schedule",resource_id=str(row.id)));db.commit()
    return {"id":row.id,"status":row.status,"next_run_at":row.next_run_at.isoformat()}
