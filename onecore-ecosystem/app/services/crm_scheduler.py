"""Durable scheduled CRM campaign execution.

One scheduler process is required for SQLite. PostgreSQL supports multiple workers
through row-level skip-locked claims. Each occurrence has a deterministic child
campaign, and provider idempotency keys make ambiguous retries safe.
"""
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import func, or_, update
from app.core.models import (CRMCampaign, CRMCampaignSchedule, CRMCommunicationTemplate,
    CRMAudienceSegment, CRMContact, CRMContactConsent, CRMCampaignRecipient,
    Membership, User, AuditEvent)
from app.services.datetime_utils import as_utc
from app.api.crm_automation import compile_rules, TEMPLATE_VARIABLES
from app.api.crm_campaigns import dispatch_campaign


def render_template(value,template,contact,campaign_name):
    variables=set(template.variables or [])
    first,last=(contact.full_name.split(" ",1)+[""])[:2]
    values={"first_name":first,"last_name":last,"full_name":contact.full_name,
        "email":contact.email or "","phone":contact.phone or "",
        "company":contact.company or "","campaign_name":campaign_name}
    found=set(re.findall(r"{{\s*([a-z_]+)\s*}}",value or ""))
    if found-TEMPLATE_VARIABLES or found-variables:
        raise ValueError("Template uses unsupported or undeclared personalization variables")
    return re.sub(r"{{\s*([a-z_]+)\s*}}",lambda match:values[match.group(1)],value or "")


def next_occurrence(value,recurrence,now,tz_name):
    if recurrence=="once":return None
    zone=ZoneInfo(tz_name)
    step=timedelta(days=1 if recurrence=="daily" else 7)
    nxt=as_utc(value).astimezone(zone)+step
    local_now=now.astimezone(zone)
    while nxt<=local_now:nxt+=step
    return nxt.astimezone(timezone.utc)


def _prepare_child(db,schedule,parent,membership,user,now,run_number):
    child_number=(parent.campaign_number[:45]+f"-R{run_number}")[:60]
    child=db.query(CRMCampaign).filter_by(
        organization_id=parent.organization_id,campaign_number=child_number).first()
    if child is not None:return child
    template=db.query(CRMCommunicationTemplate).filter_by(
        id=schedule.template_id,organization_id=schedule.organization_id).first() if schedule.template_id else None
    if schedule.template_id and template is None:
        raise ValueError("Scheduled template version is unavailable")
    segment=db.query(CRMAudienceSegment).filter_by(
        id=schedule.segment_id,organization_id=schedule.organization_id,is_active=True).first() if schedule.segment_id else None
    if schedule.segment_id and segment is None:
        raise ValueError("Scheduled audience segment is inactive or unavailable")
    if template and (template.channel!=parent.channel or template.purpose!=parent.purpose):
        raise ValueError("Scheduled template channel/purpose no longer matches the campaign")
    if template and template.branch_id and template.branch_id!=parent.branch_id:
        raise ValueError("Scheduled template branch no longer matches the campaign")
    if segment and segment.branch_id and parent.branch_id and segment.branch_id!=parent.branch_id:
        raise ValueError("Scheduled audience branch no longer matches the campaign")
    child=CRMCampaign(organization_id=parent.organization_id,
        branch_id=parent.branch_id or (segment.branch_id if segment else None),
        campaign_number=child_number,name=(parent.name[:155]+f" · run {run_number}")[:180],
        subject=template.subject if template else parent.subject,
        channel=parent.channel,purpose=parent.purpose,
        message=template.body if template else parent.message,
        status="ready",prepared_at=now,created_by=parent.created_by)
    db.add(child);db.flush()
    latest=db.query(func.max(CRMContactConsent.id).label("latest_id")).filter(
        CRMContactConsent.organization_id==parent.organization_id,
        CRMContactConsent.channel==parent.channel,
        CRMContactConsent.purpose==parent.purpose,
    ).group_by(CRMContactConsent.contact_id).subquery()
    q=db.query(CRMContact,CRMContactConsent).join(
        CRMContactConsent,CRMContactConsent.contact_id==CRMContact.id
    ).join(latest,latest.c.latest_id==CRMContactConsent.id).filter(
        CRMContact.organization_id==parent.organization_id,
        CRMContactConsent.organization_id==parent.organization_id,
        CRMContactConsent.decision=="granted",
    )
    branch_id=parent.branch_id or (segment.branch_id if segment else None)
    if branch_id:q=q.filter(CRMContact.branch_id==branch_id)
    else:
        scope=(membership.branch_scope or "").strip()
        if scope!="*":
            allowed=[x.strip() for x in scope.split(",") if x.strip()]
            q=q.filter(CRMContact.branch_id.in_(allowed)) if allowed else q.filter(CRMContact.id==-1)
    if segment:q=q.filter(compile_rules(segment.rules or {}))
    contacts=q.order_by(CRMContact.id).limit(5000).all()
    for contact,consent in contacts:
        if consent.expires_at and as_utc(consent.expires_at)<=now:continue
        address=contact.email if parent.channel=="email" else contact.phone
        if not address:continue
        subject=render_template(template.subject,template,contact,parent.name) if template and template.subject else (parent.subject or parent.name)
        body=render_template(template.body,template,contact,parent.name) if template else parent.message
        db.add(CRMCampaignRecipient(organization_id=parent.organization_id,
            campaign_id=child.id,contact_id=contact.id,consent_id=consent.id,
            channel=parent.channel,address_snapshot=address,status="prepared",
            subject_snapshot=subject[:240],message_snapshot=body))
    db.add(AuditEvent(actor_user_id=user.id,organization_id=parent.organization_id,
        action="crm.campaign.schedule_run_prepared",resource_type="crm_campaign",
        resource_id=str(child.id),detail=f"schedule:{schedule.id};run:{run_number};audience_cap:5000"))
    db.commit()
    return child


