"""CRM templates, saved audience rules and scheduled campaign dispatch."""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.core.database import get_db
from app.core.models import (User, CRMCommunicationTemplate, CRMAudienceSegment,
    CRMCampaign, CRMCampaignSchedule, CRMContact)
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, can_access_branch
from app.api.crm_campaigns import dispatch_campaign

router=APIRouter(prefix="/api/v1/crm",tags=["CRM automation"])
CHANNELS={"email","sms","whatsapp"}
FIELDS={"full_name","email","phone","company"}
OPS={"eq","contains","starts_with","is_empty","not_empty"}

@router.get("/templates")
def list_templates(m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"read")
    return [{"id":x.id,"name":x.name,"channel":x.channel,"purpose":x.purpose,"subject":x.subject,"body":x.body,"variables":x.variables}
        for x in db.query(CRMCommunicationTemplate).filter_by(organization_id=m.organization_id,is_active=True).all()]

@router.post("/templates")
def create_template(payload:dict,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    name=str(payload.get("name","")).strip(); channel=payload.get("channel"); body=str(payload.get("body",""))
    if not name or len(name)>180 or channel not in CHANNELS or not body or len(body)>100000: raise HTTPException(422,"Valid name, channel and body required")
    variables=payload.get("variables",[])
    if not isinstance(variables,list) or any(not isinstance(v,str) or not v.isidentifier() for v in variables): raise HTTPException(422,"Variables must be identifier names")
    x=CRMCommunicationTemplate(organization_id=m.organization_id,name=name,channel=channel,purpose=payload.get("purpose","marketing"),
        subject=str(payload.get("subject",""))[:240],body=body,variables=variables,created_by=u.id)
    db.add(x); db.commit(); db.refresh(x); return {"id":x.id,"name":x.name}

@router.put("/templates/{template_id}")
def update_template(template_id:int,payload:dict,m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    x=db.query(CRMCommunicationTemplate).filter_by(id=template_id,organization_id=m.organization_id).first()
    if not x: raise HTTPException(404,"Template not found")
    if "body" in payload:
        if not isinstance(payload["body"],str) or not payload["body"] or len(payload["body"])>100000: raise HTTPException(422,"Invalid body")
        x.body=payload["body"]
    if "subject" in payload: x.subject=str(payload["subject"])[:240]
    if "is_active" in payload: x.is_active=bool(payload["is_active"])
    db.commit(); return {"id":x.id,"updated":True}

def compile_rules(rules):
    if not isinstance(rules,dict) or set(rules)-{"all","any"}: raise HTTPException(422,"Rules must contain all/any groups only")
    clauses=[]
    for group in ("all","any"):
        items=rules.get(group,[])
        if not isinstance(items,list) or len(items)>20: raise HTTPException(422,"Each segment group supports at most 20 conditions")
        for item in items:
            if not isinstance(item,dict) or item.get("field") not in FIELDS or item.get("op") not in OPS: raise HTTPException(422,"Unsupported segment condition")
            field=getattr(CRMContact,item["field"]); op=item["op"]; value=str(item.get("value",""))[:180]
            if op=="eq": clauses.append(field==value)
            elif op=="contains": clauses.append(field.ilike("%"+value.replace("%","\\%").replace("_","\\_")+"%"))
            elif op=="starts_with": clauses.append(field.ilike(value.replace("%","\\%").replace("_","\\_")+"%"))
            elif op=="is_empty": clauses.append(or_(field.is_(None),field==""))
            elif op=="not_empty": clauses.append(field.is_not(None) & (field!=""))
    return clauses

@router.post("/segments")
def create_segment(payload:dict,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    if not str(payload.get("name","")).strip(): raise HTTPException(422,"Segment name required")
    rules=payload.get("rules",{}); compile_rules(rules)
    x=CRMAudienceSegment(organization_id=m.organization_id,name=str(payload["name"])[:180],description=str(payload.get("description",""))[:500],rules=rules,created_by=u.id)
    db.add(x); db.commit(); db.refresh(x); return {"id":x.id,"name":x.name}

@router.get("/segments/{segment_id}/preview")
def preview_segment(segment_id:int,m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"read")
    x=db.query(CRMAudienceSegment).filter_by(id=segment_id,organization_id=m.organization_id,is_active=True).first()
    if not x: raise HTTPException(404,"Segment not found")
    rules=x.rules or {}; groups=[]
    for group in ("all","any"):
        clauses=compile_rules({group:rules.get(group,[])})
        if clauses: groups.append((group,clauses))
    q=db.query(CRMContact).filter(CRMContact.organization_id==m.organization_id)
    for group,clauses in groups:
        if group=="all":
            for clause in clauses: q=q.filter(clause)
        else: q=q.filter(or_(*clauses))
    total=q.count()
    contacts=q.order_by(CRMContact.id).limit(100).all()
    return {"segment_id":x.id,"count":total,"sample":[{"id":c.id,"name":c.full_name,"company":c.company} for c in contacts]}

@router.post("/campaigns/{campaign_id}/schedule")
def schedule_campaign(campaign_id:int,payload:dict,m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    c=db.query(CRMCampaign).filter_by(id=campaign_id,organization_id=m.organization_id).first()
    if not c or not can_access_branch(m,c.branch_id): raise HTTPException(404,"Campaign not found")
    if c.status not in {"ready","scheduled"}: raise HTTPException(409,"Prepare campaign before scheduling")
    try:
        at=datetime.fromisoformat(str(payload["scheduled_at"]).replace("Z","+00:00"))
        if at.tzinfo is None: raise ValueError()
        zone=str(payload.get("timezone","Africa/Nairobi"))[:80]
    except Exception: raise HTTPException(422,"scheduled_at must be ISO-8601 with timezone")
    if at<=datetime.now(timezone.utc): raise HTTPException(422,"Schedule must be in the future")
    s=db.query(CRMCampaignSchedule).filter_by(organization_id=m.organization_id,campaign_id=c.id).first()
    if not s:
        s=CRMCampaignSchedule(organization_id=m.organization_id,campaign_id=c.id,scheduled_at=at,timezone_name=zone,created_by=u.id); db.add(s)
    else:
        if s.status=="running": raise HTTPException(409,"Schedule is currently being dispatched")
        s.scheduled_at=at; s.timezone_name=zone; s.status="scheduled"; s.last_error=""
    c.status="scheduled"; db.commit(); return {"campaign_id":c.id,"scheduled_at":at.isoformat(),"status":"scheduled"}

@router.delete("/campaigns/{campaign_id}/schedule")
def cancel_schedule(campaign_id:int,m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    s=db.query(CRMCampaignSchedule).filter_by(campaign_id=campaign_id,organization_id=m.organization_id).first()
    if not s: raise HTTPException(404,"Schedule not found")
    if s.status=="running": raise HTTPException(409,"Cannot cancel a running schedule")
    s.status="cancelled"; c=db.query(CRMCampaign).filter_by(id=campaign_id,organization_id=m.organization_id).first()
    if c and c.status=="scheduled": c.status="ready"
    db.commit(); return {"cancelled":True}

@router.post("/scheduler/run-due")
def run_due(m=Depends(active_membership),u:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    now=datetime.now(timezone.utc); due=db.query(CRMCampaignSchedule).filter_by(organization_id=m.organization_id,status="scheduled").filter(CRMCampaignSchedule.scheduled_at<=now).order_by(CRMCampaignSchedule.scheduled_at).limit(20).with_for_update().all()
    results=[]
    for s in due:
        s.status="running"; s.claimed_at=now; db.commit()
        try:
            campaign=db.query(CRMCampaign).filter_by(id=s.campaign_id,organization_id=m.organization_id).first()
            if not campaign: raise HTTPException(404,"Scheduled campaign not found")
            campaign.status="ready"
            db.commit()
            result=dispatch_campaign(s.campaign_id,100,m,u,db)
            s.status="completed" if result.get("remaining",0)==0 else "scheduled"
            if s.status=="scheduled": s.last_error="Batch incomplete; invoke scheduler again to continue"
            results.append({"campaign_id":s.campaign_id,**result})
        except Exception as exc:
            s.status="failed"; s.last_error=str(exc)[:1000]; results.append({"campaign_id":s.campaign_id,"error":"dispatch failed"})
        db.commit()
    return {"processed":len(results),"results":results}

@router.post("/campaigns/{campaign_id}/apply-template/{template_id}")
def apply_template(campaign_id:int,template_id:int,m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    campaign=db.query(CRMCampaign).filter_by(id=campaign_id,organization_id=m.organization_id).first()
    template=db.query(CRMCommunicationTemplate).filter_by(id=template_id,organization_id=m.organization_id,is_active=True).first()
    if not campaign or not template: raise HTTPException(404,"Campaign or template not found")
    if campaign.status!="draft": raise HTTPException(409,"Templates can only be applied to draft campaigns")
    if campaign.channel!=template.channel: raise HTTPException(422,"Template channel must match campaign channel")
    if campaign.purpose!=template.purpose: raise HTTPException(422,"Template purpose must match campaign purpose")
    campaign.message=template.body
    db.commit()
    return {"campaign_id":campaign.id,"template_id":template.id,"applied":True,"variables":template.variables}
