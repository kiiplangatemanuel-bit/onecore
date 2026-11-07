"""Versioned CRM templates, nested audiences and durable campaign scheduling."""
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, or_, true, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.models import (User, CRMCommunicationTemplate, CRMAudienceSegment,
    CRMCampaign, CRMCampaignSchedule, CRMContact, AuditEvent)
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, can_access_branch, branch_scope_ids
from app.api.crm_campaigns import dispatch_campaign

router=APIRouter(prefix="/api/v1/crm",tags=["CRM automation"])
CHANNELS={"email","sms","whatsapp"}
FIELDS={"full_name","email","phone","company"}
OPS={"eq","ne","contains","starts_with","ends_with","is_empty","not_empty","in"}
TEMPLATE_VARIABLES={"first_name","last_name","full_name","email","phone","company","campaign_name"}


def _branch(db,m,branch_id):
    if branch_id:
        from app.core.models import Branch
        if not can_access_branch(m,branch_id) or not db.query(Branch.id).filter_by(
            id=branch_id,organization_id=m.organization_id,is_active=True).first():
            raise HTTPException(404,"Branch not found")


def _asset_branch_ok(m,branch_id):
    return branch_id is None or can_access_branch(m,branch_id)


def _template(db,template_id,org,m):
    row=db.query(CRMCommunicationTemplate).filter_by(id=template_id,organization_id=org).first()
    if not row or not row.is_active or not _asset_branch_ok(m,row.branch_id):
        raise HTTPException(404,"Active template not found")
    return row


def _segment(db,segment_id,org,m):
    row=db.query(CRMAudienceSegment).filter_by(id=segment_id,organization_id=org,is_active=True).first()
    if not row or not _asset_branch_ok(m,row.branch_id):
        raise HTTPException(404,"Active audience segment not found")
    return row


def _validate_template(subject,body,variables):
    found=set(re.findall(r"{{\s*([a-z_]+)\s*}}",(subject or "")+" "+(body or "")))
    if found-TEMPLATE_VARIABLES:
        raise HTTPException(422,"Template contains unsupported personalization variables")
    if not isinstance(variables,list) or any(not isinstance(v,str) or v not in TEMPLATE_VARIABLES for v in variables):
        raise HTTPException(422,"Template variables must use the supported personalization allowlist")
    return sorted(found|set(variables))


def _field_clause(item):
    if not isinstance(item,dict) or set(item)-{"field","op","value"} or item.get("field") not in FIELDS or item.get("op") not in OPS:
        raise HTTPException(422,"Unsupported audience field or operator")
    field=getattr(CRMContact,item["field"])
    op=item["op"]
    value=item.get("value","")
    if op in {"is_empty","not_empty"}:
        if value not in ("",None,True):
            raise HTTPException(422,"Empty checks do not accept a comparison value")
        return or_(field.is_(None),field=="") if op=="is_empty" else and_(field.is_not(None),field!="")
    if op=="in":
        if not isinstance(value,list) or not 1<=len(value)<=20 or any(not isinstance(v,str) or len(v)>180 for v in value):
            raise HTTPException(422,"in requires 1–20 text values")
        return field.in_(value)
    if not isinstance(value,str) or len(value)>180:
        raise HTTPException(422,"Audience comparison values must be text up to 180 characters")
    if op=="eq": return field==value
    if op=="ne": return field!=value
    escaped=value.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")
    if op=="contains": return field.ilike("%"+escaped+"%",escape="\\")
    if op=="starts_with": return field.ilike(escaped+"%",escape="\\")
    if op=="ends_with": return field.ilike("%"+escaped,escape="\\")
    raise HTTPException(422,"Unsupported audience operator")


def compile_rules(node,depth=0):
    if depth>3 or not isinstance(node,dict) or not node or set(node)-{"all","any"}:
        raise HTTPException(422,"Audience rules must be nested all/any groups (maximum depth 3)")
    clauses=[]
    for group in ("all","any"):
        items=node.get(group,[])
        if not isinstance(items,list) or len(items)>20:
            raise HTTPException(422,"Each audience group supports at most 20 conditions")
        nested=[]
        for item in items:
            if isinstance(item,dict) and ({"all","any"} & set(item)):
                nested.append(compile_rules(item,depth+1))
            else:
                nested.append(_field_clause(item))
        if nested:
            clauses.append(and_(*nested) if group=="all" else or_(*nested))
    return and_(*clauses) if clauses else true()


