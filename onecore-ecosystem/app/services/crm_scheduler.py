"""Durable one-time and recurring campaign scheduler.

Run as a separate process: python -m app.workers.crm_scheduler
"""
import re
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, or_
from app.core.models import (CRMCampaign, CRMCampaignSchedule, CRMMessageTemplate,
    CRMAudienceSegment, CRMContact, CRMContactConsent, CRMCampaignRecipient,
    Membership, User, AuditEvent)
from app.services.crm_automation import matches_segment
from app.api.crm_campaigns import dispatch_campaign
from app.services.datetime_utils import as_utc


PLACEHOLDERS={"first_name","last_name","full_name","email","phone","company","campaign_name"}


def render_message(template,contact,campaign_name):
    first,last=(contact.full_name.split(" ",1)+[""])[:2]
    values={"first_name":first,"last_name":last,"full_name":contact.full_name,
        "email":contact.email or "","phone":contact.phone or "",
        "company":contact.company or "","campaign_name":campaign_name}
    def replace(match):
        key=match.group(1)
        if key not in PLACEHOLDERS:
            raise ValueError("Unsupported template variable: "+key)
        return values[key]
    return re.sub(r"{{\s*([a-z_]+)\s*}}",replace,template or "")


def _next_occurrence(value,recurrence,now,tz_name):
    if recurrence=="once":return None
    from zoneinfo import ZoneInfo
    zone=ZoneInfo(tz_name)
    step=timedelta(days=1 if recurrence=="daily" else 7)
    nxt=as_utc(value).astimezone(zone)+step
    local_now=now.astimezone(zone)
    while nxt<=local_now:nxt+=step
    return nxt.astimezone(timezone.utc)


def _execute_schedule(db,schedule_id,now):
    schedule=db.query(CRMCampaignSchedule).filter_by(id=schedule_id).with_for_update().first()
    if not schedule or schedule.status!="scheduled":return
    if not schedule.lease_until or as_utc(schedule.lease_until)<now:
        return
    parent=db.query(CRMCampaign).filter_by(
        id=schedule.campaign_id,organization_id=schedule.organization_id).first()
    membership=db.query(Membership).filter_by(
        organization_id=schedule.organization_id,user_id=schedule.created_by,is_active=True).first()
    user=db.query(User).filter_by(id=schedule.created_by,is_active=True).first()
    if not parent or not membership or not user:
        schedule.status="failed";schedule.lease_until=None;db.commit();return
    run_number=schedule.run_count+1
    child_number=(parent.campaign_number[:45]+f"-R{run_number}")[:60]
    child=db.query(CRMCampaign).filter_by(
        organization_id=parent.organization_id,campaign_number=child_number).first()
    if child is None:
        template=db.query(CRMMessageTemplate).filter_by(
            id=schedule.template_id,organization_id=schedule.organization_id).first() if schedule.template_id else None
        segment=db.query(CRMAudienceSegment).filter_by(
            id=schedule.segment_id,organization_id=schedule.organization_id,is_active=True).first() if schedule.segment_id else None
        child=CRMCampaign(organization_id=parent.organization_id,branch_id=parent.branch_id,
            campaign_number=child_number,name=f"{parent.name} · run {run_number}",
            channel=parent.channel,purpose=parent.purpose,
            message=template.body if template else parent.message,status="ready",
            prepared_at=now,created_by=parent.created_by)
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
        contacts=q.order_by(CRMContact.id).limit(5000).all()
        for contact,consent in contacts:
            if consent.expires_at and as_utc(consent.expires_at)<=now:continue
            if segment and not matches_segment(contact,segment.filters):continue
            address=contact.email if parent.channel=="email" else contact.phone
            if not address:continue
            subject=render_message(template.subject,contact,parent.name) if template and template.subject else parent.name
            body=render_message(template.body,contact,parent.name) if template else parent.message
            db.add(CRMCampaignRecipient(organization_id=parent.organization_id,
                campaign_id=child.id,contact_id=contact.id,consent_id=consent.id,
                channel=parent.channel,address_snapshot=address,status="prepared",
                subject_snapshot=subject[:180],message_snapshot=body))
        db.add(AuditEvent(actor_user_id=user.id,organization_id=parent.organization_id,
            action="crm.campaign.schedule_run_prepared",resource_type="crm_campaign",
            resource_id=str(child.id),detail=f"schedule:{schedule.id};run:{run_number}"))
        db.commit()
    # Dispatch through the same permission, consent, retry, callback and provider path
    # used by a manager-triggered batch. Each recipient has a stable idempotency key.
    if child.status!="sent":
        # Small bounded batches keep each lease-renewal interval below the ten-minute
        # recovery lease even when a provider responds slowly.
        for _ in range(1000):
            schedule.lease_until=datetime.now(timezone.utc)+timedelta(minutes=10)
            db.commit()
            result=dispatch_campaign(child.id,batch_size=25,membership=membership,user=user,db=db)
            if result.get("remaining",0)<=0 or result.get("processed",0)<=0:
                break
    db.refresh(child)
    schedule.last_run_at=now
    schedule.last_error=None
    schedule.last_run_campaign_id=child.id
    schedule.run_count=run_number
    next_run=_next_occurrence(schedule.next_run_at or schedule.scheduled_at,schedule.recurrence,now,schedule.timezone)
    if next_run is None:
        schedule.status="completed"
        schedule.next_run_at=None
    else:
        schedule.status="scheduled"
        schedule.next_run_at=next_run
    schedule.lease_until=None
    db.add(AuditEvent(actor_user_id=user.id,organization_id=parent.organization_id,
        action="crm.campaign.schedule_run_completed",resource_type="crm_campaign_schedule",
        resource_id=str(schedule.id),detail=f"run:{run_number};campaign:{child.id};campaign_status:{child.status}"))
    db.commit()


def run_due_schedules(db,limit=10):
    now=datetime.now(timezone.utc)
    processed=0
    for _ in range(limit):
        candidates=db.query(CRMCampaignSchedule).filter(
            CRMCampaignSchedule.status=="scheduled"
        ).order_by(CRMCampaignSchedule.next_run_at,CRMCampaignSchedule.id).limit(100).with_for_update(skip_locked=True).all()
        row=next((candidate for candidate in candidates
            if candidate.next_run_at and as_utc(candidate.next_run_at)<=now
            and (candidate.lease_until is None or as_utc(candidate.lease_until)<now)),None)
        if not row:break
        row.lease_until=now+timedelta(minutes=10)
        schedule_id=row.id
        db.commit()
        try:
            _execute_schedule(db,schedule_id,now)
        except Exception as exc:
            db.rollback()
            row=db.query(CRMCampaignSchedule).filter_by(id=schedule_id).first()
            if row:
                row.status="failed";row.lease_until=None;row.last_error=str(exc)[:1000];db.commit()
        processed+=1
    return processed
