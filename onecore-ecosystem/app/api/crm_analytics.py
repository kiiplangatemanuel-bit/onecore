"""Advanced CRM forecasting, quotas, campaign attribution and scheduler monitoring."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.config import settings
from app.core.models import (User, Membership, Organization, Branch, CRMLead, CRMForecastSetting,
    CRMSalesTarget, CRMForecastSnapshot, CRMContact, CRMCampaign, CRMCampaignAttribution,
    CRMSalesOrder, CRMWorkerHeartbeat, CRMCampaignSchedule, AuditEvent)
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, branch_scope_ids, can_access_branch
from app.services.crm_forecast import STAGES, DEFAULT_PROBABILITIES, DEFAULT_MULTIPLIERS, period_bounds, calculate_scenarios

router=APIRouter(prefix="/api/v1/crm",tags=["CRM forecasting and attribution"])

def _period(kind,start):
    try:return period_bounds(kind,start)
    except ValueError as exc:raise HTTPException(422,str(exc))

def _scope(q,m,model):
    allowed=branch_scope_ids(m)
    if allowed is not None:q=q.filter(model.branch_id.in_(allowed)) if allowed else q.filter(model.id==-1)
    return q

def _rep(db,org,rep):
    if rep is not None and not db.query(Membership.id).filter_by(
        organization_id=org,user_id=rep,is_active=True).first():
        raise HTTPException(422,"Representative must be an active organization member")

def _settings(db,org):
    row=db.query(CRMForecastSetting).filter_by(organization_id=org).first()
    return (row.stage_probabilities if row else DEFAULT_PROBABILITIES,
        row.scenario_multipliers if row else DEFAULT_MULTIPLIERS)

def _leads(db,m,first,last,rep=None):
    q=db.query(CRMLead).filter(CRMLead.organization_id==m.organization_id,
        CRMLead.expected_close_date>=datetime.combine(first,time.min,timezone.utc),
        CRMLead.expected_close_date<datetime.combine(last+timedelta(days=1),time.min,timezone.utc),
        CRMLead.stage.notin_(["won","lost"]))
    q=_scope(q,m,CRMLead)
    if rep is not None:q=q.filter(CRMLead.assigned_to==rep)
    return q.all()

@router.patch("/leads/{lead_id}/forecast-details")
def update_forecast_details(lead_id:int,payload:dict,m=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"update")
    row=db.query(CRMLead).filter_by(id=lead_id,organization_id=m.organization_id).first()
    if not row or not can_access_branch(m,row.branch_id):raise HTTPException(404,"Lead not found")
    if "expected_close_date" in payload:
        try:
            value=payload["expected_close_date"]
            parsed=datetime.fromisoformat(value.replace("Z","+00:00")) if value else None
            if parsed is not None and parsed.tzinfo is None:raise ValueError()
            row.expected_close_date=parsed.astimezone(timezone.utc) if parsed else None
        except Exception:raise HTTPException(422,"expected_close_date must be timezone-aware ISO-8601 or null")
    if "probability_override" in payload:
        value=payload["probability_override"]
        if value is not None:
            try:probability=Decimal(str(value))
            except Exception:raise HTTPException(422,"probability_override must be numeric")
            if isinstance(value,bool) or not probability.is_finite() or not 0<=probability<=100:
                raise HTTPException(422,"probability_override must be between 0 and 100")
            row.probability_override=probability
        else:row.probability_override=None
    if row.stage=="won" and row.actual_closed_at is None:
        row.actual_closed_at=datetime.now(timezone.utc)
        if row.actual_value is None:row.actual_value=row.estimated_value
    if row.stage!="won":
        row.actual_closed_at=None
        row.actual_value=None
    if "actual_value" in payload:
        if row.stage!="won":raise HTTPException(409,"Actual value can only be set on a won lead")
        try:value=Decimal(str(payload["actual_value"]))
        except Exception:raise HTTPException(422,"Invalid actual_value")
        if not value.is_finite() or value<0 or value>Decimal("9999999999999999"):raise HTTPException(422,"Invalid actual_value")
        row.actual_value=value
    db.add(AuditEvent(organization_id=m.organization_id,actor_user_id=user.id,
        action="crm.lead.forecast_details.updated",resource_type="crm_lead",resource_id=str(row.id)))
    db.commit()
    return {"lead_id":row.id,"expected_close_date":row.expected_close_date.isoformat() if row.expected_close_date else None,
        "probability_override":str(row.probability_override) if row.probability_override is not None else None}

@router.post("/forecast/settings")
def save_forecast_settings(payload:dict,m=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    probabilities=payload.get("stage_probabilities",DEFAULT_PROBABILITIES)
    multipliers=payload.get("scenario_multipliers",DEFAULT_MULTIPLIERS)
    if not isinstance(probabilities,dict) or set(probabilities)!=STAGES or any(
        isinstance(v,bool) or not isinstance(v,(int,float)) or not 0<=v<=100 for v in probabilities.values()):
        raise HTTPException(422,"Define a 0–100 probability for every pipeline stage")
    expected={"best_case","expected","worst_case"}
    if not isinstance(multipliers,dict) or set(multipliers)!=expected or any(
        isinstance(v,bool) or not isinstance(v,(int,float)) or not 0<=v<=2 for v in multipliers.values()):
        raise HTTPException(422,"Define scenario multipliers from 0 to 2")
    row=db.query(CRMForecastSetting).filter_by(organization_id=m.organization_id).first()
    if not row:row=CRMForecastSetting(organization_id=m.organization_id,updated_by=user.id,stage_probabilities=probabilities,scenario_multipliers=multipliers);db.add(row)
    row.stage_probabilities=probabilities;row.scenario_multipliers=multipliers;row.updated_by=user.id
    db.add(AuditEvent(organization_id=m.organization_id,actor_user_id=user.id,
        action="crm.forecast.settings.updated",resource_type="crm_forecast_settings"))
    db.commit()
    return {"stage_probabilities":probabilities,"scenario_multipliers":multipliers}

@router.post("/targets")
def upsert_target(payload:dict,m=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    try:
        kind=str(payload["period_type"]);start=date.fromisoformat(str(payload["period_start"]))
        first,last=_period(kind,start);amount=Decimal(str(payload["target_amount"]))
        currency=str(payload.get("currency","KES")).upper();rep=payload.get("assigned_to");branch=payload.get("branch_id")
    except Exception:raise HTTPException(422,"Invalid target payload")
    if first!=start or not amount.is_finite() or amount<0 or amount>Decimal("9999999999999999"):
        raise HTTPException(422,"Target must be non-negative and period_start must be the period's first day")
    if len(currency)!=3 or not currency.isalpha() or not currency.isupper():raise HTTPException(422,"Currency must be a 3-letter uppercase code")
    _rep(db,m.organization_id,rep)
    if branch and (not can_access_branch(m,branch) or not db.query(Branch.id).filter_by(
        id=branch,organization_id=m.organization_id,is_active=True).first()):raise HTTPException(404,"Branch not found")
    rep_key=str(rep) if rep is not None else "team"
    start_dt=datetime.combine(first,time.min,timezone.utc)
    row=db.query(CRMSalesTarget).filter_by(organization_id=m.organization_id,period_type=kind,
        period_start=start_dt,rep_key=rep_key,currency=currency).first()
    if not row:
        row=CRMSalesTarget(organization_id=m.organization_id,period_type=kind,period_start=start_dt,
            rep_key=rep_key,assigned_to=rep,branch_id=branch,currency=currency,target_amount=amount,created_by=user.id)
        db.add(row)
    else:row.target_amount=amount;row.branch_id=branch
    db.add(AuditEvent(organization_id=m.organization_id,actor_user_id=user.id,
        action="crm.sales_target.upserted",resource_type="crm_sales_target",
        detail="period:%s;rep:%s;currency:%s"%(kind,rep_key,currency)))
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,"Target update conflict; retry")
    db.refresh(row)
    return {"id":row.id,"period_type":kind,"period_start":first.isoformat(),"assigned_to":rep,
        "branch_id":branch,"currency":currency,"target_amount":str(row.target_amount)}

@router.get("/targets")
def list_targets(period_type:str=Query("month",pattern="^(month|quarter|year)$"),
    period_start:date=Query(default_factory=date.today),m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"read");first,last=_period(period_type,period_start)
    q=db.query(CRMSalesTarget).filter_by(organization_id=m.organization_id,period_type=period_type,
        period_start=datetime.combine(first,time.min,timezone.utc))
    allowed=branch_scope_ids(m)
    if allowed is not None:q=q.filter(or_(CRMSalesTarget.branch_id.is_(None),CRMSalesTarget.branch_id.in_(allowed)))
    return [{"id":x.id,"assigned_to":x.assigned_to,"branch_id":x.branch_id,"currency":x.currency,
        "target_amount":str(x.target_amount),"period_type":x.period_type,"period_start":first.isoformat()}
        for x in q.order_by(CRMSalesTarget.currency,CRMSalesTarget.assigned_to).all()]

@router.get("/forecast/advanced")
def advanced_forecast(period_type:str=Query("month",pattern="^(month|quarter|year)$"),
    start_date:date=Query(default_factory=date.today),rep_id:int|None=None,
    m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"read");_rep(db,m.organization_id,rep_id)
    first,last=_period(period_type,start_date);probs,mults=_settings(db,m.organization_id);leads=_leads(db,m,first,last,rep_id)
    grouped={}
    by_currency={}
    for lead in leads:
        grouped.setdefault((lead.assigned_to if lead.assigned_to is not None else -1,lead.currency),[]).append(lead)
        by_currency.setdefault(lead.currency,[]).append(lead)
    if rep_id is None:
        for currency,items in by_currency.items():grouped[(-2,currency)]=items
    target_rows=db.query(CRMSalesTarget).filter_by(organization_id=m.organization_id,
        period_type=period_type,period_start=datetime.combine(first,time.min,timezone.utc)).all()
    targets={}
    for x in target_rows:
        if x.branch_id is not None and not can_access_branch(m,x.branch_id):continue
        key=(int(x.assigned_to) if x.assigned_to is not None else -2,x.currency)
        targets[key]=x.target_amount
    for key in targets:grouped.setdefault(key,[])
    base_currency=db.query(Organization.currency).filter_by(id=m.organization_id).scalar() or "KES"
    if rep_id is None:grouped.setdefault((-2,base_currency),[])
    else:grouped.setdefault((rep_id,base_currency),[])
    output=[]
    for (owner,currency),items in sorted(grouped.items(),key=lambda pair:(pair[0][1],pair[0][0])):
        scenarios=calculate_scenarios(items,probs,mults)
        target=targets.get((owner,currency),Decimal("0"))
        expected=scenarios["expected"]
        output.append({"representative_id":owner if owner>0 else None,
            "group":"team" if owner==-2 else ("unassigned" if owner==-1 else "representative"),
            "currency":currency,"opportunity_count":len(items),
            "pipeline_amount":str(sum((Decimal(str(x.estimated_value)) for x in items),Decimal("0"))),
            "best_case":str(scenarios["best_case"]),"expected":str(expected),"worst_case":str(scenarios["worst_case"]),
            "target_amount":str(target),"attainment_percent":str((expected/target*100).quantize(Decimal("0.01")) if target else Decimal("0"))})
    undated=db.query(func.count(CRMLead.id)).filter(CRMLead.organization_id==m.organization_id,
        CRMLead.expected_close_date.is_(None),CRMLead.stage.notin_(["won","lost"]))
    undated=_scope(undated,m,CRMLead)
    if rep_id is not None:undated=undated.filter(CRMLead.assigned_to==rep_id)
    return {"period_type":period_type,"period_start":first.isoformat(),"period_end":last.isoformat(),
        "currency_note":"Amounts remain grouped by currency; do not add unlike currencies.",
        "undated_open_opportunities":undated.scalar() or 0,"rows":output}

@router.post("/forecast/snapshots",status_code=201)
def create_snapshot(payload:dict,m=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    try:kind=str(payload["period_type"]);start=date.fromisoformat(str(payload["period_start"]));scenario=str(payload.get("scenario","expected"));rep=payload.get("rep_id")
    except Exception:raise HTTPException(422,"Invalid snapshot parameters")
    if scenario not in {"best_case","expected","worst_case"}:raise HTTPException(422,"Invalid scenario")
    _rep(db,m.organization_id,rep);first,last=_period(kind,start);probs,mults=_settings(db,m.organization_id)
    selected=_leads(db,m,first,last,rep)
    grouped={}
    by_currency={}
    for lead in selected:
        grouped.setdefault((lead.assigned_to if lead.assigned_to is not None else -1,lead.currency),[]).append(lead)
        by_currency.setdefault(lead.currency,[]).append(lead)
    if rep is None:
        for currency,items in by_currency.items():grouped[(-2,currency)]=items
    target_rows=db.query(CRMSalesTarget).filter_by(organization_id=m.organization_id,period_type=kind,
        period_start=datetime.combine(first,time.min,timezone.utc)).all()
    for target in target_rows:
        if rep is not None and target.assigned_to!=rep:continue
        if target.branch_id is None or can_access_branch(m,target.branch_id):
            key=(int(target.assigned_to) if target.assigned_to is not None else -2,target.currency)
            grouped.setdefault(key,[])
    base_currency=db.query(Organization.currency).filter_by(id=m.organization_id).scalar() or "KES"
    if rep is None:grouped.setdefault((-2,base_currency),[])
    else:grouped.setdefault((rep,base_currency),[])
    now=datetime.now(timezone.utc);count=0
    for (owner,currency),items in grouped.items():
        db.add(CRMForecastSnapshot(organization_id=m.organization_id,period_type=kind,
            period_start=datetime.combine(first,time.min,timezone.utc),period_end=datetime.combine(last,time.max,timezone.utc),
            rep_key=("team" if owner==-2 else ("unassigned" if owner==-1 else str(owner))),assigned_to=owner if owner>0 else None,currency=currency,scenario=scenario,
            forecast_amount=calculate_scenarios(items,probs,mults)[scenario],opportunity_count=len(items),
            snapshot_at=now,snapshot_by=user.id));count+=1
    db.add(AuditEvent(organization_id=m.organization_id,actor_user_id=user.id,
        action="crm.forecast.snapshot.created",resource_type="crm_forecast_snapshot",
        detail="period:%s;start:%s;scenario:%s;rows:%s"%(kind,first,scenario,count)))
    db.commit()
    return {"snapshot_count":count,"snapshot_at":now.isoformat(),"scenario":scenario}

@router.get("/forecast/accuracy")
def forecast_accuracy(period_type:str=Query("month",pattern="^(month|quarter|year)$"),
    period_start:date=Query(default_factory=date.today),rep_id:int|None=None,m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"read");_rep(db,m.organization_id,rep_id);first,last=_period(period_type,period_start)
    q=db.query(CRMForecastSnapshot).filter_by(organization_id=m.organization_id,period_type=period_type,
        period_start=datetime.combine(first,time.min,timezone.utc))
    if rep_id is not None:q=q.filter(CRMForecastSnapshot.assigned_to==rep_id)
    latest={}
    for row in q.order_by(CRMForecastSnapshot.snapshot_at.desc()).all():
        latest.setdefault((row.rep_key,row.currency,row.scenario),row)
    output=[]
    for (_,currency,scenario),snap in latest.items():
        actual_q=db.query(func.coalesce(func.sum(func.coalesce(CRMLead.actual_value,CRMLead.estimated_value)),0)).filter(
            CRMLead.organization_id==m.organization_id,CRMLead.stage=="won",CRMLead.currency==currency,
            CRMLead.actual_closed_at>=datetime.combine(first,time.min,timezone.utc),
            CRMLead.actual_closed_at<datetime.combine(last+timedelta(days=1),time.min,timezone.utc))
        actual_q=_scope(actual_q,m,CRMLead)
        if snap.rep_key=="unassigned":actual_q=actual_q.filter(CRMLead.assigned_to.is_(None))
        elif snap.assigned_to is not None:actual_q=actual_q.filter(CRMLead.assigned_to==snap.assigned_to)
        actual=Decimal(str(actual_q.scalar() or 0));variance=actual-snap.forecast_amount
        pct=(variance/snap.forecast_amount*100).quantize(Decimal("0.01")) if snap.forecast_amount else None
        output.append({"representative_id":snap.assigned_to,"currency":currency,"scenario":scenario,
            "forecast_amount":str(snap.forecast_amount),"actual_won_amount":str(actual),
            "variance_amount":str(variance),"variance_percent":str(pct) if pct is not None else None,
            "snapshot_at":snap.snapshot_at.isoformat(),"opportunity_count":snap.opportunity_count})
    return {"period_type":period_type,"period_start":first.isoformat(),"period_end":last.isoformat(),"rows":output}

@router.post("/campaigns/{campaign_id}/budget")
def set_campaign_budget(campaign_id:int,payload:dict,m=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    campaign=db.query(CRMCampaign).filter_by(id=campaign_id,organization_id=m.organization_id).first()
    if not campaign or not can_access_branch(m,campaign.branch_id):raise HTTPException(404,"Campaign not found")
    try:amount=Decimal(str(payload["budget_amount"]))
    except Exception:raise HTTPException(422,"budget_amount is required")
    if not amount.is_finite() or amount<0 or amount>Decimal("9999999999999999"):raise HTTPException(422,"Invalid campaign budget")
    campaign.budget_amount=amount
    currency=str(payload.get("currency","KES")).upper()
    if len(currency)!=3 or not currency.isalpha() or not currency.isupper():raise HTTPException(422,"Invalid budget currency")
    campaign.budget_currency=currency
    db.add(AuditEvent(organization_id=m.organization_id,actor_user_id=user.id,
        action="crm.campaign.budget.updated",resource_type="crm_campaign",resource_id=str(campaign.id)))
    db.commit()
    return {"campaign_id":campaign.id,"budget_amount":str(amount),"budget_currency":campaign.budget_currency}

@router.post("/campaigns/{campaign_id}/attributions",status_code=201)
def create_attribution(campaign_id:int,payload:dict,m=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    campaign=db.query(CRMCampaign).filter_by(id=campaign_id,organization_id=m.organization_id).first()
    if not campaign or not can_access_branch(m,campaign.branch_id):raise HTTPException(404,"Campaign not found")
    try:
        contact_id=int(payload["contact_id"]);lead_id=int(payload["lead_id"]) if payload.get("lead_id") else None
        order_id=int(payload["sales_order_id"]) if payload.get("sales_order_id") else None
        event=str(payload["event_type"]);amount=Decimal(str(payload.get("revenue_amount",0)))
        currency=str(payload.get("currency","KES")).upper();key=str(payload["idempotency_key"]).strip()
        occurred=datetime.fromisoformat(str(payload.get("occurred_at") or datetime.now(timezone.utc).isoformat()).replace("Z","+00:00"))
    except Exception:raise HTTPException(422,"Invalid attribution payload")
    allowed={"lead_created","qualified","quote_accepted","sales_order_confirmed","order_won","invoice_paid"}
    if event not in allowed or not amount.is_finite() or amount<0 or len(key)<8 or len(key)>100 or occurred.tzinfo is None:
        raise HTTPException(422,"Invalid attribution event, amount, idempotency key or timestamp")
    if len(currency)!=3 or not currency.isalpha() or not currency.isupper():raise HTTPException(422,"Invalid currency")
    contact=db.query(CRMContact).filter_by(id=contact_id,organization_id=m.organization_id).first()
    if not contact or not can_access_branch(m,contact.branch_id):raise HTTPException(404,"Contact not found")
    lead=None
    if lead_id:
        lead=db.query(CRMLead).filter_by(id=lead_id,organization_id=m.organization_id,contact_id=contact_id).first()
        if not lead or not can_access_branch(m,lead.branch_id):raise HTTPException(404,"Lead not found")
    if order_id:
        order=db.query(CRMSalesOrder).filter_by(id=order_id,organization_id=m.organization_id,contact_id=contact_id).first()
        if not order or (lead_id and order.lead_id!=lead_id) or not can_access_branch(m,order.branch_id):
            raise HTTPException(404,"Sales order not found")
    elif event in {"sales_order_confirmed","order_won","invoice_paid"}:raise HTTPException(422,"Sales-order and invoice events require a sales order")
    existing=db.query(CRMCampaignAttribution).filter_by(organization_id=m.organization_id,idempotency_key=key).first()
    if existing:return {"id":existing.id,"duplicate":True}
    row=CRMCampaignAttribution(organization_id=m.organization_id,campaign_id=campaign.id,contact_id=contact_id,
        lead_id=lead_id,sales_order_id=order_id,event_type=event,revenue_amount=amount,currency=currency,
        idempotency_key=key,occurred_at=occurred.astimezone(timezone.utc),created_by=user.id)
    db.add(row);db.add(AuditEvent(organization_id=m.organization_id,actor_user_id=user.id,
        action="crm.campaign.attribution.created",resource_type="crm_campaign_attribution",
        detail="campaign:%s;event:%s;currency:%s"%(campaign.id,event,currency)))
    try:db.commit()
    except IntegrityError:
        db.rollback()
        existing=db.query(CRMCampaignAttribution).filter_by(organization_id=m.organization_id,idempotency_key=key).first()
        if existing:return {"id":existing.id,"duplicate":True}
        raise HTTPException(409,"Attribution conflict")
    db.refresh(row);return {"id":row.id,"duplicate":False}

@router.get("/campaigns/roi")
def campaign_roi(campaign_id:int|None=None,m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"read");q=db.query(CRMCampaign).filter_by(organization_id=m.organization_id)
    allowed=branch_scope_ids(m)
    if allowed is not None:q=q.filter(CRMCampaign.branch_id.in_(allowed))
    if campaign_id is not None:q=q.filter(CRMCampaign.id==campaign_id)
    result=[]
    for campaign in q.order_by(CRMCampaign.created_at.desc()).limit(200).all():
        events=db.query(CRMCampaignAttribution).filter_by(
            organization_id=m.organization_id,campaign_id=campaign.id).filter(
            CRMCampaignAttribution.event_type.in_(["order_won","invoice_paid"])).order_by(
            CRMCampaignAttribution.occurred_at.desc(),CRMCampaignAttribution.id.desc()).all()
        # Sum all idempotent payment events; use order-won estimate only if no payment exists.
        orders={}
        for event in events:
            key=event.sales_order_id or ("event",event.id)
            orders.setdefault(key,[]).append(event)
        totals={}
        for group in orders.values():
            payments=[event for event in group if event.event_type=="invoice_paid"]
            selected=payments if payments else [next((event for event in group if event.event_type=="order_won"),group[0])]
            for event in selected:
                gross,count=totals.get(event.currency,(Decimal("0"),0))
                totals[event.currency]=(gross+Decimal(str(event.revenue_amount)),count+(1 if event is selected[0] else 0))
        revenue=[]
        for currency,(gross,count) in totals.items():
            spend=Decimal(str(campaign.budget_amount or 0))
            roi=((gross-spend)/spend*100).quantize(Decimal("0.01")) if spend and currency==campaign.budget_currency else None
            revenue.append({"currency":currency,"attributed_revenue":str(gross),"conversions":count,
                "campaign_cost":str(spend) if currency==campaign.budget_currency else None,
                "budget_currency":campaign.budget_currency,"roi_percent":str(roi) if roi is not None else None})
        funnel=db.query(CRMCampaignAttribution.event_type,func.count(CRMCampaignAttribution.id)).filter_by(
            organization_id=m.organization_id,campaign_id=campaign.id).group_by(CRMCampaignAttribution.event_type).all()
        result.append({"campaign_id":campaign.id,"name":campaign.name,"status":campaign.status,
            "budget_amount":str(campaign.budget_amount or 0),"budget_currency":campaign.budget_currency,
            "funnel":{event_type:count for event_type,count in funnel},"revenue":revenue})
    return {"campaigns":result,"roi_note":"Explicit attribution only; ROI is not proof of causation."}

@router.post("/scheduler/heartbeat")
def scheduler_heartbeat(payload:dict,m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"manage");name=str(payload.get("worker_name","crm-scheduler")).strip()
    if not name or len(name)>80:raise HTTPException(422,"Invalid worker name")
    row=db.query(CRMWorkerHeartbeat).filter_by(organization_id=m.organization_id,worker_name=name).first()
    if not row:row=CRMWorkerHeartbeat(organization_id=m.organization_id,worker_name=name);db.add(row)
    try:processed=int(payload.get("processed",0))
    except Exception:raise HTTPException(422,"processed must be an integer")
    row.last_seen_at=datetime.now(timezone.utc);row.last_processed=max(0,min(processed,10000))
    row.last_error=str(payload.get("error",""))[:500]
    db.commit();return {"worker_name":name,"last_seen_at":row.last_seen_at.isoformat()}

@router.get("/scheduler/health")
def scheduler_health(m=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(m,"read");now=datetime.now(timezone.utc)
    heartbeat=db.query(CRMWorkerHeartbeat).filter_by(organization_id=m.organization_id).order_by(
        CRMWorkerHeartbeat.last_seen_at.desc()).first()
    due=db.query(func.count(CRMCampaignSchedule.id)).filter_by(organization_id=m.organization_id,status="scheduled").filter(
        CRMCampaignSchedule.scheduled_at<=now).scalar() or 0
    failed=db.query(func.count(CRMCampaignSchedule.id)).filter_by(organization_id=m.organization_id,status="failed").scalar() or 0
    stale=db.query(func.count(CRMCampaignSchedule.id)).filter_by(organization_id=m.organization_id,status="running").filter(
        CRMCampaignSchedule.claimed_at<now-timedelta(minutes=10)).scalar() or 0
    age=(now-heartbeat.last_seen_at).total_seconds() if heartbeat else None
    status="healthy" if age is not None and age<120 and not heartbeat.last_error else ("stale" if age is not None else "unknown")
    return {"worker_status":status,"last_heartbeat_at":heartbeat.last_seen_at.isoformat() if heartbeat else None,
        "heartbeat_age_seconds":age,"last_processed":heartbeat.last_processed if heartbeat else 0,
        "last_error":heartbeat.last_error if heartbeat else "","due_schedules":due,"failed_schedules":failed,
        "stale_running_schedules":stale}

@router.get("/providers/health")
def provider_health(m=Depends(active_membership)):
    require_permission(m,"read")
    base=(settings.crm_public_base_url or "").strip()
    return {"providers":{
        "email":{"configured":bool(settings.integration_email_enabled and settings.email_host and settings.email_from)},
        "sms":{"configured":bool(settings.integration_sms_enabled and settings.sms_base_url and settings.sms_api_key)},
        "whatsapp":{"configured":bool(settings.integration_whatsapp_enabled and settings.whatsapp_base_url and settings.whatsapp_token and settings.whatsapp_phone_number_id)}},
        "delivery_callbacks":{"shared_secret_configured":bool(settings.crm_delivery_callback_secret)},
        "marketing_unsubscribe":{"public_https_url_configured":base.startswith("https://")},
        "note":"Configuration presence is not a successful provider health check or proof of message delivery."}

@router.post("/leads/{lead_id}/campaign/{campaign_id}")
def link_lead_campaign(lead_id:int,campaign_id:int,m=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(m,"manage")
    lead=db.query(CRMLead).filter_by(id=lead_id,organization_id=m.organization_id).first()
    campaign=db.query(CRMCampaign).filter_by(id=campaign_id,organization_id=m.organization_id).first()
    if not lead or not can_access_branch(m,lead.branch_id):raise HTTPException(404,"Lead not found")
    if not campaign or not can_access_branch(m,campaign.branch_id):raise HTTPException(404,"Campaign not found")
    if lead.branch_id and campaign.branch_id and lead.branch_id!=campaign.branch_id:
        raise HTTPException(422,"Lead and campaign must belong to the same branch")
    if lead.source_campaign_id not in (None,campaign.id):raise HTTPException(409,"Lead is already attributed to another campaign")
    lead.source_campaign_id=campaign.id
    db.add(AuditEvent(organization_id=m.organization_id,actor_user_id=user.id,
        action="crm.lead.campaign_linked",resource_type="crm_lead",resource_id=str(lead.id),
        detail="campaign:%s"%campaign.id))
    db.commit()
    return {"lead_id":lead.id,"campaign_id":campaign.id,"linked":True}