def _branch_filter(query,model,m):
    allowed=branch_scope_ids(m)
    if allowed is not None:
        query=query.filter(or_(model.branch_id.is_(None),model.branch_id.in_(allowed)))
    return query


@router.get("/templates")
def list_templates(m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"read")
    q=_branch_filter(db.query(CRMCommunicationTemplate).filter_by(
        organization_id=m.organization_id,is_active=True),CRMCommunicationTemplate,m)
    return [{"id":x.id,"name":x.name,"version":x.version,"channel":x.channel,
        "purpose":x.purpose,"subject":x.subject,"body":x.body,"variables":x.variables,
        "branch_id":x.branch_id} for x in q.order_by(CRMCommunicationTemplate.name,CRMCommunicationTemplate.version.desc()).all()]


@router.post("/templates",status_code=201)
def create_template(payload:dict,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    name=str(payload.get("name","")).strip()
    channel=payload.get("channel")
    purpose=payload.get("purpose","marketing")
    body=payload.get("body")
    subject=str(payload.get("subject",""))[:240]
    branch_id=payload.get("branch_id") or None
    if not name or len(name)>180 or channel not in CHANNELS or purpose not in {"marketing","transactional"} or not isinstance(body,str) or not body.strip() or len(body)>100000:
        raise HTTPException(422,"Valid name, channel, purpose and body are required")
    _branch(db,m,branch_id)
    variables=_validate_template(subject,body,payload.get("variables",[]))
    version=(db.query(func.max(CRMCommunicationTemplate.version)).filter_by(
        organization_id=m.organization_id,name=name).scalar() or 0)+1
    db.query(CRMCommunicationTemplate).filter_by(
        organization_id=m.organization_id,name=name,is_active=True).update(
        {"is_active":False},synchronize_session=False)
    row=CRMCommunicationTemplate(organization_id=m.organization_id,branch_id=branch_id,
        name=name,version=version,channel=channel,purpose=purpose,subject=subject,
        body=body,variables=variables,created_by=u.id,is_active=True)
    db.add(row)
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,"Template version conflict")
    db.refresh(row)
    db.add(AuditEvent(actor_user_id=u.id,organization_id=m.organization_id,
        action="crm.template.created",resource_type="crm_communication_template",
        resource_id=str(row.id),detail=f"version:{row.version};channel:{row.channel}"))
    db.commit()
    return {"id":row.id,"name":row.name,"version":row.version,"variables":row.variables}


