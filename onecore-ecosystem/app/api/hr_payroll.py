"""HR and payroll APIs with tenant isolation, branch checks and maker-checker controls.

Statutory rates are never bundled as defaults. A rule set must cite current official
KRA, NSSF and SHA source evidence and be approved by a different organization member.
"""
from calendar import monthrange
import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.authorization import require_permission, branch_scope_ids, can_access_branch
from app.core.database import get_db
from app.core.hr_payroll_models import HREmployee, HRLeaveRequest, HRAttendanceRecord, PayrollRuleSet, PayrollRun, PayrollPayslip, PayrollAccountingMapping, PayrollAccountingLink, PayrollPaymentBatch, PayrollPaymentBatchItem, PayrollBankStatementLine
from app.core.models import AuditEvent, Branch, Organization, User, AccountingAccount, AccountingJournal, AccountingJournalLine, AccountingFiscalPeriod
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.services.accounting import validate_journal_lines

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


def require_hr_read(membership):
    allowed={"org_admin","branch_admin","manager","accountant","hr_admin","hr_manager","payroll_manager","payroll_approver","payroll_payment","payroll_accounting"}
    if (membership.role or "").lower() not in allowed:
        raise HTTPException(403,"HR and payroll data requires an authorized HR, finance or organization role")


def require_hr_write(membership):
    allowed={"org_admin","branch_admin","hr_admin","hr_manager"}
    if (membership.role or "").lower() not in allowed:
        raise HTTPException(403,"Employee and leave administration requires an authorized HR role")


def require_payroll_action(membership, action):
    allowed={
        "prepare":{"org_admin","payroll_manager"},
        "approve":{"org_admin","payroll_approver"},
        "pay":{"org_admin","payroll_payment"},
        "accounting":{"org_admin","payroll_accounting"},
    }
    if (membership.role or "").lower() not in allowed[action]:
        raise HTTPException(403,"Your role is not authorized for this payroll action")


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
    scheduled_minutes_per_day: int = Field(default=480, ge=60, le=1440)
    overtime_multiplier: Decimal | None = Field(default=None, ge=1, le=5, max_digits=5, decimal_places=2)

    @field_validator("recurring_allowances", "recurring_benefits")
    @classmethod
    def valid_components(cls, values):
        if len(values) > 30 or any(not k.strip() or len(k) > 80 or not dec(v).is_finite() or dec(v) < 0 or dec(v).quantize(CENT) != dec(v) for k, v in values.items()):
            raise ValueError("Pay components must have named, finite, non-negative amounts with at most two decimal places")
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
        if self.days > Decimal((self.end_date - self.start_date).days + 1):
            raise ValueError("Leave days cannot exceed the calendar days in the requested range")
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
            if not {"lower_bound", "upper_bound", "rate"}.issubset(band):
                raise ValueError("Each PAYE band requires lower_bound, upper_bound and rate")
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
            if not {"lower_bound", "upper_bound", "employee_rate", "employer_rate"}.issubset(tier):
                raise ValueError("Each NSSF tier requires lower_bound, upper_bound, employee_rate and employer_rate")
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
            try:
                date.fromisoformat(str(item["effective_date"]))
                date.fromisoformat(str(item["checked_on"]))
            except ValueError:
                raise ValueError("Statutory evidence dates must use YYYY-MM-DD")
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
            "recurring_benefits": x.recurring_benefits, "pension_contribution": str(x.pension_contribution), "scheduled_minutes_per_day": x.scheduled_minutes_per_day,
            "overtime_multiplier": str(x.overtime_multiplier) if x.overtime_multiplier is not None else None}


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


def _calculate(employee, rules, period_start, period_end, overtime_minutes=0, unpaid_leave_days=ZERO):
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
    unpaid_leave_days = dec(unpaid_leave_days)
    if unpaid_leave_days > Decimal(eligible_days):
        raise HTTPException(422, f"Unpaid leave exceeds eligible payroll days for employee {employee.employee_number}")
    unpaid_leave_deduction = rounded(dec(employee.base_salary) * unpaid_leave_days / Decimal(total_days))
    overtime_earnings = ZERO
    if overtime_minutes:
        if employee.overtime_multiplier is None:
            raise HTTPException(409, f"Configure an approved overtime multiplier for employee {employee.employee_number}")
        monthly_work_minutes = Decimal(26) * Decimal(employee.scheduled_minutes_per_day or 480)
        minute_rate = dec(employee.base_salary) / monthly_work_minutes
        overtime_earnings = rounded(minute_rate * Decimal(overtime_minutes) * dec(employee.overtime_multiplier))
    gross = rounded(prorated_salary - unpaid_leave_deduction + overtime_earnings + sum(allowances.values(), ZERO) + sum(benefits.values(), ZERO))
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
            "overtime_minutes": int(overtime_minutes), "overtime_earnings": str(overtime_earnings),
            "unpaid_leave_days": str(unpaid_leave_days), "unpaid_leave_deduction": str(unpaid_leave_deduction),
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
    require_hr_read(membership)
    q = db.query(HREmployee).filter_by(organization_id=membership.organization_id)
    q = scoped(q, HREmployee, membership)
    return [employee_out(x) for x in q.order_by(HREmployee.employee_number).limit(limit).all()]


