"""HR and payroll APIs with tenant isolation, branch checks and maker-checker controls.

Statutory rates are never bundled as defaults. A rule set must cite current official
KRA, NSSF and SHA source evidence and be approved by a different organization member.
"""
from calendar import monthrange
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.authorization import require_permission, branch_scope_ids, can_access_branch
from app.core.database import get_db
from app.core.hr_payroll_models import HREmployee, HRLeaveRequest, PayrollRuleSet, PayrollRun, PayrollPayslip
from app.core.models import AuditEvent, Branch, User
from app.core.security import current_user
from app.core.tenancy import active_membership

router = APIRouter(prefix="/api/v1", tags=["HR and Payroll"])
CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def dec(value):
    return Decimal(str(value or 0))


def rounded(value):
    return dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def audit(db, user, org_id, action, kind, row_id, detail=""):
    db.add(AuditEvent(actor_user_id=user.id, organization_id=org_id, action=action,
                      resource_type=kind, resource_id=str(row_id), detail=detail))


def scoped(query, model, membership):
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            return query.filter(model.id == -1)
        query = query.filter(model.branch_id.in_(allowed))
    return query


def branch_or_404(db, membership, branch_id):
    if not can_access_branch(membership, branch_id):
        raise HTTPException(404, "Branch not found")
    if branch_id is not None and not db.query(Branch).filter_by(
        id=branch_id, organization_id=membership.organization_id, is_active=True
    ).first():
        raise HTTPException(404, "Branch not found")


class EmployeeIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    branch_id: str | None = None
    employee_number: str = Field(min_length=1, max_length=60)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: str = Field(default="", max_length=320)
    phone: str = Field(default="", max_length=32)
    department: str = Field(default="", max_length=120)
    job_title: str = Field(default="", max_length=120)
    employment_type: str = Field(default="permanent", pattern="^(permanent|contract|casual|intern)$")
    hire_date: date
    base_salary: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(default="KES", pattern="^[A-Z]{3}$")
    recurring_allowances: dict[str, Decimal] = Field(default_factory=dict)
    recurring_benefits: dict[str, Decimal] = Field(default_factory=dict)
    pension_contribution: Decimal = Field(default=ZERO, ge=0, max_digits=18, decimal_places=2)

    @field_validator("recurring_allowances", "recurring_benefits")
    @classmethod
    def valid_components(cls, values):
        if len(values) > 30 or any(not k.strip() or len(k) > 80 or dec(v) < 0 for k, v in values.items()):
            raise ValueError("Pay components must have named, non-negative amounts")
        return values


class LeaveIn(BaseModel):
    leave_type: str = Field(pattern="^(annual|sick|maternity|paternity|compassionate|unpaid|other)$")
    start_date: date
    end_date: date
    days: Decimal = Field(gt=0, le=366, max_digits=7, decimal_places=2)
    reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def valid_range(self):
        if self.end_date < self.start_date:
            raise ValueError("Leave end date must not precede start date")
        return self