@router.put("/templates/{template_id}")
def update_template(template_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    old=db.query(CRMCommunicationTemplate).filter_by(
        id=template_id,organization_id=m.organization_id,is_active=True).first()
    if not old or not _asset_branch_ok(m,old.branch_id):raise HTTPException(404,"Active template not found")
    if payload.get("is_active") is False:
        old.is_active=False;db.commit()
        return {"id":old.id,"status":"deactivated"}
    name=str(payload.get("name",old.name)).strip()
    channel=payload.get("channel",old.channel)
    purpose=payload.get("purpose",old.purpose)
    subject=str(payload.get("subject",old.subject))[:240]
    body=payload.get("body",old.body)
    branch_id=payload.get("branch_id",old.branch_id) or None
    if not name or len(name)>180 or channel not in CHANNELS or purpose not in {"marketing","transactional"} or not isinstance(body,str) or not body.strip() or len(body)>100000:
        raise HTTPException(422,"Invalid template revision")
    _branch(db,m,branch_id)
    variables=_validate_template(subject,body,payload.get("variables",old.variables or []))
    version=(db.query(func.max(CRMCommunicationTemplate.version)).filter_by(
        organization_id=m.organization_id,name=name).scalar() or 0)+1
    old.is_active=False
    row=CRMCommunicationTemplate(organization_id=m.organization_id,branch_id=branch_id,
        name=name,version=version,channel=channel,purpose=purpose,subject=subject,
        body=body,variables=variables,created_by=u.id,is_active=True)
    db.add(row);db.commit();db.refresh(row)
    db.add(AuditEvent(actor_user_id=u.id,organization_id=m.organization_id,
        action="crm.template.revised",resource_type="crm_communication_template",
        resource_id=str(row.id),detail=f"previous:{old.id};version:{version}"))
    db.commit()
    return {"id":row.id,"name":row.name,"version":row.version}


@router.get("/segments")
def list_segments(m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"read")
    q=_branch_filter(db.query(CRMAudienceSegment).filter_by(
        organization_id=m.organization_id,is_active=True),CRMAudienceSegment,m)
    return [{"id":x.id,"name":x.name,"description":x.description,
        "rules":x.rules,"branch_id":x.branch_id} for x in q.order_by(CRMAudienceSegment.name).all()]


@router.post("/segments",status_code=201)
def create_segment(payload:dict,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    name=str(payload.get("name","")).strip()
    rules=payload.get("rules",{})
    branch_id=payload.get("branch_id") or None
    if not name or len(name)>180:raise HTTPException(422,"Segment name required")
    _branch(db,m,branch_id)
    compile_rules(rules)
    row=CRMAudienceSegment(organization_id=m.organization_id,branch_id=branch_id,
        name=name,description=str(payload.get("description",""))[:500],
        rules=rules,is_active=True,created_by=u.id)
    db.add(row)
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,"Segment name already exists")
    db.refresh(row)
    db.add(AuditEvent(actor_user_id=u.id,organization_id=m.organization_id,
        action="crm.segment.created",resource_type="crm_audience_segment",resource_id=str(row.id)))
    db.commit()
    return {"id":row.id,"name":row.name,"rules":row.rules}


@router.put("/segments/{segment_id}")
def update_segment(segment_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    row=_segment(db,segment_id,m)
    rules=payload.get("rules",row.rules)
    compile_rules(rules)
    name=str(payload.get("name",row.name)).strip()
    if not name or len(name)>180:raise HTTPException(422,"Segment name required")
    branch_id=payload.get("branch_id",row.branch_id) or None
    _branch(db,m,branch_id)
    row.name=name;row.description=str(payload.get("description",row.description))[:500]
    row.rules=rules;row.branch_id=branch_id
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,"Segment name already exists")
    db.add(AuditEvent(actor_user_id=u.id,organization_id=m.organization_id,
        action="crm.segment.updated",resource_type="crm_audience_segment",resource_id=str(row.id)))
    db.commit()
    return {"id":row.id,"name":row.name,"rules":row.rules}


@router.post("/segments/{segment_id}/deactivate")
def deactivate_segment(segment_id:int,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    row=_segment(db,segment_id,m);row.is_active=False
    db.add(AuditEvent(actor_user_id=u.id,organization_id=m.organization_id,
        action="crm.segment.deactivated",resource_type="crm_audience_segment",resource_id=str(row.id)))
    db.commit()
    return {"id":row.id,"status":"deactivated"}


def _segment(db,segment_id,m):
    row=db.query(CRMAudienceSegment).filter_by(
        id=segment_id,organization_id=m.organization_id,is_active=True).first()
    if not row or not _asset_branch_ok(m,row.branch_id):
        raise HTTPException(404,"Active audience segment not found")
    return row


@router.post("/segments/{segment_id}/preview")
def preview_segment(segment_id:int,channel:str="email",m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"read")
    if channel not in CHANNELS:raise HTTPException(422,"Unsupported channel")
    row=_segment(db,segment_id,m)
    q=db.query(CRMContact).filter(CRMContact.organization_id==m.organization_id)
    if row.branch_id:q=q.filter(CRMContact.branch_id==row.branch_id)
    else:
        allowed=branch_scope_ids(m)
        if allowed is not None:q=q.filter(CRMContact.branch_id.in_(allowed)) if allowed else q.filter(CRMContact.id==-1)
    q=q.filter(compile_rules(row.rules or {}))
    total=q.count()
    contacts=q.order_by(CRMContact.id).limit(100).all()
    addressable=sum(1 for x in contacts if (x.email if channel=="email" else x.phone))
    return {"segment_id":row.id,"matched_contacts":total,"sample":[{"id":x.id,"name":x.full_name,"company":x.company} for x in contacts],
        "addressable_sample":addressable,"truncated":total>100}


@router.post("/campaigns/{campaign_id}/schedule")
def schedule_campaign(campaign_id:int,payload:dict,m=Depends(active_membership),
    u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    campaign=db.query(CRMCampaign).filter_by(id=campaign_id,organization_id=m.organization_id).first()
    if not campaign or not can_access_branch(m,campaign.branch_id):raise HTTPException(404,"Campaign not found")
    if campaign.status not in {"ready","scheduled"}:raise HTTPException(409,"Prepare campaign before scheduling")
    try:
        at=datetime.fromisoformat(str(payload["scheduled_at"]).replace("Z","+00:00"))
        if at.tzinfo is None or at.utcoffset() is None:raise ValueError()
        zone=str(payload.get("timezone",payload.get("timezone_name","Africa/Nairobi")))
        ZoneInfo(zone)
    except (KeyError,ValueError,ZoneInfoNotFoundError):
        raise HTTPException(422,"scheduled_at must be timezone-aware and timezone must be an IANA name")
    if at.astimezone(timezone.utc)<=datetime.now(timezone.utc):raise HTTPException(422,"Schedule must be in the future")
    recurrence=payload.get("recurrence","once")
    if recurrence not in {"once","daily","weekly"}:raise HTTPException(422,"recurrence must be once, daily or weekly")
    template=_template(db,int(payload["template_id"]),m.organization_id,m) if payload.get("template_id") else None
    segment=_segment(db,int(payload["segment_id"]),m) if payload.get("segment_id") else None
    if template and (template.channel!=campaign.channel or template.purpose!=campaign.purpose):
        raise HTTPException(422,"Template channel and purpose must match the campaign")
    if template and template.branch_id and template.branch_id!=campaign.branch_id:
        raise HTTPException(422,"Template and campaign branch must match")
    if segment and segment.branch_id and campaign.branch_id and segment.branch_id!=campaign.branch_id:
        raise HTTPException(422,"Audience segment and campaign branch must match")
    row=db.query(CRMCampaignSchedule).filter_by(
        organization_id=m.organization_id,campaign_id=campaign.id).first()
    if row and row.status=="running":raise HTTPException(409,"Campaign schedule is currently running")
    if row is None:
        row=CRMCampaignSchedule(organization_id=m.organization_id,campaign_id=campaign.id,created_by=u.id)
        db.add(row)
    row.scheduled_at=at.astimezone(timezone.utc);row.timezone_name=zone
    row.recurrence=recurrence;row.template_id=template.id if template else None
    row.segment_id=segment.id if segment else None;row.next_run_at=row.scheduled_at
    row.status="scheduled";row.lease_until=None;row.last_error=""
    campaign.status="scheduled"
    db.add(AuditEvent(actor_user_id=u.id,organization_id=m.organization_id,
        action="crm.campaign.scheduled",resource_type="crm_campaign_schedule",resource_id=str(row.id or campaign.id),
        detail=f"recurrence:{recurrence};segment:{row.segment_id};template:{row.template_id}"))
    db.commit()
    return {"campaign_id":campaign.id,"scheduled_at":row.scheduled_at.isoformat(),
        "timezone":row.timezone_name,"recurrence":row.recurrence,"status":row.status}


@router.get("/schedules")
def list_schedules(m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"read")
    q=db.query(CRMCampaignSchedule,CRMCampaign).join(CRMCampaign,CRMCampaign.id==CRMCampaignSchedule.campaign_id).filter(
        CRMCampaignSchedule.organization_id==m.organization_id)
    allowed=branch_scope_ids(m)
    if allowed is not None:q=q.filter(CRMCampaign.branch_id.in_(allowed))
    return [{"campaign_id":c.id,"campaign_name":c.name,"status":s.status,
        "scheduled_at":s.scheduled_at.isoformat(),"next_run_at":s.next_run_at.isoformat() if s.next_run_at else None,
        "recurrence":s.recurrence,"run_count":s.run_count,"last_error":s.last_error,
        "last_run_at":s.last_run_at.isoformat() if s.last_run_at else None,
        "last_run_campaign_id":s.last_run_campaign_id} for s,c in q.order_by(CRMCampaignSchedule.next_run_at).all()]


@router.post("/campaigns/{campaign_id}/schedule/pause")
def pause_schedule(campaign_id:int,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    row=db.query(CRMCampaignSchedule).filter_by(organization_id=m.organization_id,campaign_id=campaign_id).first()
    if not row:raise HTTPException(404,"Schedule not found")
    if row.status!="scheduled":raise HTTPException(409,"Schedule cannot be paused in its current state")
    if row.lease_until and _utc(row.lease_until)>datetime.now(timezone.utc):raise HTTPException(409,"Schedule run is active")
    row.status="paused";row.next_run_at=None
    db.add(AuditEvent(actor_user_id=u.id,organization_id=m.organization_id,action="crm.schedule.paused",
        resource_type="crm_campaign_schedule",resource_id=str(row.id)));db.commit()
    return {"campaign_id":campaign_id,"status":row.status}


@router.post("/campaigns/{campaign_id}/schedule/resume")
def resume_schedule(campaign_id:int,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    row=db.query(CRMCampaignSchedule).filter_by(organization_id=m.organization_id,campaign_id=campaign_id).first()
    if not row or row.status not in {"paused","failed"}:raise HTTPException(404,"Paused or failed schedule not found")
    if row.recurrence=="once" and row.run_count:raise HTTPException(409,"One-time schedule already ran")
    row.status="scheduled";row.next_run_at=max(_utc(row.scheduled_at),datetime.now(timezone.utc))
    row.lease_until=None;row.claimed_at=None;row.last_error=""
    db.add(AuditEvent(actor_user_id=u.id,organization_id=m.organization_id,action="crm.schedule.resumed",
        resource_type="crm_campaign_schedule",resource_id=str(row.id)));db.commit()
    return {"campaign_id":campaign_id,"status":row.status,"next_run_at":row.next_run_at.isoformat()}


@router.delete("/campaigns/{campaign_id}/schedule")
def cancel_schedule(campaign_id:int,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    row=db.query(CRMCampaignSchedule).filter_by(organization_id=m.organization_id,campaign_id=campaign_id).first()
    if not row:raise HTTPException(404,"Schedule not found")
    if row.status=="running" or (row.lease_until and _utc(row.lease_until)>datetime.now(timezone.utc)):
        raise HTTPException(409,"Schedule is currently being processed")
    row.status="cancelled";row.next_run_at=None;row.lease_until=None
    campaign=db.query(CRMCampaign).filter_by(id=campaign_id,organization_id=m.organization_id).first()
    if campaign and campaign.status=="scheduled":campaign.status="ready"
    db.add(AuditEvent(actor_user_id=u.id,organization_id=m.organization_id,action="crm.schedule.cancelled",
        resource_type="crm_campaign_schedule",resource_id=str(row.id)));db.commit()
    return {"cancelled":True}


def _utc(value):
    if value is None:return None
    if value.tzinfo is None or value.utcoffset() is None:value=value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@router.post("/scheduler/run-due")
def run_due(m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    from app.services.crm_scheduler import run_due_schedules
    return {"processed":run_due_schedules(db,organization_id=m.organization_id,limit=20)}


@router.post("/campaigns/{campaign_id}/apply-template/{template_id}")
def apply_template(campaign_id:int,template_id:int,m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    campaign=db.query(CRMCampaign).filter_by(id=campaign_id,organization_id=m.organization_id).first()
    template=_template(db,template_id,m.organization_id,m)
    if not campaign or not can_access_branch(m,campaign.branch_id):raise HTTPException(404,"Campaign not found")
    if campaign.status!="draft":raise HTTPException(409,"Templates can only be applied to draft campaigns")
    if campaign.channel!=template.channel or campaign.purpose!=template.purpose:raise HTTPException(422,"Template channel and purpose must match")
    campaign.message=template.body;campaign.subject=template.subject or campaign.name
    db.commit()
    return {"campaign_id":campaign.id,"template_id":template.id,"applied":True,"variables":template.variables}