@router.post("/hr/employees", status_code=201)
def create_employee(payload: EmployeeIn, membership=Depends(active_membership),
                    user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_hr_write(membership)
    branch_or_404(db, membership, payload.branch_id)
    row = HREmployee(organization_id=membership.organization_id, branch_id=payload.branch_id,
        employee_number=payload.employee_number, first_name=payload.first_name, last_name=payload.last_name,
        email=payload.email, phone=payload.phone, department=payload.department, job_title=payload.job_title,
        employment_type=payload.employment_type, hire_date=datetime.combine(payload.hire_date, time.min, tzinfo=timezone.utc),
        base_salary=payload.base_salary, currency=payload.currency,
        recurring_allowances={k: str(v) for k,v in payload.recurring_allowances.items()},
        recurring_benefits={k: str(v) for k,v in payload.recurring_benefits.items()},
        pension_contribution=payload.pension_contribution, scheduled_minutes_per_day=payload.scheduled_minutes_per_day,
        overtime_multiplier=payload.overtime_multiplier, created_by=user.id)
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
    require_hr_write(membership)
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
    require_hr_write(membership)
    employee = db.query(HREmployee).filter_by(id=employee_id, organization_id=membership.organization_id).first()
    if not employee or not can_access_branch(membership, employee.branch_id):
        raise HTTPException(404, "Employee not found")
    start_dt=datetime.combine(payload.start_date,time.min,tzinfo=timezone.utc)
    end_dt=datetime.combine(payload.end_date,time.max,tzinfo=timezone.utc)
    overlap=db.query(HRLeaveRequest).filter(HRLeaveRequest.organization_id==membership.organization_id,
        HRLeaveRequest.employee_id==employee.id,HRLeaveRequest.status.in_(("pending","approved")),
        HRLeaveRequest.start_date<=end_dt,HRLeaveRequest.end_date>=start_dt).first()
    if overlap: raise HTTPException(409,"This leave request overlaps an existing pending or approved request")
    row = HRLeaveRequest(organization_id=membership.organization_id, branch_id=employee.branch_id,
        employee_id=employee.id, leave_type=payload.leave_type,
        start_date=start_dt,
        end_date=end_dt,
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
    require_hr_read(membership)
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
    require_hr_write(membership)
    row = db.query(HRLeaveRequest).filter_by(id=request_id, organization_id=membership.organization_id).first()
    if not row or not can_access_branch(membership, row.branch_id): raise HTTPException(404, "Leave request not found")
    if row.status != "pending": raise HTTPException(409, "Leave request has already been decided")
    if payload.decision=="approved" and db.query(HRLeaveRequest).filter(HRLeaveRequest.organization_id==membership.organization_id,
        HRLeaveRequest.employee_id==row.employee_id,HRLeaveRequest.id!=row.id,HRLeaveRequest.status=="approved",
        HRLeaveRequest.start_date<=row.end_date,HRLeaveRequest.end_date>=row.start_date).first():
        raise HTTPException(409,"Another approved leave request overlaps this period")
    if row.requested_by == user.id: raise HTTPException(409, "A requester cannot approve their own leave request")
    row.status=payload.decision; row.decision_note=payload.note; row.decided_by=user.id; row.decided_at=datetime.now(timezone.utc)
    audit(db,user,membership.organization_id,"hr.leave."+payload.decision,"hr_leave_request",row.id,payload.note)
    db.commit()
    return {"id":row.id,"status":row.status,"decided_by":row.decided_by}


@router.get("/payroll/rule-sets")
def list_rule_sets(membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    require_hr_read(membership)
    rows=db.query(PayrollRuleSet).filter_by(organization_id=membership.organization_id).order_by(PayrollRuleSet.version.desc()).all()
    return [{"id":x.id,"version":x.version,"effective_from":x.effective_from.date().isoformat(),
        "effective_to":x.effective_to.date().isoformat() if x.effective_to else None,
        "currency":x.currency,"status":x.status,"source_evidence":x.source_evidence,
        "approved_by":x.approved_by,"approved_at":x.approved_at.isoformat() if x.approved_at else None} for x in rows]


@router.post("/payroll/rule-sets", status_code=201)
def create_rule_set(payload: RuleSetIn, membership=Depends(active_membership),
                    user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_payroll_action(membership,"prepare")
    db.query(Organization.id).filter_by(id=membership.organization_id).with_for_update().first()
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
    require_payroll_action(membership,"prepare")
    row=db.query(PayrollRuleSet).filter_by(id=rule_set_id,organization_id=membership.organization_id).first()
    if not row: raise HTTPException(404,"Payroll rule set not found")
    if row.status!="draft": raise HTTPException(409,"Only draft rule sets can be submitted")
    row.status="pending_approval"; row.submitted_by=user.id
    audit(db,user,membership.organization_id,"payroll.rules.submitted","payroll_rule_set",row.id)
    db.commit()
    return {"id":row.id,"status":row.status}


@router.post("/payroll/rule-sets/{rule_set_id}/approve")
def approve_rule_set(rule_set_id:int,membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_payroll_action(membership,"approve")
    db.query(Organization.id).filter_by(id=membership.organization_id).with_for_update().first()
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
    require_hr_read(membership)
    q=db.query(PayrollRun).filter_by(organization_id=membership.organization_id)
    q=scoped(q,PayrollRun,membership)
    rows=q.order_by(PayrollRun.id.desc()).limit(200).all()
    links=db.query(PayrollAccountingLink).filter(
        PayrollAccountingLink.organization_id==membership.organization_id,
        PayrollAccountingLink.payroll_run_id.in_([x.id for x in rows] or [-1])
    ).all()
    by_run={x.payroll_run_id:x for x in links}
    result=[]
    for row in rows:
        item=_run_out(row); link=by_run.get(row.id)
        item.update({"accounting_journal_id":link.journal_id if link else None,
                     "settlement_journal_id":link.settlement_journal_id if link else None,
                     "reversal_journal_id":link.reversal_journal_id if link else None})
        result.append(item)
    return result


@router.post("/payroll/runs",status_code=201)
def create_payroll_run(payload:PayrollRunIn,membership=Depends(active_membership),
                       user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_payroll_action(membership,"prepare")
    db.query(Organization.id).filter_by(id=membership.organization_id).with_for_update().first()
    branch_or_404(db,membership,payload.branch_id)
    if payload.branch_id is None and branch_scope_ids(membership) is not None:
        raise HTTPException(422,"Select a branch for payroll when your membership has a restricted branch scope")
    existing=db.query(PayrollRun).filter_by(organization_id=membership.organization_id,
        idempotency_key=payload.idempotency_key).first()
    if existing:
        if existing.created_by!=user.id: raise HTTPException(409,"Idempotency key already belongs to another payroll request")
        same_request=(existing.branch_id==payload.branch_id and existing.period_start.date()==payload.period_start and
            existing.period_end.date()==payload.period_end and
            sorted(x["employee_id"] for x in existing.calculation_snapshot.get("items",[]))==sorted(payload.employee_ids))
        if not same_request: raise HTTPException(409,"Idempotency key was already used with a different payroll request")
        return _run_out(existing)
    duplicate_period=db.query(PayrollRun).filter_by(organization_id=membership.organization_id,
        branch_id=payload.branch_id,period_start=datetime.combine(payload.period_start,time.min,tzinfo=timezone.utc),
        period_end=datetime.combine(payload.period_end,time.max,tzinfo=timezone.utc)).filter(PayrollRun.status!="cancelled").first()
    if duplicate_period: raise HTTPException(409,"A payroll run already exists for this branch and monthly period")
    start=datetime.combine(payload.period_start,time.min,tzinfo=timezone.utc)
    end=datetime.combine(payload.period_end,time.max,tzinfo=timezone.utc)
    rules=db.query(PayrollRuleSet).filter(PayrollRuleSet.organization_id==membership.organization_id,
        PayrollRuleSet.status=="active",PayrollRuleSet.effective_from<=start,
        ((PayrollRuleSet.effective_to.is_(None))|(PayrollRuleSet.effective_to>=end))).order_by(PayrollRuleSet.version.desc()).first()
    if not rules: raise HTTPException(409,"No approved statutory rule set covers the complete payroll period")
    q=db.query(HREmployee).filter(HREmployee.organization_id==membership.organization_id,
        HREmployee.id.in_(payload.employee_ids),
        or_(HREmployee.employment_status=="active",and_(HREmployee.employment_status=="terminated",HREmployee.termination_date>=start)),
        HREmployee.hire_date<=end,HREmployee.currency==rules.currency)
    if payload.branch_id is not None:q=q.filter(HREmployee.branch_id==payload.branch_id)
    employees=q.all()
    if len(employees)!=len(payload.employee_ids): raise HTTPException(404,"One or more active employees were not found in this tenant, branch or currency")
    if any(not can_access_branch(membership,x.branch_id) for x in employees): raise HTTPException(404,"Employee not found")
    snapshots=[]
    for employee in employees:
        attendance_rows = db.query(HRAttendanceRecord).filter(
            HRAttendanceRecord.organization_id == membership.organization_id,
            HRAttendanceRecord.employee_id == employee.id,
            HRAttendanceRecord.status == "approved",
            HRAttendanceRecord.work_date >= start,
            HRAttendanceRecord.work_date <= end,
        ).all()
        overtime_minutes = sum(x.overtime_minutes for x in attendance_rows)
        unpaid_rows = db.query(HRLeaveRequest).filter(
            HRLeaveRequest.organization_id == membership.organization_id,
            HRLeaveRequest.employee_id == employee.id,
            HRLeaveRequest.status == "approved",
            HRLeaveRequest.leave_type == "unpaid",
            HRLeaveRequest.start_date <= end,
            HRLeaveRequest.end_date >= start,
        ).all()
        unpaid_days = ZERO
        for leave in unpaid_rows:
            leave_start = leave.start_date.date()
            leave_end = leave.end_date.date()
            overlap_start = max(payload.period_start, leave_start)
            overlap_end = min(payload.period_end, leave_end)
            overlap_days = max(0, (overlap_end - overlap_start).days + 1)
            leave_calendar_days = (leave_end - leave_start).days + 1
            if overlap_days and leave_calendar_days:
                unpaid_days += dec(leave.days) * Decimal(overlap_days) / Decimal(leave_calendar_days)
        item = _calculate(employee, rules.rules, payload.period_start, payload.period_end,
                          overtime_minutes=overtime_minutes, unpaid_leave_days=unpaid_days)
        item["attendance_records_count"] = len(attendance_rows)
        item["rule_set_id"] = rules.id
        snapshots.append(item)
    gross=sum((dec(x["gross_pay"]) for x in snapshots),ZERO)
    deductions=sum((dec(x["total_deductions"]) for x in snapshots),ZERO)
    net=sum((dec(x["net_pay"]) for x in snapshots),ZERO)
    employer=sum((dec(x["gross_pay"])+dec(x["nssf_employer"])+dec(x["housing_levy_employer"]) for x in snapshots),ZERO)
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
    require_payroll_action(membership,"prepare")
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
    require_payroll_action(membership,"approve")
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
    require_payroll_action(membership,"pay")
    row=db.query(PayrollRun).filter_by(id=run_id,organization_id=membership.organization_id).with_for_update().first()
    if not row or not can_access_branch(membership,row.branch_id): raise HTTPException(404,"Payroll run not found")
    if row.status!="approved": raise HTTPException(409,"Only approved payroll can be marked paid")
    if db.query(PayrollPaymentBatchItem).filter_by(
        organization_id=membership.organization_id, payroll_run_id=row.id
    ).first():
        raise HTTPException(409, "Payroll run is reserved by a payment batch; settle or cancel that batch")
    if user.id in {row.created_by,row.submitted_by,row.approved_by}:
        raise HTTPException(409,"Payroll preparer, submitter and approver cannot authorize its payment")
    accounting_link=db.query(PayrollAccountingLink).filter_by(organization_id=membership.organization_id,payroll_run_id=row.id).with_for_update().first()
    if not accounting_link or accounting_link.reversal_journal_id:
        raise HTTPException(409,"Post the approved payroll to accounting before recording payment")
    if user.id==accounting_link.created_by:
        raise HTTPException(409,"The payroll accounting poster cannot authorize its payment")
    if accounting_link.settlement_journal_id:
        raise HTTPException(409,"Payroll settlement journal already exists")
    if dec(row.net_total)<=0:
        raise HTTPException(422,"Payroll with zero net pay cannot be marked paid")
    mapping_snapshot=accounting_link.mapping_snapshot or {}
    bank_account_id=mapping_snapshot.get("bank_account_id")
    net_payable_account_id=mapping_snapshot.get("net_payable_account_id")
    bank=db.query(AccountingAccount).filter_by(id=bank_account_id,
        organization_id=membership.organization_id,is_active=True,account_type="asset").first()
    payable=db.query(AccountingAccount).filter_by(id=net_payable_account_id,
        organization_id=membership.organization_id,is_active=True,account_type="liability").first()
    if not bank or not payable: raise HTTPException(409,"The payroll journal bank or payable account is no longer active")
    settlement_date=datetime.now(timezone.utc).date()
    _assert_accounting_date_open(db,membership.organization_id,settlement_date)
    settlement_lines=[
        {"account_id":net_payable_account_id,"description":"Settle net payroll payable",
         "debit":dec(row.net_total),"credit":ZERO,"branch_id":row.branch_id},
        {"account_id":bank_account_id,"description":"Payroll bank disbursement confirmation",
         "debit":ZERO,"credit":dec(row.net_total),"branch_id":row.branch_id},
    ]
    validate_journal_lines([type("Line",(),x)() for x in settlement_lines])
    journal=AccountingJournal(organization_id=membership.organization_id,branch_id=row.branch_id,
        journal_number="JRN-"+uuid.uuid4().hex[:16].upper(),reference=f"PAYROLL-PAYMENT-{row.id}",
        memo=f"Settlement for payroll run {row.id}; payment reference {payload.payment_reference}",
        status="posted",entry_date=datetime.combine(settlement_date,time.min,tzinfo=timezone.utc),
        created_by=user.id,posted_by=user.id,posted_at=datetime.now(timezone.utc))
    db.add(journal); db.flush()
    for line in settlement_lines:
        db.add(AccountingJournalLine(organization_id=membership.organization_id,journal_id=journal.id,
            account_id=line["account_id"],branch_id=line["branch_id"],description=line["description"],
            debit=line["debit"],credit=line["credit"]))
    accounting_link.settlement_journal_id=journal.id
    row.status="paid"; row.paid_by=user.id; row.paid_at=datetime.now(timezone.utc); row.payment_reference=payload.payment_reference
    audit(db,user,membership.organization_id,"payroll.run.marked_paid","payroll_run",row.id,
          f"External payment confirmed; settlement journal {journal.journal_number}; no transfer initiated by this API")
    db.commit()
    result=_run_out(row); result["settlement_journal_id"]=journal.id
    return result


@router.get("/payroll/runs/{run_id}/payslips")
def list_payslips(run_id:int,membership=Depends(active_membership),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    require_hr_read(membership)
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



class PayrollAccountingMappingIn(BaseModel):
    salary_expense_account_id: int = Field(gt=0)
    employer_contribution_expense_account_id: int = Field(gt=0)
    net_payable_account_id: int = Field(gt=0)
    paye_payable_account_id: int = Field(gt=0)
    nssf_payable_account_id: int = Field(gt=0)
    shif_payable_account_id: int = Field(gt=0)
    housing_levy_payable_account_id: int = Field(gt=0)
    pension_payable_account_id: int = Field(gt=0)
    bank_account_id: int = Field(gt=0)


class PayrollJournalReversalIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


def _payroll_mapping_out(row):
    return {name: getattr(row, name) for name in (
        "id", "salary_expense_account_id", "employer_contribution_expense_account_id",
        "net_payable_account_id", "paye_payable_account_id", "nssf_payable_account_id",
        "shif_payable_account_id", "housing_levy_payable_account_id", "pension_payable_account_id", "bank_account_id"
    )}


def _validate_payroll_mapping(db, organization_id, payload):
    expected = {
        "salary_expense_account_id": "expense",
        "employer_contribution_expense_account_id": "expense",
        "net_payable_account_id": "liability",
        "paye_payable_account_id": "liability",
        "nssf_payable_account_id": "liability",
        "shif_payable_account_id": "liability",
        "housing_levy_payable_account_id": "liability",
        "pension_payable_account_id": "liability",
        "bank_account_id": "asset",
    }
    ids = {getattr(payload, name) for name in expected}
    accounts = db.query(AccountingAccount).filter(
        AccountingAccount.organization_id == organization_id,
        AccountingAccount.is_active == True,
        AccountingAccount.id.in_(ids)
    ).all()
    by_id = {x.id: x for x in accounts}
    if set(by_id) != ids:
        raise HTTPException(404, "One or more mapped accounting accounts were not found in this organization")
    for field, account_type in expected.items():
        if by_id[getattr(payload, field)].account_type != account_type:
            raise HTTPException(422, f"{field} must map to an active {account_type} account")
    return by_id


@router.get("/payroll/accounting-mapping")
def get_payroll_accounting_mapping(membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    require_hr_read(membership)
    row=db.query(PayrollAccountingMapping).filter_by(organization_id=membership.organization_id).first()
    return _payroll_mapping_out(row) if row else None


@router.put("/payroll/accounting-mapping")
def put_payroll_accounting_mapping(payload: PayrollAccountingMappingIn,
                                   membership=Depends(active_membership),
                                   user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_payroll_action(membership, "accounting")
    _validate_payroll_mapping(db, membership.organization_id, payload)
    row=db.query(PayrollAccountingMapping).filter_by(organization_id=membership.organization_id).with_for_update().first()
    values=payload.model_dump()
    if row:
        for key,value in values.items(): setattr(row,key,value)
        row.updated_by=user.id
    else:
        row=PayrollAccountingMapping(organization_id=membership.organization_id,**values,
                                     created_by=user.id,updated_by=user.id)
        db.add(row)
    db.flush()
    audit(db,user,membership.organization_id,"payroll.accounting_mapping.saved","payroll_accounting_mapping",row.id)
    db.commit(); db.refresh(row)
    return _payroll_mapping_out(row)


def _assert_accounting_date_open(db, organization_id, entry_date):
    start=datetime.combine(entry_date,time.min,tzinfo=timezone.utc)
    end=datetime.combine(entry_date,time.max,tzinfo=timezone.utc)
    closed=db.query(AccountingFiscalPeriod).filter(
        AccountingFiscalPeriod.organization_id==organization_id,
        AccountingFiscalPeriod.status=="closed",
        AccountingFiscalPeriod.start_date<=end,
        AccountingFiscalPeriod.end_date>=start
    ).first()
    if closed:
        raise HTTPException(409,"The payroll accounting date falls inside a closed fiscal period")


def _append_journal_line(lines, account_id, description, debit=ZERO, credit=ZERO, branch_id=None):
    debit,credit=rounded(debit),rounded(credit)
    if debit==ZERO and credit==ZERO:
        return
    lines.append({"account_id":account_id,"description":description,
                  "debit":debit,"credit":credit,"branch_id":branch_id})


@router.post("/payroll/runs/{run_id}/post-to-accounting", status_code=201)
def post_payroll_to_accounting(run_id:int,membership=Depends(active_membership),
                               user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_payroll_action(membership,"accounting")
    run=db.query(PayrollRun).filter_by(id=run_id,organization_id=membership.organization_id).with_for_update().first()
    if not run or not can_access_branch(membership,run.branch_id):
        raise HTTPException(404,"Payroll run not found")
    if user.id in {run.created_by,run.submitted_by,run.approved_by}:
        raise HTTPException(409,"Payroll preparer, submitter and approver cannot post its accounting journal")
    if run.status!="approved":
        raise HTTPException(409,"Only an approved, unpaid payroll run can be posted to accounting")
    existing=db.query(PayrollAccountingLink).filter_by(
        organization_id=membership.organization_id,payroll_run_id=run.id).first()
    if existing:
        if existing.reversal_journal_id:
            raise HTTPException(409,"The payroll journal was reversed and cannot be posted again")
        return {"payroll_run_id":run.id,"journal_id":existing.journal_id,"status":"already_posted"}
    mapping=db.query(PayrollAccountingMapping).filter_by(organization_id=membership.organization_id).first()
    if not mapping:
        raise HTTPException(409,"Configure payroll accounting mappings before posting payroll")
    _validate_payroll_mapping(db,membership.organization_id,mapping)
    payslips=db.query(PayrollPayslip).filter_by(
        organization_id=membership.organization_id,payroll_run_id=run.id).all()
    if len(payslips)!=run.employee_count or not payslips:
        raise HTTPException(409,"Payroll payslip snapshots are incomplete")
    _assert_accounting_date_open(db,membership.organization_id,run.period_end.date())
    nssf_employee=sum((dec(x.nssf_employee) for x in payslips),ZERO)
    nssf_employer=sum((dec(x.nssf_employer) for x in payslips),ZERO)
    paye=sum((dec(x.paye) for x in payslips),ZERO)
    shif=sum((dec(x.shif_employee) for x in payslips),ZERO)
    housing_employee=sum((dec(x.housing_levy_employee) for x in payslips),ZERO)
    housing_employer=sum((dec(x.housing_levy_employer) for x in payslips),ZERO)
    pension=sum((dec(x.pension_employee) for x in payslips),ZERO)
    employer_contributions=rounded(nssf_employer+housing_employer)
    lines=[]
    _append_journal_line(lines,mapping.salary_expense_account_id,"Payroll gross earnings",debit=run.gross_total,branch_id=run.branch_id)
    _append_journal_line(lines,mapping.employer_contribution_expense_account_id,"Employer statutory contributions",debit=employer_contributions,branch_id=run.branch_id)
    _append_journal_line(lines,mapping.net_payable_account_id,"Net payroll payable",credit=run.net_total,branch_id=run.branch_id)
    _append_journal_line(lines,mapping.paye_payable_account_id,"PAYE payable",credit=paye,branch_id=run.branch_id)
    _append_journal_line(lines,mapping.nssf_payable_account_id,"Employee and employer NSSF payable",credit=nssf_employee+nssf_employer,branch_id=run.branch_id)
    _append_journal_line(lines,mapping.shif_payable_account_id,"SHIF payable",credit=shif,branch_id=run.branch_id)
    _append_journal_line(lines,mapping.housing_levy_payable_account_id,"Employee and employer Housing Levy payable",credit=housing_employee+housing_employer,branch_id=run.branch_id)
    _append_journal_line(lines,mapping.pension_payable_account_id,"Employee pension payable",credit=pension,branch_id=run.branch_id)
    validate_journal_lines([type("Line",(),x)() for x in lines])
    journal=AccountingJournal(organization_id=membership.organization_id,branch_id=run.branch_id,
        journal_number="JRN-"+uuid.uuid4().hex[:16].upper(),reference=f"PAYROLL-RUN-{run.id}",
        memo=f"Payroll accrual for {run.period_start.date().isoformat()} to {run.period_end.date().isoformat()}",
        status="posted",entry_date=datetime.combine(run.period_end.date(),time.min,tzinfo=timezone.utc),
        created_by=user.id,posted_by=user.id,posted_at=datetime.now(timezone.utc))
    db.add(journal); db.flush()
    for line in lines:
        db.add(AccountingJournalLine(organization_id=membership.organization_id,journal_id=journal.id,
            account_id=line["account_id"],branch_id=line["branch_id"],description=line["description"],
            debit=line["debit"],credit=line["credit"]))
    link=PayrollAccountingLink(organization_id=membership.organization_id,payroll_run_id=run.id,
        journal_id=journal.id,mapping_snapshot={name:getattr(mapping,name) for name in (
            "salary_expense_account_id","employer_contribution_expense_account_id","net_payable_account_id",
            "paye_payable_account_id","nssf_payable_account_id","shif_payable_account_id",
            "housing_levy_payable_account_id","pension_payable_account_id","bank_account_id")},
        created_by=user.id)
    db.add(link)
    audit(db,user,membership.organization_id,"payroll.run.posted_to_accounting","payroll_run",run.id,
          f"Accounting journal {journal.journal_number}")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,"Payroll accounting journal was posted concurrently")
    return {"payroll_run_id":run.id,"journal_id":journal.id,"journal_number":journal.journal_number,
            "status":"posted","debits":str(run.gross_total+employer_contributions),
            "credits":str(run.gross_total+employer_contributions)}


@router.post("/payroll/runs/{run_id}/reverse-accounting-journal")
def reverse_payroll_accounting_journal(run_id:int,payload:PayrollJournalReversalIn,
                                       membership=Depends(active_membership),
                                       user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_payroll_action(membership,"accounting")
    run=db.query(PayrollRun).filter_by(id=run_id,organization_id=membership.organization_id).with_for_update().first()
    if not run or not can_access_branch(membership,run.branch_id):
        raise HTTPException(404,"Payroll run not found")
    if run.status!="approved":
        raise HTTPException(409,"Only approved and unpaid payroll journals can be reversed")
    if db.query(PayrollPaymentBatchItem).filter_by(
        organization_id=membership.organization_id, payroll_run_id=run.id
    ).first():
        raise HTTPException(409,"Cancel the unprocessed payment batch before reversing its payroll journal")
    link=db.query(PayrollAccountingLink).filter_by(
        organization_id=membership.organization_id,payroll_run_id=run.id).with_for_update().first()
    if not link: raise HTTPException(404,"Payroll accounting journal not found")
    if link.reversal_journal_id: raise HTTPException(409,"Payroll accounting journal has already been reversed")
    original=db.query(AccountingJournal).filter_by(
        id=link.journal_id,organization_id=membership.organization_id,status="posted").first()
    if not original: raise HTTPException(409,"Original posted payroll journal is unavailable")
    original_lines=db.query(AccountingJournalLine).filter_by(
        organization_id=membership.organization_id,journal_id=original.id).all()
    if not original_lines: raise HTTPException(409,"Original payroll journal has no lines")
    reversal_date=datetime.now(timezone.utc).date()
    _assert_accounting_date_open(db,membership.organization_id,reversal_date)
    reversal_lines=[{"account_id":x.account_id,"description":"Reversal: "+x.description,
                     "debit":dec(x.credit),"credit":dec(x.debit),"branch_id":x.branch_id}
                    for x in original_lines]
    validate_journal_lines([type("Line",(),x)() for x in reversal_lines])
    journal=AccountingJournal(organization_id=membership.organization_id,branch_id=run.branch_id,
        journal_number="JRN-"+uuid.uuid4().hex[:16].upper(),reference=f"PAYROLL-REV-{run.id}",
        memo="Reversal of payroll journal for run "+str(run.id)+": "+payload.reason,
        status="posted",entry_date=datetime.combine(reversal_date,time.min,tzinfo=timezone.utc),
        created_by=user.id,posted_by=user.id,posted_at=datetime.now(timezone.utc))
    db.add(journal); db.flush()
    for line in reversal_lines:
        db.add(AccountingJournalLine(organization_id=membership.organization_id,journal_id=journal.id,
            account_id=line["account_id"],branch_id=line["branch_id"],description=line["description"],
            debit=line["debit"],credit=line["credit"]))
    link.reversal_journal_id=journal.id; link.reversed_by=user.id
    link.reversed_at=datetime.now(timezone.utc); link.reversal_reason=payload.reason
    run.status="cancelled"
    audit(db,user,membership.organization_id,"payroll.run.accounting_journal_reversed","payroll_run",run.id,
          f"Reversal journal {journal.journal_number}: {payload.reason}")
    db.commit()
    return {"payroll_run_id":run.id,"original_journal_id":original.id,
            "reversal_journal_id":journal.id,"status":"reversed"}


class AttendanceIn(BaseModel):
    employee_id: int = Field(gt=0)
    work_date: date
    clock_in: datetime
    clock_out: datetime
    break_minutes: int = Field(default=0, ge=0, le=720)
    scheduled_minutes: int = Field(default=480, gt=0, le=1440)
    idempotency_key: str = Field(min_length=8, max_length=100)
    @model_validator(mode="after")
    def validate_shift(self):
        if self.clock_in.tzinfo is None or self.clock_out.tzinfo is None:
            raise ValueError("Clock timestamps must include an explicit timezone")
        if self.clock_out <= self.clock_in:
            raise ValueError("Clock-out must be after clock-in")
        if self.work_date != self.clock_in.date() or self.work_date != self.clock_out.date():
            raise ValueError("Attendance clock timestamps must fall on the work date")
        elapsed = int((self.clock_out - self.clock_in).total_seconds() // 60)
        if self.break_minutes >= elapsed:
            raise ValueError("Break duration must be shorter than the shift")
        return self


class AttendanceDecisionIn(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    note: str = Field(default="", max_length=500)


def _same_instant(left, right):
    # SQLite drops timezone metadata on DateTime round-trips; normalize both
    # values to UTC before comparing an idempotent retry.
    if left.tzinfo is None:
        left = left.replace(tzinfo=timezone.utc)
    if right.tzinfo is None:
        right = right.replace(tzinfo=timezone.utc)
    return left.astimezone(timezone.utc) == right.astimezone(timezone.utc)


def attendance_out(row):
    return {
        "id": row.id, "employee_id": row.employee_id, "branch_id": row.branch_id,
        "work_date": row.work_date.date().isoformat(),
        "clock_in": row.clock_in.isoformat(), "clock_out": row.clock_out.isoformat(),
        "break_minutes": row.break_minutes, "scheduled_minutes": row.scheduled_minutes,
        "worked_minutes": row.worked_minutes, "overtime_minutes": row.overtime_minutes,
        "status": row.status, "submitted_by": row.submitted_by,
        "approved_by": row.approved_by, "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "decision_note": row.decision_note,
    }


@router.get("/hr/attendance")
def list_attendance(start_date: date | None = None, end_date: date | None = None,
                    status: str | None = None, employee_id: int | None = None,
                    membership=Depends(active_membership), db: Session = Depends(get_db)):
    require_permission(membership, "read")
    require_hr_read(membership)
    if start_date and end_date and end_date < start_date:
        raise HTTPException(422, "End date cannot precede start date")
    if status and status not in {"pending_approval", "approved", "rejected"}:
        raise HTTPException(422, "Invalid attendance status")
    q = db.query(HRAttendanceRecord).filter_by(organization_id=membership.organization_id)
    q = scoped(q, HRAttendanceRecord, membership)
    if start_date:
        q = q.filter(HRAttendanceRecord.work_date >= datetime.combine(start_date, time.min, tzinfo=timezone.utc))
    if end_date:
        q = q.filter(HRAttendanceRecord.work_date <= datetime.combine(end_date, time.max, tzinfo=timezone.utc))
    if status:
        q = q.filter(HRAttendanceRecord.status == status)
    if employee_id:
        q = q.filter(HRAttendanceRecord.employee_id == employee_id)
    return [attendance_out(x) for x in q.order_by(HRAttendanceRecord.work_date.desc()).limit(500).all()]


@router.post("/hr/attendance", status_code=201)
def submit_attendance(payload: AttendanceIn, membership=Depends(active_membership),
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_hr_write(membership)
    employee = db.query(HREmployee).filter_by(
        id=payload.employee_id, organization_id=membership.organization_id, employment_status="active"
    ).first()
    if not employee or not can_access_branch(membership, employee.branch_id):
        raise HTTPException(404, "Active employee not found")
    if payload.work_date < employee.hire_date.date() or (employee.termination_date and payload.work_date > employee.termination_date.date()):
        raise HTTPException(422, "Attendance date is outside the employee's employment period")
    existing = db.query(HRAttendanceRecord).filter_by(
        organization_id=membership.organization_id, idempotency_key=payload.idempotency_key
    ).first()
    if existing:
        same = (existing.employee_id == employee.id and existing.work_date.date() == payload.work_date
                and _same_instant(existing.clock_in, payload.clock_in) and _same_instant(existing.clock_out, payload.clock_out)
                and existing.break_minutes == payload.break_minutes
                and existing.scheduled_minutes == payload.scheduled_minutes)
        if not same or existing.submitted_by != user.id:
            raise HTTPException(409, "Attendance idempotency key belongs to a different submission")
        return attendance_out(existing)
    elapsed = int((payload.clock_out - payload.clock_in).total_seconds() // 60)
    worked = elapsed - payload.break_minutes
    row = HRAttendanceRecord(
        organization_id=membership.organization_id, branch_id=employee.branch_id,
        employee_id=employee.id,
        work_date=datetime.combine(payload.work_date, time.min, tzinfo=timezone.utc),
        clock_in=payload.clock_in.astimezone(timezone.utc), clock_out=payload.clock_out.astimezone(timezone.utc),
        break_minutes=payload.break_minutes, scheduled_minutes=payload.scheduled_minutes,
        worked_minutes=worked, overtime_minutes=max(0, worked - payload.scheduled_minutes),
        status="pending_approval", idempotency_key=payload.idempotency_key,
        submitted_by=user.id,
    )
    db.add(row)
    try:
        db.flush()
        audit(db, user, membership.organization_id, "hr.attendance.submitted", "hr_attendance", row.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Attendance already exists for this employee and work date")
    db.refresh(row)
    return attendance_out(row)


@router.post("/hr/attendance/{attendance_id}/decision")
def decide_attendance(attendance_id: int, payload: AttendanceDecisionIn,
                      membership=Depends(active_membership), user: User=Depends(current_user),
                      db: Session=Depends(get_db)):
    require_hr_write(membership)
    row = db.query(HRAttendanceRecord).filter_by(
        id=attendance_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not row or not can_access_branch(membership, row.branch_id):
        raise HTTPException(404, "Attendance record not found")
    if row.status != "pending_approval":
        raise HTTPException(409, "Attendance has already been decided")
    if row.submitted_by == user.id:
        raise HTTPException(409, "Attendance submitter cannot approve their own record")
    row.status = payload.decision
    row.decision_note = payload.note
    if payload.decision == "approved":
        row.approved_by = user.id
        row.approved_at = datetime.now(timezone.utc)
    audit(db, user, membership.organization_id, "hr.attendance." + payload.decision,
          "hr_attendance", row.id, payload.note)
    db.commit()
    return attendance_out(row)


# Payroll payment batches and bank reconciliation
class PayrollPaymentBatchIn(BaseModel):
    payroll_run_ids: list[int] = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=8, max_length=100)

    @field_validator("payroll_run_ids")
    @classmethod
    def unique_run_ids(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("Payroll run IDs must be unique")
        return values


class PayrollBatchSettlementItemIn(BaseModel):
    payroll_run_id: int = Field(gt=0)
    payment_reference: str = Field(min_length=3, max_length=120)


class PayrollBatchSettlementIn(BaseModel):
    items: list[PayrollBatchSettlementItemIn] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_settlements(self):
        ids = [x.payroll_run_id for x in self.items]
        refs = [x.payment_reference for x in self.items]
        if len(ids) != len(set(ids)) or len(refs) != len(set(refs)):
            raise ValueError("Settlement run IDs and payment references must be unique")
        return self


class PayrollStatementLineIn(BaseModel):
    transaction_date: date
    reference: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(default="KES", pattern="^[A-Z]{3}$")


class PayrollStatementImportIn(BaseModel):
    lines: list[PayrollStatementLineIn] = Field(min_length=1, max_length=1000)


class PayrollStatementResolveIn(BaseModel):
    batch_item_id: int = Field(gt=0)
    note: str = Field(min_length=5, max_length=500)


def _assert_payment_batch_branch_scope(db, batch, membership):
    items = db.query(PayrollPaymentBatchItem).filter_by(
        organization_id=membership.organization_id, batch_id=batch.id
    ).all()
    if not items or any(not can_access_branch(membership, item.branch_id) for item in items):
        raise HTTPException(404, "Payment batch not found")
    return items


def _payment_batch_out(db, batch):
    items = db.query(PayrollPaymentBatchItem).filter_by(
        organization_id=batch.organization_id, batch_id=batch.id
    ).order_by(PayrollPaymentBatchItem.id).all()
    return {
        "id": batch.id, "currency": batch.currency, "status": batch.status,
        "item_count": batch.item_count, "total_amount": str(batch.total_amount),
        "idempotency_key": batch.idempotency_key,
        "created_by": batch.created_by, "submitted_by": batch.submitted_by,
        "approved_by": batch.approved_by,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "submitted_at": batch.submitted_at.isoformat() if batch.submitted_at else None,
        "approved_at": batch.approved_at.isoformat() if batch.approved_at else None,
        "items": [{
            "id": x.id, "payroll_run_id": x.payroll_run_id, "branch_id": x.branch_id,
            "currency": x.currency, "amount": str(x.amount), "status": x.status,
            "payment_reference": x.payment_reference,
            "settlement_journal_id": x.settlement_journal_id,
            "paid_by": x.paid_by, "paid_at": x.paid_at.isoformat() if x.paid_at else None,
        } for x in items],
    }


@router.get("/payroll/payment-batches")
def list_payroll_payment_batches(membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    require_hr_read(membership)
    rows = db.query(PayrollPaymentBatch).filter_by(
        organization_id=membership.organization_id
    ).order_by(PayrollPaymentBatch.created_at.desc()).limit(200).all()
    visible = []
    for row in rows:
        items = db.query(PayrollPaymentBatchItem).filter_by(batch_id=row.id).all()
        if items and all(can_access_branch(membership, item.branch_id) for item in items):
            visible.append(_payment_batch_out(db, row))
    return visible


@router.post("/payroll/payment-batches", status_code=201)
def create_payroll_payment_batch(payload: PayrollPaymentBatchIn,
        membership=Depends(active_membership), user: User=Depends(current_user),
        db: Session=Depends(get_db)):
    require_payroll_action(membership, "prepare")
    existing = db.query(PayrollPaymentBatch).filter_by(
        organization_id=membership.organization_id, idempotency_key=payload.idempotency_key
    ).first()
    if existing:
        existing_ids = [x.payroll_run_id for x in db.query(PayrollPaymentBatchItem).filter_by(batch_id=existing.id).all()]
        if set(existing_ids) != set(payload.payroll_run_ids) or len(existing_ids) != len(payload.payroll_run_ids):
            raise HTTPException(409, "Payment batch idempotency key was already used for different payroll runs")
        _assert_payment_batch_branch_scope(db, existing, membership)
        return _payment_batch_out(db, existing)
    runs = db.query(PayrollRun).filter(
        PayrollRun.organization_id == membership.organization_id,
        PayrollRun.id.in_(payload.payroll_run_ids)
    ).with_for_update().all()
    if len(runs) != len(payload.payroll_run_ids):
        raise HTTPException(404, "One or more payroll runs were not found in this organization")
    currencies = {x.currency for x in runs}
    if len(currencies) != 1:
        raise HTTPException(422, "A payment batch can contain only one currency")
    for run in runs:
        if not can_access_branch(membership, run.branch_id):
            raise HTTPException(404, "One or more payroll runs were not found in your branch scope")
        if run.status != "approved" or dec(run.net_total) <= 0:
            raise HTTPException(409, "Only approved payroll runs with a positive net total can enter a payment batch")
        link = db.query(PayrollAccountingLink).filter_by(
            organization_id=membership.organization_id, payroll_run_id=run.id
        ).first()
        if not link or link.reversal_journal_id or link.settlement_journal_id:
            raise HTTPException(409, "Every payroll run must have an unreversed accrual journal and no prior settlement")
        if db.query(PayrollPaymentBatchItem).filter(
            PayrollPaymentBatchItem.payroll_run_id == run.id,
            PayrollPaymentBatchItem.status != "cancelled"
        ).first():
            raise HTTPException(409, "A payroll run is already reserved by a payment batch")
    batch = PayrollPaymentBatch(
        organization_id=membership.organization_id, currency=next(iter(currencies)),
        status="draft", item_count=len(runs), total_amount=rounded(sum((dec(x.net_total) for x in runs), ZERO)),
        idempotency_key=payload.idempotency_key, created_by=user.id,
    )
    db.add(batch)
    try:
        db.flush()
        for run in runs:
            db.add(PayrollPaymentBatchItem(
                organization_id=membership.organization_id, batch_id=batch.id,
                payroll_run_id=run.id, branch_id=run.branch_id, currency=run.currency,
                amount=rounded(run.net_total), status="pending",
            ))
        audit(db, user, membership.organization_id, "payroll.payment_batch.created",
              "payroll_payment_batch", batch.id, f"{len(runs)} payroll runs; total {batch.total_amount} {batch.currency}")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "One or more payroll runs were concurrently reserved by another payment batch")
    db.refresh(batch)
    return _payment_batch_out(db, batch)


@router.post("/payroll/payment-batches/{batch_id}/cancel")
def cancel_payroll_payment_batch(batch_id: int, membership=Depends(active_membership),
        user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_payroll_action(membership, "prepare")
    batch = db.query(PayrollPaymentBatch).filter_by(
        id=batch_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not batch:
        raise HTTPException(404, "Payment batch not found")
    _assert_payment_batch_branch_scope(db, batch, membership)
    if user.id != batch.created_by and (membership.role or "").lower() != "org_admin":
        raise HTTPException(403, "Only the batch creator or organization administrator can cancel it")
    if batch.status not in {"draft", "pending_approval"}:
        raise HTTPException(409, "Only an unapproved batch can be cancelled")
    for item in db.query(PayrollPaymentBatchItem).filter_by(
        organization_id=membership.organization_id, batch_id=batch.id
    ).with_for_update().all():
        if item.status != "pending":
            raise HTTPException(409, "Only unpaid batch items can be released by cancellation")
        item.status = "cancelled"
    batch.status = "cancelled"
    audit(db, user, membership.organization_id, "payroll.payment_batch.cancelled",
          "payroll_payment_batch", batch.id, "Unprocessed batch cancelled; payroll runs released")
    db.commit()
    return _payment_batch_out(db, batch)


@router.post("/payroll/payment-batches/{batch_id}/submit")
def submit_payroll_payment_batch(batch_id: int, membership=Depends(active_membership),
        user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_payroll_action(membership, "prepare")
    batch = db.query(PayrollPaymentBatch).filter_by(
        id=batch_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not batch:
        raise HTTPException(404, "Payment batch not found")
    _assert_payment_batch_branch_scope(db, batch, membership)
    if batch.status != "draft":
        raise HTTPException(409, "Only draft payment batches can be submitted")
    batch.status = "pending_approval"
    batch.submitted_by = user.id
    batch.submitted_at = datetime.now(timezone.utc)
    audit(db, user, membership.organization_id, "payroll.payment_batch.submitted",
          "payroll_payment_batch", batch.id)
    db.commit()
    return _payment_batch_out(db, batch)


@router.post("/payroll/payment-batches/{batch_id}/approve")
def approve_payroll_payment_batch(batch_id: int, membership=Depends(active_membership),
        user: User=Depends(current_user), db: Session=Depends(get_db)):
    require_payroll_action(membership, "approve")
    batch = db.query(PayrollPaymentBatch).filter_by(
        id=batch_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not batch:
        raise HTTPException(404, "Payment batch not found")
    _assert_payment_batch_branch_scope(db, batch, membership)
    if batch.status != "pending_approval":
        raise HTTPException(409, "Only submitted payment batches can be approved")
    if user.id in {batch.created_by, batch.submitted_by}:
        raise HTTPException(409, "Payment batch creator or submitter cannot approve the batch")
    items = db.query(PayrollPaymentBatchItem).filter_by(
        organization_id=membership.organization_id, batch_id=batch.id
    ).all()
    if len(items) != batch.item_count or not items:
        raise HTTPException(409, "Payment batch items are incomplete")
    for item in items:
        run = db.query(PayrollRun).filter_by(
            id=item.payroll_run_id, organization_id=membership.organization_id
        ).with_for_update().first()
        link = db.query(PayrollAccountingLink).filter_by(
            organization_id=membership.organization_id, payroll_run_id=item.payroll_run_id
        ).first()
        if not run or run.status != "approved" or not link or link.reversal_journal_id or link.settlement_journal_id:
            raise HTTPException(409, "A payroll run changed after batch creation; refresh or rebuild the batch")
    batch.status = "approved"
    batch.approved_by = user.id
    batch.approved_at = datetime.now(timezone.utc)
    audit(db, user, membership.organization_id, "payroll.payment_batch.approved",
          "payroll_payment_batch", batch.id)
    db.commit()
    return _payment_batch_out(db, batch)


@router.post("/payroll/payment-batches/{batch_id}/settlements")
def settle_payroll_payment_batch(batch_id: int, payload: PayrollBatchSettlementIn,
        membership=Depends(active_membership), user: User=Depends(current_user),
        db: Session=Depends(get_db)):
    require_payroll_action(membership, "pay")
    batch = db.query(PayrollPaymentBatch).filter_by(
        id=batch_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not batch or batch.status not in {"approved", "partially_paid"}:
        raise HTTPException(409, "Only approved or partially paid batches can be settled")
    _assert_payment_batch_branch_scope(db, batch, membership)
    if user.id in {batch.created_by, batch.submitted_by, batch.approved_by}:
        raise HTTPException(409, "Batch creator, submitter and approver cannot authorize its payment")
    items_by_run = {x.payroll_run_id: x for x in db.query(PayrollPaymentBatchItem).filter_by(
        organization_id=membership.organization_id, batch_id=batch.id
    ).with_for_update().all()}
    mapping = db.query(PayrollAccountingMapping).filter_by(
        organization_id=membership.organization_id
    ).first()
    if not mapping:
        raise HTTPException(409, "Payroll accounting mapping is not configured")
    bank = db.query(AccountingAccount).filter_by(
        id=mapping.bank_account_id, organization_id=membership.organization_id,
        is_active=True, account_type="asset"
    ).first()
    payable = db.query(AccountingAccount).filter_by(
        id=mapping.net_payable_account_id, organization_id=membership.organization_id,
        is_active=True, account_type="liability"
    ).first()
    if not bank or not payable:
        raise HTTPException(409, "The mapped bank or net-payable account is no longer active")
    settled = []
    for requested in payload.items:
        item = items_by_run.get(requested.payroll_run_id)
        if not item:
            raise HTTPException(404, "A requested payroll run is not part of this batch")
        if item.status != "pending":
            raise HTTPException(409, "A payment batch item has already been settled")
        if db.query(PayrollPaymentBatchItem).filter(
            PayrollPaymentBatchItem.organization_id == membership.organization_id,
            PayrollPaymentBatchItem.payment_reference == requested.payment_reference,
            PayrollPaymentBatchItem.id != item.id
        ).first():
            raise HTTPException(409, "Payment reference is already used by another payroll item")
        run = db.query(PayrollRun).filter_by(
            id=item.payroll_run_id, organization_id=membership.organization_id
        ).with_for_update().first()
        link = db.query(PayrollAccountingLink).filter_by(
            organization_id=membership.organization_id, payroll_run_id=run.id
        ).with_for_update().first()
        if not run or run.status != "approved" or not link or link.reversal_journal_id or link.settlement_journal_id:
            raise HTTPException(409, "Payroll run is no longer eligible for settlement")
        if user.id == link.created_by:
            raise HTTPException(409, "The payroll accounting poster cannot authorize its settlement")
        settlement_date = datetime.now(timezone.utc).date()
        _assert_accounting_date_open(db, membership.organization_id, settlement_date)
        lines = [
            {"account_id": mapping.net_payable_account_id, "description": f"Settle payroll run {run.id} net payable",
             "debit": dec(item.amount), "credit": ZERO, "branch_id": run.branch_id},
            {"account_id": mapping.bank_account_id, "description": f"Payroll bank payment {requested.payment_reference}",
             "debit": ZERO, "credit": dec(item.amount), "branch_id": run.branch_id},
        ]
        validate_journal_lines([type("Line", (), x)() for x in lines])
        journal = AccountingJournal(
            organization_id=membership.organization_id, branch_id=run.branch_id,
            journal_number="JRN-" + uuid.uuid4().hex[:16].upper(),
            reference=f"PAYROLL-BATCH-{batch.id}-RUN-{run.id}",
            memo=f"Payroll batch {batch.id} settlement; external payment reference {requested.payment_reference}",
            status="posted", entry_date=datetime.combine(settlement_date, time.min, tzinfo=timezone.utc),
            created_by=user.id, posted_by=user.id, posted_at=datetime.now(timezone.utc),
        )
        db.add(journal)
        db.flush()
        for line in lines:
            db.add(AccountingJournalLine(
                organization_id=membership.organization_id, journal_id=journal.id,
                account_id=line["account_id"], branch_id=line["branch_id"],
                description=line["description"], debit=line["debit"], credit=line["credit"],
            ))
        link.settlement_journal_id = journal.id
        run.status = "paid"
        run.paid_by = user.id
        run.paid_at = datetime.now(timezone.utc)
        run.payment_reference = requested.payment_reference
        item.payment_reference = requested.payment_reference
        item.status = "paid"
        item.settlement_journal_id = journal.id
        item.paid_by = user.id
        item.paid_at = datetime.now(timezone.utc)
        audit(db, user, membership.organization_id, "payroll.payment_batch.item_paid",
              "payroll_payment_batch_item", item.id,
              f"Run {run.id}; amount {item.amount} {item.currency}; external reference {requested.payment_reference}")
        settled.append({"payroll_run_id": run.id, "payment_reference": requested.payment_reference,
                        "settlement_journal_id": journal.id})
    remaining = sum(1 for x in items_by_run.values() if x.status == "pending")
    batch.status = "paid" if remaining == 0 else "partially_paid"
    audit(db, user, membership.organization_id, "payroll.payment_batch.settled",
          "payroll_payment_batch", batch.id, f"Settled {len(settled)} item(s); {remaining} remain")
    db.commit()
    return {"batch": _payment_batch_out(db, batch), "settled": settled}


@router.post("/payroll/bank-statements/import", status_code=201)
def import_payroll_bank_statement(payload: PayrollStatementImportIn,
        membership=Depends(active_membership), user: User=Depends(current_user),
        db: Session=Depends(get_db)):
    require_payroll_action(membership, "accounting")
    mapping = db.query(PayrollAccountingMapping).filter_by(
        organization_id=membership.organization_id
    ).first()
    if not mapping:
        raise HTTPException(409, "Configure payroll accounting mapping before importing bank statements")
    bank = db.query(AccountingAccount).filter_by(
        id=mapping.bank_account_id, organization_id=membership.organization_id,
        is_active=True, account_type="asset"
    ).first()
    if not bank:
        raise HTTPException(409, "Configured payroll bank account is not active")
    created = []
    for line in payload.lines:
        tx_date = datetime.combine(line.transaction_date, time.min, tzinfo=timezone.utc)
        row = PayrollBankStatementLine(
            organization_id=membership.organization_id, bank_account_id=bank.id,
            transaction_date=tx_date, reference=line.reference, amount=rounded(line.amount),
            currency=line.currency, status="unmatched", imported_by=user.id,
        )
        candidates = db.query(PayrollPaymentBatchItem).join(
            PayrollPaymentBatch, PayrollPaymentBatch.id == PayrollPaymentBatchItem.batch_id
        ).filter(
            PayrollPaymentBatchItem.organization_id == membership.organization_id,
            PayrollPaymentBatchItem.status == "paid",
            PayrollPaymentBatchItem.payment_reference == line.reference,
            PayrollPaymentBatchItem.amount == rounded(line.amount),
            PayrollPaymentBatch.currency == line.currency,
        ).all()
        if len(candidates) == 1:
            candidate = candidates[0]
            already_matched = db.query(PayrollBankStatementLine).filter_by(
                organization_id=membership.organization_id, batch_item_id=candidate.id
            ).first()
            if not already_matched:
                row.status = "matched"
                row.batch_item_id = candidate.id
                row.matched_by = user.id
                row.matched_at = datetime.now(timezone.utc)
                row.match_note = "Automatically matched by exact payment reference, amount and currency"
            else:
                row.status = "exception"
                row.match_note = "Payment item already has a matched bank statement line"
        elif len(candidates) > 1:
            row.status = "exception"
            row.match_note = "Multiple payroll payment items share this reference and amount"
        else:
            row.status = "unmatched"
            row.match_note = "No exact paid payroll item matched this bank line"
        db.add(row)
        created.append(row)
    try:
        db.flush()
        audit(db, user, membership.organization_id, "payroll.bank_statement.imported",
              "payroll_bank_statement", created[0].id,
              f"Imported {len(created)} line(s); matched {sum(1 for x in created if x.status == 'matched')}")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "The statement contains a duplicate line already imported for this bank account")
    return [{"id": x.id, "transaction_date": x.transaction_date.date().isoformat(),
             "reference": x.reference, "amount": str(x.amount), "currency": x.currency,
             "status": x.status, "batch_item_id": x.batch_item_id, "match_note": x.match_note}
            for x in created]


@router.get("/payroll/bank-statements")
def list_payroll_bank_statement_lines(status: str | None = None,
        membership=Depends(active_membership), db: Session=Depends(get_db)):
    require_payroll_action(membership, "accounting")
    if status and status not in {"matched", "unmatched", "exception"}:
        raise HTTPException(422, "Invalid statement reconciliation status")
    q = db.query(PayrollBankStatementLine).filter_by(organization_id=membership.organization_id)
    if status:
        q = q.filter(PayrollBankStatementLine.status == status)
    return [{"id": x.id, "transaction_date": x.transaction_date.date().isoformat(),
             "reference": x.reference, "amount": str(x.amount), "currency": x.currency,
             "status": x.status, "batch_item_id": x.batch_item_id, "match_note": x.match_note,
             "matched_by": x.matched_by, "matched_at": x.matched_at.isoformat() if x.matched_at else None}
            for x in q.order_by(PayrollBankStatementLine.transaction_date.desc()).limit(1000).all()]


@router.post("/payroll/bank-statements/{line_id}/resolve")
def resolve_payroll_bank_statement_line(line_id: int, payload: PayrollStatementResolveIn,
        membership=Depends(active_membership), user: User=Depends(current_user),
        db: Session=Depends(get_db)):
    require_payroll_action(membership, "accounting")
    line = db.query(PayrollBankStatementLine).filter_by(
        id=line_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not line:
        raise HTTPException(404, "Bank statement line not found")
    if line.status == "matched":
        raise HTTPException(409, "A reconciled bank statement line cannot be rematched")
    item = db.query(PayrollPaymentBatchItem).filter_by(
        id=payload.batch_item_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not item or item.status != "paid":
        raise HTTPException(404, "Paid payroll batch item not found")
    mapping = db.query(PayrollAccountingMapping).filter_by(
        organization_id=membership.organization_id
    ).first()
    if not mapping or line.bank_account_id != mapping.bank_account_id:
        raise HTTPException(409, "Statement line does not belong to the configured payroll bank account")
    if line.amount != item.amount or line.currency != item.currency:
        raise HTTPException(409, "Statement amount and currency must exactly match the payroll payment")
    if db.query(PayrollBankStatementLine).filter(
        PayrollBankStatementLine.organization_id == membership.organization_id,
        PayrollBankStatementLine.batch_item_id == item.id,
        PayrollBankStatementLine.id != line.id
    ).first():
        raise HTTPException(409, "Payroll payment item is already reconciled against another statement line")
    line.status = "matched"
    line.batch_item_id = item.id
    line.matched_by = user.id
    line.matched_at = datetime.now(timezone.utc)
    line.match_note = "Manually resolved by authorized finance reviewer: " + payload.note
    audit(db, user, membership.organization_id, "payroll.bank_statement.manually_matched",
          "payroll_bank_statement", line.id, line.match_note)
    db.commit()
    return {"id": line.id, "status": line.status, "batch_item_id": line.batch_item_id,
            "matched_by": line.matched_by, "matched_at": line.matched_at.isoformat(),
            "match_note": line.match_note}