class LeaveDecisionIn(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    note: str = Field(default="", max_length=500)


class RuleSetIn(BaseModel):
    effective_from: date
    effective_to: date | None = None
    currency: str = Field(default="KES", pattern="^[A-Z]{3}$")
    paye_bands: list[dict] = Field(min_length=1, max_length=20)
    personal_relief: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    pension_tax_deductible_limit: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    nssf_tiers: list[dict] = Field(min_length=1, max_length=10)
    shif_rate: Decimal = Field(ge=0, le=1, decimal_places=6)
    housing_levy_employee_rate: Decimal = Field(ge=0, le=1, decimal_places=6)
    housing_levy_employer_rate: Decimal = Field(ge=0, le=1, decimal_places=6)
    source_evidence: list[dict] = Field(min_length=3, max_length=20)

    @model_validator(mode="after")
    def validate_rule_structure(self):
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("Effective end must not precede effective start")
        previous = Decimal("0")
        for index, band in enumerate(self.paye_bands):
            lower = dec(band.get("lower_bound"))
            upper = None if band.get("upper_bound") is None else dec(band["upper_bound"])
            rate = dec(band.get("rate"))
            if lower != previous or rate < 0 or rate > 1 or (upper is not None and upper <= lower):
                raise ValueError("PAYE bands must be contiguous, increasing and have rates between 0 and 1")
            if upper is None and index != len(self.paye_bands) - 1:
                raise ValueError("Only the final PAYE band may be open-ended")
            if upper is not None:
                previous = upper
        if self.paye_bands[-1].get("upper_bound") is not None:
            raise ValueError("The final PAYE band must be open-ended")
        previous = Decimal("0")
        for tier in self.nssf_tiers:
            lower, upper = dec(tier.get("lower_bound")), dec(tier.get("upper_bound"))
            if lower != previous or upper <= lower:
                raise ValueError("NSSF tiers must be contiguous and increasing")
            for key in ("employee_rate", "employer_rate"):
                if dec(tier.get(key)) < 0 or dec(tier.get(key)) > 1:
                    raise ValueError("NSSF contribution rates must be between 0 and 1")
            previous = upper
        authorities = set()
        for item in self.source_evidence:
            authority = str(item.get("authority", "")).upper()
            url = str(item.get("url", ""))
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            allowed = {"KRA": ("kra.go.ke",), "NSSF": ("nssf.or.ke",), "SHA": ("sha.go.ke",)}
            if authority not in allowed or parsed.scheme != "https" or not any(host == d or host.endswith("." + d) for d in allowed.get(authority, ())):
                raise ValueError("Evidence must link to official HTTPS KRA, NSSF or SHA sources")
            if not item.get("title") or not item.get("effective_date") or not item.get("checked_on"):
                raise ValueError("Each statutory source needs title, effective_date and checked_on")
            authorities.add(authority)
        if not {"KRA", "NSSF", "SHA"}.issubset(authorities):
            raise ValueError("Current official KRA, NSSF and SHA evidence is required")
        return self


class PayrollRunIn(BaseModel):
    branch_id: str | None = None
    period_start: date
    period_end: date
    employee_ids: list[int] = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=100)

    @model_validator(mode="after")
    def valid_period(self):
        if self.period_end < self.period_start:
            raise ValueError("Payroll period end must not precede start")
        if self.period_start.day != 1 or self.period_end != date(self.period_start.year, self.period_start.month, monthrange(self.period_start.year, self.period_start.month)[1]):
            raise ValueError("Monthly payroll periods must cover one complete calendar month")
        if len(self.employee_ids) != len(set(self.employee_ids)):
            raise ValueError("Employee IDs must be unique")
        return self


class PaidIn(BaseModel):
    payment_reference: str = Field(min_length=3, max_length=120)


def employee_out(x):
    return {"id": x.id, "termination_date": x.termination_date.date().isoformat() if x.termination_date else None, "branch_id": x.branch_id, "employee_number": x.employee_number,
            "first_name": x.first_name, "last_name": x.last_name, "email": x.email,
            "phone": x.phone, "department": x.department, "job_title": x.job_title,
            "employment_type": x.employment_type, "employment_status": x.employment_status,
            "hire_date": x.hire_date.date().isoformat(), "base_salary": str(x.base_salary),
            "currency": x.currency, "recurring_allowances": x.recurring_allowances,
            "recurring_benefits": x.recurring_benefits, "pension_contribution": str(x.pension_contribution)}


def _progressive_tax(taxable, bands):
    tax = ZERO
    for band in bands:
        lower = dec(band["lower_bound"])
        upper = None if band.get("upper_bound") is None else dec(band["upper_bound"])
        taxable_in_band = max(ZERO, taxable - lower)
        if upper is not None:
            taxable_in_band = min(taxable_in_band, upper - lower)
        tax += taxable_in_band * dec(band["rate"])
    return rounded(tax)


def _tiered_contribution(gross, tiers, rate_key):
    total = ZERO
    for tier in tiers:
        lower, upper = dec(tier["lower_bound"]), dec(tier["upper_bound"])
        pensionable = max(ZERO, min(gross, upper) - lower)
        total += pensionable * dec(tier[rate_key])
    return rounded(total)