def _execute_schedule(db,schedule_id,now):
    schedule=db.query(CRMCampaignSchedule).filter_by(id=schedule_id).with_for_update().first()
    if not schedule or schedule.status!="running":return
    if not schedule.lease_until or as_utc(schedule.lease_until)<now:return
    parent=db.query(CRMCampaign).filter_by(
        id=schedule.campaign_id,organization_id=schedule.organization_id).first()
    membership=db.query(Membership).filter_by(
        organization_id=schedule.organization_id,user_id=schedule.created_by,is_active=True).first()
    user=db.query(User).filter_by(id=schedule.created_by,is_active=True).first()
    if not parent or not membership or not user:
        schedule.status="failed";schedule.lease_until=None; schedule.claimed_at=None
        schedule.last_error="Campaign, active campaign owner or organization membership is unavailable"
        db.commit();return
    run_number=schedule.run_count+1
    child=_prepare_child(db,schedule,parent,membership,user,now,run_number)
    if child.status!="sent":
        for _ in range(1500):
            schedule.lease_until=datetime.now(timezone.utc)+timedelta(minutes=10)
            db.commit()
            result=dispatch_campaign(child.id,batch_size=20,membership=membership,user=user,db=db)
            if result.get("remaining",0)<=0 or result.get("processed",0)<=0:break
    db.refresh(child)
    schedule.last_run_at=datetime.now(timezone.utc)
    schedule.last_run_campaign_id=child.id
    schedule.run_count=run_number
    schedule.last_error=""
    next_run=next_occurrence(schedule.next_run_at or schedule.scheduled_at,
        schedule.recurrence,datetime.now(timezone.utc),schedule.timezone_name)
    if next_run is None:
        schedule.status="completed";schedule.next_run_at=None
        parent.status=child.status
    else:
        schedule.status="scheduled";schedule.next_run_at=next_run
        parent.status="scheduled"
    schedule.lease_until=None;schedule.claimed_at=None
    db.add(AuditEvent(actor_user_id=user.id,organization_id=parent.organization_id,
        action="crm.campaign.schedule_run_completed",resource_type="crm_campaign_schedule",
        resource_id=str(schedule.id),detail=f"run:{run_number};campaign:{child.id};delivery_status:{child.status}"))
    db.commit()


def run_due_schedules(db,organization_id=None,limit=10):
    now=datetime.now(timezone.utc)
    processed=0
    for _ in range(limit):
        q=db.query(CRMCampaignSchedule).filter(CRMCampaignSchedule.status.in_(["scheduled","running"]))
        if organization_id is not None:q=q.filter(CRMCampaignSchedule.organization_id==organization_id)
        candidates=q.order_by(CRMCampaignSchedule.next_run_at,CRMCampaignSchedule.id).limit(100).with_for_update(skip_locked=True).all()
        row=next((x for x in candidates if x.next_run_at and as_utc(x.next_run_at)<=now
            and (x.status=="scheduled" or not x.lease_until or as_utc(x.lease_until)<now)),None)
        if not row:break
        claim_filters=[CRMCampaignSchedule.id==row.id,CRMCampaignSchedule.status==row.status]
        if row.status=="scheduled":
            claim_filters.append(CRMCampaignSchedule.next_run_at==row.next_run_at)
        elif row.lease_until is None:
            claim_filters.append(CRMCampaignSchedule.lease_until.is_(None))
        else:
            claim_filters.append(CRMCampaignSchedule.lease_until==row.lease_until)
        claimed=db.execute(update(CRMCampaignSchedule).where(*claim_filters).values(
            status="running",claimed_at=now,lease_until=now+timedelta(minutes=10)))
        schedule_id=row.id
        db.commit()
        if claimed.rowcount!=1:
            continue
        try:
            _execute_schedule(db,schedule_id,now)
        except Exception as exc:
            db.rollback()
            row=db.query(CRMCampaignSchedule).filter_by(id=schedule_id).first()
            if row:
                row.status="failed";row.claimed_at=None;row.lease_until=None
                row.last_error=str(exc)[:1000];db.commit()
        processed+=1
    return processed