def _calculate(employee, rules, period_start, period_end):
    total_days = (period_end - period_start).days + 1
    hired = employee.hire_date.date() if isinstance(employee.hire_date, datetime) else employee.hire_date
    terminated = employee.termination_date.date() if isinstance(employee.termination_date, datetime) else employee.termination_date
    eligible_start = max(period_start, hired)
    eligible_end = min(period_end, terminated or period_end)
    eligible_days = max(0, (eligible_end - eligible_start).days + 1)
    if eligible_days == 0:
        raise HTTPException(422, f"Employee {employee.employee_number} was not employed during this payroll period")
    factor = Decimal(eligible_days) / Decimal(total_days)
    allowances = {k: rounded(dec(v) * factor) for k, v in (employee.recurring_allowances or {}).items()}
    benefits = {k: rounded(dec(v) * factor) for k, v in (employee.recurring_benefits or {}).items()}
    prorated_salary = rounded(dec(employee.base_salary) * factor)
    gross = rounded(prorated_salary + sum(allowances.values(), ZERO) + sum(benefits.values(), ZERO))
    pension = rounded(dec(employee.pension_contribution) * factor)
    deductible_pension = min(pension, dec(rules["pension_tax_deductible_limit"]))
    taxable = max(ZERO, gross - deductible_pension)
    paye = max(ZERO, _progressive_tax(taxable, rules["paye_bands"]) - dec(rules["personal_relief"]))
    paye = rounded(paye)
    nssf_employee = _tiered_contribution(gross, rules["nssf_tiers"], "employee_rate")
    nssf_employer = _tiered_contribution(gross, rules["nssf_tiers"], "employer_rate")
    shif = rounded(gross * dec(rules["shif_rate"]))
    housing_employee = rounded(gross * dec(rules["housing_levy_employee_rate"]))
    housing_employer = rounded(gross * dec(rules["housing_levy_employer_rate"]))
    deductions = rounded(paye + nssf_employee + shif + housing_employee + pension)
    net = rounded(gross - deductions)
    if net < 0:
        raise HTTPException(422, f"Payroll deductions exceed gross pay for employee {employee.employee_number}")
    return {"employee_id": employee.id, "employee_number": employee.employee_number,
            "employee_name": (employee.first_name + " " + employee.last_name).strip(),
            "gross_pay": str(gross), "taxable_pay": str(taxable), "paye": str(paye),
            "proration_days": eligible_days, "period_days": total_days, "proration_factor": str(factor), "base_salary_prorated": str(prorated_salary),
            "nssf_employee": str(nssf_employee), "nssf_employer": str(nssf_employer),
            "shif_employee": str(shif), "housing_levy_employee": str(housing_employee),
            "housing_levy_employer": str(housing_employer), "pension_employee": str(pension),
            "total_deductions": str(deductions), "net_pay": str(net),
            "allowances": {k: str(v) for k, v in allowances.items()},
            "benefits": {k: str(v) for k, v in benefits.items()},
            "rule_set_id": None}


@router.get("/hr/employees")
def list_employees(membership=Depends(active_membership), db: Session=Depends(get_db),
                   limit: int=Query(100, ge=1, le=500)):
    require_permission(membership, "read")
    q = db.query(HREmployee).filter_by(organization_id=membership.organization_id)
    q = scoped(q, HREmployee, membership)
    return [employee_out(x) for x in q.order_by(HREmployee.employee_number).limit(limit).all()]


@router.post("/hr/employees", status_code=201)
def create_employee(payload: EmployeeIn, membership=Depends(active_membership),
                    user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "create")
    branch_or_404(db, membership, payload.branch_id)
    row = HREmployee(organization_id=membership.organization_id, branch_id=payload.branch_id,
        employee_number=payload.employee_number, first_name=payload.first_name, last_name=payload.last_name,
        email=payload.email, phone=payload.phone, department=payload.department, job_title=payload.job_title,
        employment_type=payload.employment_type, hire_date=datetime.combine(payload.hire_date, time.min, tzinfo=timezone.utc),
        base_salary=payload.base_salary, currency=payload.currency,
        recurring_allowances={k: str(v) for k,v in payload.recurring_allowances.items()},
        recurring_benefits={k: str(v) for k,v in payload.recurring_benefits.items()},
        pension_contribution=payload.pension_contribution, created_by=user.id)
    db.add(row)
    try:
        db.flush()
        audit(db, user, membership.organization_id, "hr.employee.created", "hr_employee", row.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Employee number already exists in this organization")
    db.refresh(row)
    return employee_out(row)


class EmploymentChangeIn(BaseModel):
    status: str = Field(pattern="^(active|terminated)$")
    termination_date: date | None = None
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def termination_date_required(self):
        if self.status == "terminated" and self.termination_date is None:
            raise ValueError("A termination date is required when terminating employment")
        if self.status != "terminated" and self.termination_date is not None:
            raise ValueError("Termination date is only valid for terminated employees")
        return self


@router.post("/hr/employees/{employee_id}/employment-status")
def change_employment_status(employee_id: int, payload: EmploymentChangeIn,
                             membership=Depends(active_membership), user: User=Depends(current_user),
                             db: Session=Depends(get_db)):
    require_permission(membership, "update")
    row=db.query(HREmployee).filter_by(id=employee_id, organization_id=membership.organization_id).first()
    if not row or not can_access_branch(membership,row.branch_id):
        raise HTTPException(404, "Employee not found")
    if row.employment_status == "terminated":
        raise HTTPException(409, "Terminated employment records cannot be changed")
    if payload.termination_date and payload.termination_date < row.hire_date.date():
        raise HTTPException(422, "Termination date cannot precede hire date")
    row.employment_status=payload.status
    row.termination_date=datetime.combine(payload.termination_date,time.max,tzinfo=timezone.utc) if payload.termination_date else None
    audit(db,user,membership.organization_id,"hr.employee.status_changed","hr_employee",row.id,payload.reason)
    db.commit()
    return employee_out(row)


@router.post("/hr/employees/{employee_id}/leave", status_code=201)
def request_leave(employee_id: int, payload: LeaveIn, membership=Depends(active_membership),
                  user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "create")
    employee = db.query(HREmployee).filter_by(id=employee_id, organization_id=membership.organization_id).first()
    if not employee or not can_access_branch(membership, employee.branch_id):
        raise HTTPException(404, "Employee not found")
    row = HRLeaveRequest(organization_id=membership.organization_id, branch_id=employee.branch_id,
        employee_id=employee.id, leave_type=payload.leave_type,
        start_date=datetime.combine(payload.start_date, time.min, tzinfo=timezone.utc),
        end_date=datetime.combine(payload.end_date, time.min, tzinfo=timezone.utc),
        days=payload.days, reason=payload.reason, requested_by=user.id)
    db.add(row); db.flush()
    audit(db, user, membership.organization_id, "hr.leave.requested", "hr_leave_request", row.id)
    db.commit(); db.refresh(row)
    return {"id": row.id, "employee_id": row.employee_id, "leave_type": row.leave_type,
            "start_date": payload.start_date.isoformat(), "end_date": payload.end_date.isoformat(),
            "days": str(row.days), "status": row.status}


@router.get("/hr/leave-requests")
def list_leave_requests(status: str | None=None, membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    q = db.query(HRLeaveRequest).filter_by(organization_id=membership.organization_id)
    q = scoped(q, HRLeaveRequest, membership)
    if status:
        if status not in {"pending", "approved", "rejected"}: raise HTTPException(422, "Invalid leave status")
        q = q.filter(HRLeaveRequest.status == status)
    return [{"id":x.id,"employee_id":x.employee_id,"leave_type":x.leave_type,
        "start_date":x.start_date.date().isoformat(),"end_date":x.end_date.date().isoformat(),
        "days":str(x.days),"reason":x.reason,"status":x.status,"decision_note":x.decision_note}
        for x in q.order_by(HRLeaveRequest.created_at.desc()).limit(500).all()]


@router.post("/hr/leave-requests/{request_id}/decision")
def decide_leave(request_id: int, payload: LeaveDecisionIn, membership=Depends(active_membership),
                 user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "update")
    row = db.query(HRLeaveRequest).filter_by(id=request_id, organization_id=membership.organization_id).first()
    if not row or not can_access_branch(membership, row.branch_id): raise HTTPException(404, "Leave request not found")
    if row.status != "pending": raise HTTPException(409, "Leave request has already been decided")
    if row.requested_by == user.id: raise HTTPException(409, "A requester cannot approve their own leave request")
    row.status=payload.decision; row.decision_note=payload.note; row.decided_by=user.id; row.decided_at=datetime.now(timezone.utc)
    audit(db,user,membership.organization_id,"hr.leave."+payload.decision,"hr_leave_request",row.id,payload.note)
    db.commit()
    return {"id":row.id,"status":row.status,"decided_by":row.decided_by}


@router.get("/payroll/rule-sets")
def list_rule_sets(membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    rows=db.query(PayrollRuleSet).filter_by(organization_id=membership.organization_id).order_by(PayrollRuleSet.version.desc()).all()
    return [{"id":x.id,"version":x.version,"effective_from":x.effective_from.date().isoformat(),
        "effective_to":x.effective_to.date().isoformat() if x.effective_to else None,
        "currency":x.currency,"status":x.status,"source_evidence":x.source_evidence,
        "approved_by":x.approved_by,"approved_at":x.approved_at.isoformat() if x.approved_at else None} for x in rows]


@router.post("/payroll/rule-sets", status_code=201)
def create_rule_set(payload: RuleSetIn, membership=Depends(active_membership),
                    user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    version=(db.query(PayrollRuleSet.version).filter_by(organization_id=membership.organization_id)
             .order_by(PayrollRuleSet.version.desc()).first())
    rules={"paye_bands":[{k:str(v) if v is not None else None for k,v in b.items()} for b in payload.paye_bands],
        "personal_relief":str(payload.personal_relief),"pension_tax_deductible_limit":str(payload.pension_tax_deductible_limit),
        "nssf_tiers":[{k:str(v) for k,v in t.items()} for t in payload.nssf_tiers],
        "shif_rate":str(payload.shif_rate),"housing_levy_employee_rate":str(payload.housing_levy_employee_rate),
        "housing_levy_employer_rate":str(payload.housing_levy_employer_rate)}
    row=PayrollRuleSet(organization_id=membership.organization_id,version=(version[0] if version else 0)+1,
        effective_from=datetime.combine(payload.effective_from,time.min,tzinfo=timezone.utc),
        effective_to=datetime.combine(payload.effective_to,time.max,tzinfo=timezone.utc) if payload.effective_to else None,
        currency=payload.currency,rules=rules,source_evidence=payload.source_evidence,status="draft",created_by=user.id)
    db.add(row); db.flush(); audit(db,user,membership.organization_id,"payroll.rules.created","payroll_rule_set",row.id)
    db.commit(); db.refresh(row)
    return {"id":row.id,"version":row.version,"status":row.status}


@router.post("/payroll/rule-sets/{rule_set_id}/submit")
def submit_rule_set(rule_set_id:int,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(PayrollRuleSet).filter_by(id=rule_set_id,organization_id=membership.organization_id).first()
    if not row: raise HTTPException(404,"Payroll rule set not found")
    if row.status!="draft": raise HTTPException(409,"Only draft rule sets can be submitted")
    row.status="pending_approval"; row.submitted_by=user.id
    audit(db,user,membership.organization_id,"payroll.rules.submitted","payroll_rule_set",row.id)
    db.commit()
    return {"id":row.id,"status":row.status}


@router.post("/payroll/rule-sets/{rule_set_id}/approve")
def approve_rule_set(rule_set_id:int,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(PayrollRuleSet).filter_by(id=rule_set_id,organization_id=membership.organization_id).with_for_update().first()
    if not row: raise HTTPException(404,"Payroll rule set not found")
    if row.status!="pending_approval": raise HTTPException(409,"Rule set is not awaiting approval")
    if row.submitted_by==user.id or row.created_by==user.id: raise HTTPException(409,"Rule-set creator and submitter cannot approve it")
    row_end = row.effective_to or datetime.max.replace(tzinfo=timezone.utc)
    if db.query(PayrollRuleSet).filter(PayrollRuleSet.organization_id==membership.organization_id,
        PayrollRuleSet.status=="active", PayrollRuleSet.effective_from<=row_end,
        or_(PayrollRuleSet.effective_to.is_(None), PayrollRuleSet.effective_to>=row.effective_from)).first():
        raise HTTPException(409,"An active statutory rule set already overlaps this effective date")
    row.status="active"; row.approved_by=user.id; row.approved_at=datetime.now(timezone.utc)
    audit(db,user,membership.organization_id,"payroll.rules.activated","payroll_rule_set",row.id,
          "Activation requires independent review of official source evidence")
    db.commit()
    return {"id":row.id,"version":row.version,"status":row.status,"approved_at":row.approved_at.isoformat()}


def _run_out(row):
    return {"id":row.id,"branch_id":row.branch_id,"rule_set_id":row.rule_set_id,
        "period_start":row.period_start.date().isoformat(),"period_end":row.period_end.date().isoformat(),
        "status":row.status,"currency":row.currency,"employee_count":row.employee_count,
        "gross_total":str(row.gross_total),"deductions_total":str(row.deductions_total),
        "net_total":str(row.net_total),"employer_cost_total":str(row.employer_cost_total),
        "payment_reference":row.payment_reference}


@router.get("/payroll/runs")
def list_payroll_runs(membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    q=db.query(PayrollRun).filter_by(organization_id=membership.organization_id)
    q=scoped(q,PayrollRun,membership)
    return [_run_out(x) for x in q.order_by(PayrollRun.id.desc()).limit(200).all()]


@router.post("/payroll/runs",status_code=201)
def create_payroll_run(payload:PayrollRunIn,membership=Depends(active_membership),
                       user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    branch_or_404(db,membership,payload.branch_id)
    if payload.branch_id is None and branch_scope_ids(membership) is not None:
        raise HTTPException(422,"Select a branch for payroll when your membership has a restricted branch scope")
    existing=db.query(PayrollRun).filter_by(organization_id=membership.organization_id,
        idempotency_key=payload.idempotency_key).first()
    if existing:
        if existing.created_by!=user.id: raise HTTPException(409,"Idempotency key already belongs to another payroll request")
        return _run_out(existing)
    start=datetime.combine(payload.period_start,time.min,tzinfo=timezone.utc)
    end=datetime.combine(payload.period_end,time.max,tzinfo=timezone.utc)
    rules=db.query(PayrollRuleSet).filter(PayrollRuleSet.organization_id==membership.organization_id,
        PayrollRuleSet.status=="active",PayrollRuleSet.effective_from<=start,
        ((PayrollRuleSet.effective_to.is_(None))|(PayrollRuleSet.effective_to>=end))).order_by(PayrollRuleSet.version.desc()).first()
    if not rules: raise HTTPException(409,"No approved statutory rule set covers the complete payroll period")
    if rules.currency!="KES" and rules.currency!="USD":
        raise HTTPException(409,"Unsupported payroll currency configuration")
    q=db.query(HREmployee).filter(HREmployee.organization_id==membership.organization_id,
        HREmployee.id.in_(payload.employee_ids),HREmployee.employment_status=="active",
        HREmployee.currency==rules.currency)
    if payload.branch_id is not None:q=q.filter(HREmployee.branch_id==payload.branch_id)
    employees=q.all()
    if len(employees)!=len(payload.employee_ids): raise HTTPException(404,"One or more active employees were not found in this tenant, branch or currency")
    if any(not can_access_branch(membership,x.branch_id) for x in employees): raise HTTPException(404,"Employee not found")
    snapshots=[]
    for employee in employees:
        item=_calculate(employee,rules.rules,payload.period_start,payload.period_end); item["rule_set_id"]=rules.id
        snapshots.append(item)
    gross=sum((dec(x["gross_pay"]) for x in snapshots),ZERO)
    deductions=sum((dec(x["total_deductions"]) for x in snapshots),ZERO)
    net=sum((dec(x["net_pay"]) for x in snapshots),ZERO)
    employer=sum((dec(x["nssf_employer"])+dec(x["housing_levy_employer"]) for x in snapshots),ZERO)
    row=PayrollRun(organization_id=membership.organization_id,branch_id=payload.branch_id,rule_set_id=rules.id,
        period_start=start,period_end=end,status="draft",currency=rules.currency,employee_count=len(snapshots),
        gross_total=rounded(gross),deductions_total=rounded(deductions),net_total=rounded(net),
        employer_cost_total=rounded(employer),idempotency_key=payload.idempotency_key,
        calculation_snapshot={"rule_set_id":rules.id,"rule_version":rules.version,"items":snapshots},
        created_by=user.id)
    db.add(row)
    try:
        db.flush()
        for item in snapshots:
            db.add(PayrollPayslip(organization_id=membership.organization_id,payroll_run_id=row.id,
                employee_id=item["employee_id"],employee_number=item["employee_number"],employee_name=item["employee_name"],
                currency=rules.currency,gross_pay=dec(item["gross_pay"]),taxable_pay=dec(item["taxable_pay"]),
                paye=dec(item["paye"]),nssf_employee=dec(item["nssf_employee"]),shif_employee=dec(item["shif_employee"]),
                housing_levy_employee=dec(item["housing_levy_employee"]),pension_employee=dec(item["pension_employee"]),
                total_deductions=dec(item["total_deductions"]),net_pay=dec(item["net_pay"]),
                nssf_employer=dec(item["nssf_employer"]),housing_levy_employer=dec(item["housing_levy_employer"]),
                snapshot=item))
        audit(db,user,membership.organization_id,"payroll.run.calculated","payroll_run",row.id,
              f"Rule set version {rules.version}; immutable calculation snapshot created")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,"Payroll idempotency conflict or duplicate employee payslip")
    db.refresh(row)
    return _run_out(row)


@router.post("/payroll/runs/{run_id}/submit")
def submit_payroll_run(run_id:int,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(PayrollRun).filter_by(id=run_id,organization_id=membership.organization_id).with_for_update().first()
    if not row or not can_access_branch(membership,row.branch_id): raise HTTPException(404,"Payroll run not found")
    if row.status!="draft": raise HTTPException(409,"Only draft payroll runs can be submitted")
    if row.created_by==user.id: pass
    row.status="pending_approval"; row.submitted_by=user.id
    audit(db,user,membership.organization_id,"payroll.run.submitted","payroll_run",row.id)
    db.commit()
    return _run_out(row)


@router.post("/payroll/runs/{run_id}/approve")
def approve_payroll_run(run_id:int,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(PayrollRun).filter_by(id=run_id,organization_id=membership.organization_id).with_for_update().first()
    if not row or not can_access_branch(membership,row.branch_id): raise HTTPException(404,"Payroll run not found")
    if row.status!="pending_approval": raise HTTPException(409,"Payroll run is not awaiting approval")
    if row.created_by==user.id or row.submitted_by==user.id: raise HTTPException(409,"Payroll preparer and submitter cannot approve the run")
    row.status="approved"; row.approved_by=user.id; row.approved_at=datetime.now(timezone.utc)
    audit(db,user,membership.organization_id,"payroll.run.approved","payroll_run",row.id,
          "Approved immutable payroll calculation snapshot")
    db.commit()
    return _run_out(row)


@router.post("/payroll/runs/{run_id}/mark-paid")
def mark_payroll_paid(run_id:int,payload:PaidIn,membership=Depends(active_membership),
                      user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(PayrollRun).filter_by(id=run_id,organization_id=membership.organization_id).with_for_update().first()
    if not row or not can_access_branch(membership,row.branch_id): raise HTTPException(404,"Payroll run not found")
    if row.status!="approved": raise HTTPException(409,"Only approved payroll can be marked paid")
    if row.approved_by==user.id: raise HTTPException(409,"The payroll approver cannot authorize its payment")
    row.status="paid"; row.paid_by=user.id; row.paid_at=datetime.now(timezone.utc); row.payment_reference=payload.payment_reference
    audit(db,user,membership.organization_id,"payroll.run.marked_paid","payroll_run",row.id,
          "Payment confirmation recorded; this endpoint does not initiate a bank or mobile-money transfer")
    db.commit()
    return _run_out(row)


@router.get("/payroll/runs/{run_id}/payslips")
def list_payslips(run_id:int,membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    run=db.query(PayrollRun).filter_by(id=run_id,organization_id=membership.organization_id).first()
    if not run or not can_access_branch(membership,run.branch_id): raise HTTPException(404,"Payroll run not found")
    rows=db.query(PayrollPayslip).filter_by(organization_id=membership.organization_id,payroll_run_id=run_id).order_by(PayrollPayslip.employee_number).all()
    return [{"id":x.id,"employee_id":x.employee_id,"employee_number":x.employee_number,
        "employee_name":x.employee_name,"currency":x.currency,"gross_pay":str(x.gross_pay),
        "taxable_pay":str(x.taxable_pay),"paye":str(x.paye),"nssf_employee":str(x.nssf_employee),
        "shif_employee":str(x.shif_employee),"housing_levy_employee":str(x.housing_levy_employee),
        "pension_employee":str(x.pension_employee),"total_deductions":str(x.total_deductions),
        "net_pay":str(x.net_pay),"nssf_employer":str(x.nssf_employer),
        "housing_levy_employer":str(x.housing_levy_employer),"snapshot":x.snapshot} for x in rows]
