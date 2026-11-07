"""Kenya payroll completion API.

Rules are effective-dated and copied into immutable calculation snapshots. Payment
providers are adapters only: no payment is considered successful without a verified
provider/bank reference.
"""
import csv
import hashlib
import hmac
import io
import json
import os
import uuid
from urllib.parse import urlparse
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Body, Header
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import Record, HRPayrollRun, HRPayrollLine, HRPayrollItem, HREmployee, AccountingAccount, AccountingJournal, AccountingJournalLine
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, branch_scope_ids, can_access_branch

router = APIRouter(prefix="/api/v1")
D = Decimal
CENT = D("0.01")
ZERO = D("0.00")
MODULE = "hr-payroll"


def money(v):
    return D(str(v or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def _record(db, org_id, kind, key=None):
    q = db.query(Record).filter_by(organization_id=org_id, module_key=MODULE, record_type=kind)
    if key is not None:
        q = q.filter(Record.data["key"].as_string() == str(key))
    return q


def _audit(db, org_id, user_id, action, kind, rid, detail=""):
    from app.core.models import AuditEvent
    db.add(AuditEvent(organization_id=org_id, actor_user_id=user_id, action=action,
                      resource_type=kind, resource_id=str(rid), detail=detail[:2000]))


def _require_manage(membership):
    require_permission(membership, "manage")


def _active_rule(db, org_id, on_date):
    rows = _record(db, org_id, "statutory_rule_set").all()
    active = [r for r in rows if r.data.get("status") == "active"
              and date.fromisoformat(r.data["effective_from"]) <= on_date
              and (not r.data.get("effective_to") or date.fromisoformat(r.data["effective_to"]) >= on_date)]
    if len(active) != 1:
        raise HTTPException(409, "Exactly one active Kenya statutory rule set must cover the payroll period")
    return active[0]


def _validate_authority_sources(sources):
    if not isinstance(sources, list) or not sources:
        raise HTTPException(422, "Authoritative source evidence is required")
    authorities=set()
    for source in sources:
        url=str(source.get("url",""))
        host=(urlparse(url).hostname or "").lower()
        authority=str(source.get("authority","")).lower()
        if not url.startswith("https://") or not any(host == d or host.endswith("."+d) for d in
                ("kra.go.ke","nssf.or.ke","kenyalaw.org","new.kenyalaw.org","sha.go.ke","health.go.ke")):
            raise HTTPException(422, "Statutory evidence must link to an official KRA, NSSF, SHA or Kenya Law HTTPS source")
        authorities.add(authority)
    combined=" ".join(authorities)
    if "kra" not in combined or "nssf" not in combined or not ("sha" in combined or "kenya law" in combined):
        raise HTTPException(422, "Rule evidence must cover KRA, NSSF and SHA/Kenya Law")


def _validate_rule_parameters(parameters):
    try:
        paye = parameters["paye"]
        bands = paye["bands"]
        if len(bands) < 2:
            raise ValueError("At least two PAYE bands are required")
        previous = D("0")
        for index, band in enumerate(bands):
            lower = D(str(band["lower"]))
            rate = D(str(band["rate"]))
            upper = D(str(band["upper"])) if band.get("upper") is not None else None
            if lower != previous or rate < 0 or rate > 1:
                raise ValueError("PAYE bands must be contiguous and rates between zero and one")
            if upper is not None and upper <= lower:
                raise ValueError("PAYE band upper limits must exceed lower limits")
            if index < len(bands)-1 and upper is None:
                raise ValueError("Only the final PAYE band may be unlimited")
            previous = upper if upper is not None else previous
        if bands[-1].get("upper") is not None:
            raise ValueError("Final PAYE band must be unlimited")
        nssf = parameters["nssf"]
        if not (D("0") < D(str(nssf["rate"])) <= D("1") and D(str(nssf["upper_earnings_limit"])) >= D(str(nssf["lower_earnings_limit"])) > 0):
            raise ValueError("Invalid NSSF contribution limits or rate")
        shif = parameters["shif"]
        housing = parameters["housing_levy"]
        if not (D("0") <= D(str(shif["rate"])) <= D("1") and D(str(shif["minimum"])) >= 0):
            raise ValueError("Invalid SHIF rate or minimum")
        if not (D("0") <= D(str(housing["employee_rate"])) <= D("1") and D("0") <= D(str(housing["employer_rate"])) <= D("1")):
            raise ValueError("Invalid Housing Levy rates")
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise HTTPException(422, f"Invalid statutory rule parameters: {exc}")


def _progressive_tax(taxable, bands):
    remaining = max(ZERO, money(taxable))
    tax = ZERO
    for band in bands:
        width = None if band.get("upper") is None else D(str(band["upper"])) - D(str(band["lower"]))
        slice_amount = remaining if width is None else min(remaining, width)
        if slice_amount > 0:
            tax += slice_amount * D(str(band["rate"]))
            remaining -= slice_amount
        if remaining <= 0:
            break
    return money(tax)


def calculate_kenya_payroll(gross, employee, rule, extra=None):
    """Monthly statutory calculation in KES. extra holds documented relief claims."""
    gross = money(gross)
    extra = extra or {}
    cfg = rule["parameters"]
    nssf_cfg = cfg["nssf"]
    nssf_base = min(gross, D(str(nssf_cfg["upper_earnings_limit"])))
    tier1 = min(nssf_base, D(str(nssf_cfg["lower_earnings_limit"])))
    tier2 = max(ZERO, nssf_base - D(str(nssf_cfg["lower_earnings_limit"])))
    nssf = money((tier1 + tier2) * D(str(nssf_cfg["rate"])))
    shif_base = money(extra.get("shif_contribution_base", gross))
    shif = max(D(str(cfg["shif"]["minimum"])), money(shif_base * D(str(cfg["shif"]["rate"])))) if shif_base > 0 else ZERO
    ahl = money(gross * D(str(cfg["housing_levy"]["employee_rate"])))
    employer_nssf = nssf
    employer_ahl = money(gross * D(str(cfg["housing_levy"]["employer_rate"])))

    pension_limit = D(str(cfg["paye"]["pension_monthly_limit"]))
    pension = min(money(extra.get("employee_pension", 0)), max(ZERO, pension_limit - nssf))
    mortgage = min(money(extra.get("mortgage_interest", 0)), D(str(cfg["paye"]["mortgage_monthly_limit"])))
    prmf = min(money(extra.get("post_retirement_medical_fund", 0)), D(str(cfg["paye"]["prmf_monthly_limit"])))
    insurance_premium = money(extra.get("insurance_premium", 0))
    insurance_relief = min(money(insurance_premium * D(str(cfg["paye"]["insurance_relief_rate"]))),
                            D(str(cfg["paye"]["insurance_relief_monthly_limit"])))
    deductible = money(ahl + shif + pension + mortgage + prmf + nssf)
    meal_exemption = min(money(extra.get("meal_benefit", 0)), D(str(cfg["paye"].get("meal_benefit_exemption_monthly", "5000"))))
    certificate_expiry = extra.get("disability_exemption_valid_until")
    certificate_valid = bool(extra.get("disability_exemption_certificate_number")) and bool(certificate_expiry)
    if certificate_valid:
        try:
            certificate_valid = date.fromisoformat(certificate_expiry) >= date.today()
        except ValueError:
            certificate_valid = False
    disability_exemption = D(str(cfg["paye"].get("disability_exemption_monthly", "150000"))) if certificate_valid else ZERO
    taxable = max(ZERO, money(gross - deductible - meal_exemption - disability_exemption))
    gross_tax = _progressive_tax(taxable, cfg["paye"]["bands"])
    personal_relief = D(str(cfg["paye"]["personal_relief_monthly"])) if employee.get("resident_for_tax", True) else ZERO
    paye = max(ZERO, money(gross_tax - personal_relief - insurance_relief - money(extra.get("other_tax_relief", 0))))
    other_deductions = money(extra.get("other_deductions", 0))
    net = money(gross - nssf - shif - ahl - paye - pension - other_deductions)
    if net < 0:
        raise HTTPException(422, "Deductions exceed gross pay; review employee declarations and payroll items")
    return {
        "gross_pay": str(gross), "taxable_pay": str(taxable), "paye": str(paye),
        "personal_relief": str(personal_relief), "insurance_relief": str(insurance_relief),
        "nssf_employee": str(nssf), "nssf_employer": str(employer_nssf),
        "shif_employee": str(shif), "housing_levy_employee": str(ahl),
        "housing_levy_employer": str(employer_ahl), "employee_pension": str(pension),
        "mortgage_interest": str(mortgage), "post_retirement_medical_fund": str(prmf),
        "other_deductions": str(other_deductions), "net_pay": str(net),
        "employer_statutory_cost": str(money(employer_nssf + employer_ahl)),
        "total_employer_cost": str(money(gross + employer_nssf + employer_ahl)),
    }


def _json_hash(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _save_record(db, org_id, user_id, kind, data, branch_id=None):
    row = Record(organization_id=org_id, module_key=MODULE, record_type=kind,
                 data=data, branch_id=branch_id, created_by=user_id)
    db.add(row)
    db.flush()
    return row


# Verified published parameters. Changes are new effective-dated records, never edits
# to a rule set already used by a payroll snapshot.
KENYA_2026_RULES = {
    "country": "KE", "currency": "KES", "version": "KE-2026-02",
    "effective_from": "2026-02-01", "effective_to": None,
    "status": "active", "reviewed_on": "2026-11-08",
    "sources": [
        {"authority": "KRA", "url": "https://www.kra.go.ke/individual/filing-paying/types-of-taxes/paye", "verified_on": "2026-11-08"},
        {"authority": "KRA", "url": "https://www.kra.go.ke/news-center/public-notices/2157-amendments-to-paye-computation-pursuant-to-the-tax-laws-amendment-act%2C-2024", "verified_on": "2026-11-08"},
        {"authority": "KRA", "url": "https://www.kra.go.ke/news-center/public-notices/2099-collection-of-the-affordable-housing-levy-by-kenya-revenue-authority", "verified_on": "2026-11-08"},
        {"authority": "NSSF", "url": "https://www.nssf.or.ke/notice-to-employers-year-4-2026-nssf-contribution-rates", "verified_on": "2026-11-08"},
        {"authority": "Kenya Law / SHA", "url": "https://new.kenyalaw.org/akn/ke/act/ln/2024/49/eng%402024-03-08/source.pdf", "verified_on": "2026-11-08"}
    ],
    "parameters": {
        "paye": {
            "meal_benefit_exemption_monthly": "5000", "disability_exemption_monthly": "150000",
            "bands": [
                {"lower": "0", "upper": "24000", "rate": "0.10"},
                {"lower": "24000", "upper": "32333", "rate": "0.25"},
                {"lower": "32333", "upper": "500000", "rate": "0.30"},
                {"lower": "500000", "upper": "800000", "rate": "0.325"},
                {"lower": "800000", "upper": None, "rate": "0.35"}
            ],
            "personal_relief_monthly": "2400", "insurance_relief_rate": "0.15",
            "insurance_relief_monthly_limit": "5000", "pension_monthly_limit": "30000",
            "mortgage_monthly_limit": "30000", "prmf_monthly_limit": "15000"
        },
        "nssf": {"rate": "0.06", "lower_earnings_limit": "9000", "upper_earnings_limit": "108000"},
        "shif": {"rate": "0.0275", "minimum": "300"},
        "housing_levy": {"employee_rate": "0.015", "employer_rate": "0.015"}
    }
}


@router.post("/hr/payroll/statutory-rules/seed-kenya-2026", status_code=201)
def seed_kenya_rules(membership=Depends(active_membership), user=Depends(current_user), db: Session=Depends(get_db)):
    _require_manage(membership)
    existing = _record(db, membership.organization_id, "statutory_rule_set", KENYA_2026_RULES["version"]).first()
    if existing:
        return {"id": existing.id, "version": existing.data["version"], "status": existing.data["status"], "existing": True}
    row = _save_record(db, membership.organization_id, user.id, "statutory_rule_set",
                       {"key": KENYA_2026_RULES["version"], **KENYA_2026_RULES})
    _audit(db, membership.organization_id, user.id, "hr.payroll.statutory_rules.seeded", "statutory_rule_set", row.id, KENYA_2026_RULES["version"])
    db.commit()
    return {"id": row.id, "version": KENYA_2026_RULES["version"], "status": "active"}


@router.post("/hr/payroll/statutory-rules", status_code=201)
def create_statutory_rules(payload: dict=Body(...), membership=Depends(active_membership),
                           user=Depends(current_user), db: Session=Depends(get_db)):
    _require_manage(membership)
    required = {"version", "effective_from", "parameters", "sources"}
    if not required.issubset(payload) or not payload["sources"]:
        raise HTTPException(422, "Version, effective_from, parameters and authoritative sources are required")
    _validate_rule_parameters(payload["parameters"])
    _validate_authority_sources(payload["sources"])
    try:
        start = date.fromisoformat(payload["effective_from"])
        end = date.fromisoformat(payload["effective_to"]) if payload.get("effective_to") else None
    except Exception:
        raise HTTPException(422, "Invalid effective date")
    if end and end < start:
        raise HTTPException(422, "Effective end date precedes start date")
    data = {**payload, "key": payload["version"], "country": "KE", "currency": "KES",
            "status": "draft", "created_by": user.id, "created_at": datetime.now(timezone.utc).isoformat()}
    row = _save_record(db, membership.organization_id, user.id, "statutory_rule_set", data)
    _audit(db, membership.organization_id, user.id, "hr.payroll.statutory_rules.created", "statutory_rule_set", row.id, data["version"])
    db.commit()
    return {"id": row.id, "version": data["version"], "status": "draft"}


@router.post("/hr/payroll/statutory-rules/{rule_id}/activate")
def activate_statutory_rules(rule_id: int, membership=Depends(active_membership), user=Depends(current_user), db: Session=Depends(get_db)):
    _require_manage(membership)
    row = db.query(Record).filter_by(id=rule_id, organization_id=membership.organization_id,
                                     module_key=MODULE, record_type="statutory_rule_set").with_for_update().first()
    if not row:
        raise HTTPException(404, "Statutory rule set not found")
    d = row.data
    if not d.get("sources") or not d.get("version") or not d.get("parameters"):
        raise HTTPException(422, "Rule set requires a version, parameters and evidence sources")
    _validate_rule_parameters(d["parameters"])
    _validate_authority_sources(d["sources"])
    start = date.fromisoformat(d["effective_from"])
    for other in _record(db, membership.organization_id, "statutory_rule_set").all():
        if other.id == row.id or other.data.get("status") != "active":
            continue
        a = date.fromisoformat(other.data["effective_from"])
        b = date.fromisoformat(other.data["effective_to"]) if other.data.get("effective_to") else date.max
        c = date.fromisoformat(d["effective_to"]) if d.get("effective_to") else date.max
        if a <= c and start <= b:
            raise HTTPException(409, "Effective period overlaps another active statutory rule set")
    d["status"] = "active"
    d["activated_by"] = user.id
    d["activated_at"] = datetime.now(timezone.utc).isoformat()
    row.data = d
    _audit(db, membership.organization_id, user.id, "hr.payroll.statutory_rules.activated", "statutory_rule_set", row.id, d["version"])
    db.commit()
    return {"id": row.id, "version": d["version"], "status": "active"}


@router.get("/hr/payroll/statutory-rules")
def list_statutory_rules(membership=Depends(active_membership), user=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    return [{"id": r.id, **r.data} for r in _record(db, membership.organization_id, "statutory_rule_set").order_by(Record.id.desc()).all()]


@router.post("/hr/payroll/runs/{run_id}/calculate-kenya")
def calculate_run(run_id: int, payload: dict=Body(default={}), membership=Depends(active_membership),
                  user=Depends(current_user), db: Session=Depends(get_db)):
    _require_manage(membership)
    run = db.query(HRPayrollRun).filter_by(id=run_id, organization_id=membership.organization_id).with_for_update().first()
    if not run:
        raise HTTPException(404, "Payroll run not found")
    if run.status != "draft":
        raise HTTPException(409, "Only draft payroll runs can be calculated")
    rule = _active_rule(db, membership.organization_id, run.period_end)
    lines = db.query(HRPayrollLine).filter_by(organization_id=membership.organization_id, run_id=run.id).all()
    if not lines:
        raise HTTPException(409, "Payroll run has no employees")
    snapshots = []
    for line in lines:
        items = db.query(HRPayrollItem).filter_by(organization_id=membership.organization_id, payroll_line_id=line.id).all()
        earnings = sum((money(i.amount) for i in items if i.item_type == "earning"), ZERO)
        deductions = sum((money(i.amount) for i in items if i.item_type == "deduction"), ZERO)
        gross = money(line.base_pay + earnings)
        employee = db.query(HREmployee).filter_by(id=line.employee_id, organization_id=membership.organization_id).first()
        extras = (payload.get("employees") or {}).get(str(line.employee_id), {})
        period_days = int(extras.get("period_days", (run.period_end - run.period_start).days + 1))
        days_employed = int(extras.get("days_employed", period_days))
        if period_days < 1 or days_employed < 0 or days_employed > period_days:
            raise HTTPException(422, "Invalid payroll proration days")
        prorated_base = money(D(str(line.base_pay)) * D(days_employed) / D(period_days))
        hourly_rate = money(extras.get("hourly_rate", 0))
        overtime_hours = D(str(extras.get("overtime_hours", 0)))
        overtime_multiplier = D(str(extras.get("overtime_multiplier", "1.5")))
        if overtime_hours < 0 or overtime_multiplier <= 0 or overtime_hours > D("744"):
            raise HTTPException(422, "Invalid overtime hours or multiplier")
        overtime_pay = money(hourly_rate * overtime_hours * overtime_multiplier)
        shift_allowance = money(extras.get("shift_allowance", 0))
        cash_allowances = money(extras.get("cash_allowances", 0))
        taxable_benefits = money(extras.get("taxable_benefits", 0))
        meal_benefit = money(extras.get("meal_benefit", 0))
        gross = money(prorated_base + earnings + overtime_pay + shift_allowance + cash_allowances + taxable_benefits + meal_benefit)
        result = calculate_kenya_payroll(gross, extras, rule.data, {**extras, "other_deductions": money(deductions + money(extras.get("other_deductions", 0)))})
        snapshot = {"employee_id": line.employee_id, "employee_number": line.employee_number,
                    "employee_name": line.employee_name, "run_id": run.id, "run_number": run.run_number,
                    "period_start": run.period_start.isoformat(), "period_end": run.period_end.isoformat(),
                    "pay_date": run.pay_date.isoformat(), "rule_set_id": rule.id, "rule_version": rule.data["version"],
                    "rule_set": rule.data, "earnings": [{"code": i.code, "description": i.description, "amount": str(i.amount)} for i in items if i.item_type == "earning"],
                    "deductions": [{"code": i.code, "description": i.description, "amount": str(i.amount)} for i in items if i.item_type == "deduction"],
                    "pay_components": {"prorated_base_pay": str(prorated_base), "days_employed": days_employed, "period_days": period_days, "overtime_hours": str(overtime_hours), "overtime_multiplier": str(overtime_multiplier), "overtime_pay": str(overtime_pay), "shift_allowance": str(shift_allowance), "cash_allowances": str(cash_allowances), "taxable_benefits": str(taxable_benefits), "meal_benefit": str(meal_benefit)}, "tax_declarations": {k: extras.get(k) for k in ("resident_for_tax","employee_pension","mortgage_interest","post_retirement_medical_fund","insurance_premium","disability_exemption_certificate_number","disability_exemption_valid_until","meal_benefit","shif_contribution_base") if k in extras}, "calculation": result, "calculated_at": datetime.now(timezone.utc).isoformat()}
        snapshot["sha256"] = _json_hash(snapshot)
        existing = _record(db, membership.organization_id, "calculation_snapshot", f"{run.id}:{line.employee_id}").first()
        if existing:
            raise HTTPException(409, "Calculation snapshot already exists; create a new payroll run to recalculate")
        _save_record(db, membership.organization_id, user.id, "calculation_snapshot",
                     {"key": f"{run.id}:{line.employee_id}", **snapshot}, line.branch_id)
        snapshots.append(snapshot)
    gross_total = sum((D(x["calculation"]["gross_pay"]) for x in snapshots), ZERO)
    deductions_total = sum((D(x["calculation"]["gross_pay"]) - D(x["calculation"]["net_pay"]) for x in snapshots), ZERO)
    net_total = sum((D(x["calculation"]["net_pay"]) for x in snapshots), ZERO)
    run.gross_total, run.deductions_total, run.net_total = gross_total, deductions_total, net_total
    run.status = "calculated"
    _audit(db, membership.organization_id, user.id, "hr.payroll.run.calculated", "hr_payroll_run", run.id,
           f"employees:{len(snapshots)};rules:{rule.data['version']}")
    db.commit()
    return {"run_id": run.id, "status": run.status, "rule_version": rule.data["version"],
            "employee_count": len(snapshots), "gross_total": str(gross_total),
            "deductions_total": str(deductions_total), "net_total": str(net_total), "snapshots": snapshots}


@router.get("/hr/payroll/runs/{run_id}/snapshots")
def list_snapshots(run_id: int, membership=Depends(active_membership), user=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    run = db.query(HRPayrollRun).filter_by(id=run_id, organization_id=membership.organization_id).first()
    if not run:
        raise HTTPException(404, "Payroll run not found")
    return [r.data for r in _record(db, membership.organization_id, "calculation_snapshot").all() if r.data.get("run_id") == run_id]


@router.post("/hr/payroll/runs/{run_id}/approve-calculation")
def approve_calculation(run_id: int, payload: dict=Body(default={}), membership=Depends(active_membership),
                        user=Depends(current_user), db: Session=Depends(get_db)):
    _require_manage(membership)
    run = db.query(HRPayrollRun).filter_by(id=run_id, organization_id=membership.organization_id).with_for_update().first()
    if not run or run.status != "calculated":
        raise HTTPException(409, "Only a calculated run can be approved")
    if run.created_by == user.id:
        raise HTTPException(403, "Maker cannot approve own payroll")
    snaps = [r for r in _record(db, membership.organization_id, "calculation_snapshot").all() if r.data.get("run_id") == run_id]
    lines = db.query(HRPayrollLine).filter_by(organization_id=membership.organization_id, run_id=run_id).count()
    if len(snaps) != lines or any(_json_hash({k:v for k,v in s.data.items() if k not in ("sha256", "key")}) != s.data.get("sha256") for s in snaps):
        raise HTTPException(409, "Payroll snapshot integrity or employee count check failed")
    run.status = "approved"
    run.approved_by, run.approved_at = user.id, datetime.now(timezone.utc)
    run.approval_note = str(payload.get("note", ""))[:500]
    _audit(db, membership.organization_id, user.id, "hr.payroll.run.calculation_approved", "hr_payroll_run", run.id)
    db.commit()
    return {"run_id": run.id, "status": run.status, "approved_by": user.id, "snapshot_count": len(snaps)}


@router.post("/hr/payroll/runs/{run_id}/payment-batches", status_code=201)
def create_payment_batch(run_id: int, payload: dict=Body(...), membership=Depends(active_membership),
                         user=Depends(current_user), db: Session=Depends(get_db)):
    _require_manage(membership)
    run = db.query(HRPayrollRun).filter_by(id=run_id, organization_id=membership.organization_id).first()
    if not run or run.status != "approved":
        raise HTTPException(409, "Payroll must be approved before payment preparation")
    method = payload.get("method")
    if method not in ("bank", "mpesa"):
        raise HTTPException(422, "Payment method must be bank or mpesa")
    snaps = [r.data for r in _record(db, membership.organization_id, "calculation_snapshot").all() if r.data.get("run_id") == run_id]
    if not snaps:
        raise HTTPException(409, "Approved calculation snapshots are missing")
    existing = _record(db, membership.organization_id, "payment_batch").filter(Record.data["run_id"].as_integer() == run_id).first()
    if existing:
        raise HTTPException(409, "A payment batch already exists for this payroll run")
    rows = []
    for s in snaps:
        emp = db.query(HREmployee).filter_by(id=s["employee_id"], organization_id=membership.organization_id).first()
        if not emp:
            raise HTTPException(409, "Employee no longer exists")
        rows.append({"employee_id": emp.id, "employee_number": emp.employee_number,
                     "employee_name": s["employee_name"], "phone": emp.phone,
                     "amount": s["calculation"]["net_pay"], "currency": run.currency,
                     "status": "pending", "provider_reference": None})
    batch = _save_record(db, membership.organization_id, user.id, "payment_batch",
                         {"key": str(uuid.uuid4()), "run_id": run_id, "method": method,
                          "status": "prepared", "rows": rows, "created_at": datetime.now(timezone.utc).isoformat()})
    _audit(db, membership.organization_id, user.id, "hr.payroll.payment_batch.prepared", "payment_batch", batch.id, method)
    db.commit()
    return {"batch_id": batch.id, **batch.data}


@router.get("/hr/payroll/payment-batches/{batch_id}/bank-file")
def export_bank_file(batch_id: int, membership=Depends(active_membership), user=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    batch = db.query(Record).filter_by(id=batch_id, organization_id=membership.organization_id,
                                       module_key=MODULE, record_type="payment_batch").first()
    if not batch or batch.data["method"] != "bank":
        raise HTTPException(404, "Bank payment batch not found")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["employee_number", "employee_name", "account_reference", "currency", "amount", "payment_reference"])
    for row in batch.data["rows"]:
        emp = db.query(HREmployee).filter_by(id=row["employee_id"], organization_id=membership.organization_id).first()
        writer.writerow([row["employee_number"], row["employee_name"], "", row["currency"], row["amount"], f"PAY-{batch.id}-{row['employee_id']}"])
    return Response(content=output.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="payroll-{batch.id}.csv"'})


@router.post("/hr/payroll/payment-batches/{batch_id}/authorize")
def authorize_batch(batch_id: int, payload: dict=Body(default={}), membership=Depends(active_membership),
                    user=Depends(current_user), db: Session=Depends(get_db)):
    _require_manage(membership)
    batch = db.query(Record).filter_by(id=batch_id, organization_id=membership.organization_id,
                                       module_key=MODULE, record_type="payment_batch").with_for_update().first()
    if not batch or batch.data["status"] != "prepared":
        raise HTTPException(409, "Only prepared payment batches can be authorized")
    run = db.query(HRPayrollRun).filter_by(id=batch.data["run_id"], organization_id=membership.organization_id).first()
    if not run or run.approved_by == user.id:
        raise HTTPException(403, "Payment authorizer must be independent of payroll approver")
    d = dict(batch.data); d["status"] = "authorized"; d["authorized_by"] = user.id
    d["authorized_at"] = datetime.now(timezone.utc).isoformat(); batch.data = d
    _audit(db, membership.organization_id, user.id, "hr.payroll.payment_batch.authorized", "payment_batch", batch.id)
    db.commit()
    return {"batch_id": batch.id, "status": "authorized"}


@router.post("/hr/payroll/payment-batches/{batch_id}/mpesa-submit")
def mpesa_submit(batch_id: int, payload: dict=Body(...), membership=Depends(active_membership),
                 user=Depends(current_user), db: Session=Depends(get_db)):
    _require_manage(membership)
    batch = db.query(Record).filter_by(id=batch_id, organization_id=membership.organization_id,
                                       module_key=MODULE, record_type="payment_batch").with_for_update().first()
    if not batch or batch.data["method"] != "mpesa" or batch.data["status"] not in ("authorized", "processing"):
        raise HTTPException(409, "An authorized M-Pesa batch is required")
    from app.core.config import settings
    import httpx
    required = (settings.mpesa_base_url, settings.mpesa_consumer_key, settings.mpesa_consumer_secret,
                settings.mpesa_shortcode, os.getenv("MPESA_INITIATOR_NAME"),
                os.getenv("MPESA_SECURITY_CREDENTIAL"), os.getenv("MPESA_B2C_RESULT_URL"),
                os.getenv("MPESA_B2C_TIMEOUT_URL"))
    if not settings.integration_mpesa_enabled or not all(required):
        raise HTTPException(503, "Daraja B2C payroll credentials and callback URLs are not fully configured")
    employee_id = int(payload.get("employee_id", 0))
    row = next((x for x in batch.data["rows"] if x["employee_id"] == employee_id), None)
    if not row or row["status"] not in ("pending", "failed") or row.get("conversation_id"):
        raise HTTPException(409, "A pending employee instruction without an existing Daraja request is required")
    if not row.get("phone"):
        raise HTTPException(422, "Employee mobile number is missing")
    phone = "".join(ch for ch in row["phone"] if ch.isdigit())
    if phone.startswith("0"):
        phone = "254" + phone[1:]
    if phone.startswith("+"):
        phone = phone[1:]
    if not phone.startswith("254") or len(phone) != 12:
        raise HTTPException(422, "Employee phone must be a valid Kenyan MSISDN")
    amount_decimal = D(row["amount"])
    if amount_decimal != amount_decimal.to_integral_value():
        raise HTTPException(422, "Daraja B2C requires whole KES amounts; configure an approved rounding policy before submission")
    base = settings.mpesa_base_url.rstrip("/")
    try:
        with httpx.Client(timeout=25.0) as client:
            token_response = client.get(base + "/oauth/v1/generate?grant_type=client_credentials",
                auth=(settings.mpesa_consumer_key, settings.mpesa_consumer_secret))
            token_response.raise_for_status()
            access_token = token_response.json()["access_token"]
            body = {"InitiatorName": os.getenv("MPESA_INITIATOR_NAME"),
                "SecurityCredential": os.getenv("MPESA_SECURITY_CREDENTIAL"),
                "CommandID": os.getenv("MPESA_B2C_COMMAND_ID", "BusinessPayment"),
                "Amount": int(amount_decimal),
                "PartyA": settings.mpesa_shortcode, "PartyB": phone,
                "Remarks": f"Salary {batch.data['run_id']}"[:100],
                "QueueTimeOutURL": os.getenv("MPESA_B2C_TIMEOUT_URL"),
                "ResultURL": os.getenv("MPESA_B2C_RESULT_URL"),
                "Occasion": f"PAY-{batch.id}-{employee_id}"}
            response = client.post(base + "/mpesa/b2c/v1/paymentrequest", json=body,
                headers={"Authorization": "Bearer " + access_token, "Content-Type": "application/json"})
            response.raise_for_status()
            provider = response.json()
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise HTTPException(502, f"Daraja B2C request failed: {type(exc).__name__}")
    if str(provider.get("ResponseCode")) != "0":
        raise HTTPException(502, "Daraja did not accept the B2C payment request")
    d = dict(batch.data); rows = list(d["rows"])
    for item in rows:
        if item["employee_id"] == employee_id:
            item.update({"status":"pending","originator_conversation_id":provider.get("OriginatorConversationID"),
                         "conversation_id":provider.get("ConversationID"),
                         "response_description":provider.get("ResponseDescription",""),
                         "submitted_at":datetime.now(timezone.utc).isoformat()})
    d["rows"] = rows; d["status"] = "processing"; batch.data = d
    _audit(db,membership.organization_id,user.id,"hr.payroll.mpesa.submitted","payment_batch",batch.id,
           f"employee:{employee_id};conversation:{provider.get('ConversationID','')}")
    db.commit()
    return {"batch_id":batch.id,"employee_id":employee_id,"status":"submitted",
            "conversation_id":provider.get("ConversationID"),
            "originator_conversation_id":provider.get("OriginatorConversationID")}


@router.post("/hr/payroll/payment-batches/{batch_id}/provider-callback")
def payment_callback(batch_id: int, payload: dict=Body(...), signature: str=Header(default="", alias="X-OneCore-Signature"),
                     db: Session=Depends(get_db)):
    secret = os.getenv("PAYROLL_PROVIDER_CALLBACK_SECRET", "")
    if not secret:
        raise HTTPException(503, "Payment callback signing secret is not configured")
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "Invalid provider callback signature")
    batch = db.query(Record).filter_by(id=batch_id, module_key=MODULE, record_type="payment_batch").with_for_update().first()
    if not batch:
        raise HTTPException(404, "Payment batch not found")
    d = dict(batch.data)
    if d.get("status") not in ("authorized", "processing", "partial", "failed"):
        raise HTTPException(409, "Payment batch must be authorized before provider callbacks")
    item_id = int(payload.get("employee_id", 0))
    row = next((x for x in d["rows"] if x["employee_id"] == item_id), None)
    if not row:
        raise HTTPException(404, "Payment instruction not found")
    status = payload.get("status")
    if status not in ("paid", "failed"):
        raise HTTPException(422, "Callback status must be paid or failed")
    if row["status"] == "paid" and (status != "paid" or row.get("provider_reference") != payload.get("provider_reference")):
        raise HTTPException(409, "A settled salary payment cannot be downgraded or assigned a different reference")
    if status == "paid" and not payload.get("provider_reference"):
        raise HTTPException(422, "Verified provider reference is required")
    row.update({"status": status, "provider_reference": payload.get("provider_reference"),
                "verified_at": datetime.now(timezone.utc).isoformat(), "callback_hash": hashlib.sha256(raw).hexdigest()})
    d["status"] = "paid" if all(x["status"] == "paid" for x in d["rows"]) else ("partial" if any(x["status"] == "paid" for x in d["rows"]) else "failed")
    batch.data = d
    if d["status"] == "paid":
        paid_run = db.query(HRPayrollRun).filter_by(id=d["run_id"], organization_id=batch.organization_id).with_for_update().first()
        if paid_run:
            paid_run.status = "paid"
    _audit(db, batch.organization_id, None, "hr.payroll.payment.callback", "payment_batch", batch.id, f"employee:{item_id};status:{status}")
    db.commit()
    return {"batch_id": batch.id, "status": d["status"]}


@router.post("/hr/payroll/payment-batches/{batch_id}/retry")
def retry_failed_payment(batch_id: int, payload: dict=Body(default={}), membership=Depends(active_membership),
                         user=Depends(current_user), db: Session=Depends(get_db)):
    _require_manage(membership)
    batch = db.query(Record).filter_by(id=batch_id, organization_id=membership.organization_id,
                                       module_key=MODULE, record_type="payment_batch").with_for_update().first()
    if not batch:
        raise HTTPException(404, "Payment batch not found")
    d = dict(batch.data)
    if d["status"] not in ("failed", "partial"):
        raise HTTPException(409, "Only failed or partially paid batches can be retried")
    failed = [x for x in d["rows"] if x["status"] == "failed"]
    if not failed:
        raise HTTPException(409, "No failed payments to retry")
    for row in failed:
        if int(row.get("retry_count", 0)) >= 3:
            raise HTTPException(409, f"Payment {row['employee_id']} has reached the three-retry limit")
        row["status"] = "pending"
        row["retry_count"] = int(row.get("retry_count", 0)) + 1
        row.pop("conversation_id", None); row.pop("originator_conversation_id", None)
        row["last_retry_at"] = datetime.now(timezone.utc).isoformat()
    d["status"] = "prepared"
    d["last_retry_by"] = user.id
    batch.data = d
    _audit(db, membership.organization_id, user.id, "hr.payroll.payment_batch.retry", "payment_batch", batch.id, f"failed:{len(failed)}")
    db.commit()
    return {"batch_id": batch.id, "status": d["status"], "retry_count": len(failed)}


@router.get("/hr/payroll/payment-batches/{batch_id}/reconciliation")
def reconcile_payments(batch_id: int, membership=Depends(active_membership), user=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    batch = db.query(Record).filter_by(id=batch_id, organization_id=membership.organization_id,
                                       module_key=MODULE, record_type="payment_batch").first()
    if not batch:
        raise HTTPException(404, "Payment batch not found")
    rows = batch.data["rows"]
    return {"batch_id": batch.id, "count": len(rows), "paid": sum(x["status"] == "paid" for x in rows),
            "failed": sum(x["status"] == "failed" for x in rows), "pending": sum(x["status"] == "pending" for x in rows),
            "paid_total": str(sum((D(x["amount"]) for x in rows if x["status"] == "paid"), ZERO)),
            "unpaid_total": str(sum((D(x["amount"]) for x in rows if x["status"] != "paid"), ZERO)),
            "rows": rows}


@router.get("/hr/payroll/reports/statutory")
def statutory_report(period_start: date, period_end: date, membership=Depends(active_membership),
                     user=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    snaps = [r.data for r in _record(db, membership.organization_id, "calculation_snapshot").all()
             if period_start.isoformat() <= r.data.get("period_end", "") <= period_end.isoformat()]
    totals = {}
    for s in snaps:
        for key in ("paye", "nssf_employee", "nssf_employer", "shif_employee", "housing_levy_employee", "housing_levy_employer"):
            totals[key] = str(money(D(totals.get(key, "0")) + D(s["calculation"][key])))
    return {"period_start": period_start.isoformat(), "period_end": period_end.isoformat(),
            "employee_count": len(snaps), "totals": totals, "snapshots": snaps}


@router.get("/hr/payroll/reports/analytics")
def payroll_analytics(membership=Depends(active_membership), user=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    runs = db.query(HRPayrollRun).filter_by(organization_id=membership.organization_id).all()
    return {"runs": len(runs), "by_status": {s: sum(r.status == s for r in runs) for s in ("draft","calculated","approved","paid")},
            "gross_total": str(money(sum((D(r.gross_total or 0) for r in runs), ZERO))),
            "net_total": str(money(sum((D(r.net_total or 0) for r in runs), ZERO)))}


@router.get("/hr/payroll/year-end/{year}")
def year_end_reconciliation(year: int, membership=Depends(active_membership), user=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    if year < 2000 or year > 2200:
        raise HTTPException(422, "Invalid year")
    snaps = [r.data for r in _record(db, membership.organization_id, "calculation_snapshot").all()
             if r.data.get("period_end", "").startswith(str(year))]
    totals = {}
    for s in snaps:
        for key in ("gross_pay","paye","nssf_employee","shif_employee","housing_levy_employee","net_pay"):
            totals[key] = str(money(D(totals.get(key, "0")) + D(s["calculation"][key])))
    return {"year": year, "months_covered": sorted({s["period_end"][:7] for s in snaps}),
            "employee_months": len(snaps), "totals": totals,
            "reconciliation_status": "workpaper_ready" if snaps else "no_payroll_data"}


@router.get("/hr/payroll/my-history")
def my_payroll_history(membership=Depends(active_membership), user=Depends(current_user), db: Session=Depends(get_db)):
    require_permission(membership, "read")
    employee = db.query(HREmployee).filter_by(organization_id=membership.organization_id, user_id=user.id, status="active").first()
    if not employee or not can_access_branch(membership, employee.branch_id):
        return []
    approved_run_ids = {r.id for r in db.query(HRPayrollRun).filter_by(organization_id=membership.organization_id).filter(HRPayrollRun.status.in_(["approved","paid"])).all()}
    rows = [r.data for r in _record(db, membership.organization_id, "calculation_snapshot").all()
            if r.data.get("employee_id") == employee.id and r.data.get("run_id") in approved_run_ids]
    return sorted(rows, key=lambda x: x["period_end"], reverse=True)


@router.post("/hr/payroll/runs/{run_id}/post-journal")
def post_payroll_journal(run_id: int, payload: dict=Body(...), membership=Depends(active_membership),
                         user=Depends(current_user), db: Session=Depends(get_db)):
    _require_manage(membership)
    run = db.query(HRPayrollRun).filter_by(id=run_id, organization_id=membership.organization_id).with_for_update().first()
    if not run or run.status != "approved":
        raise HTTPException(409, "Only an approved payroll can be posted to accounting")
    if _record(db, membership.organization_id, "payroll_journal").filter(Record.data["run_id"].as_integer() == run_id).first():
        raise HTTPException(409, "Payroll journal already exists; use a reversal for corrections")
    snaps = [r.data for r in _record(db, membership.organization_id, "calculation_snapshot").all() if r.data.get("run_id") == run_id]
    if not snaps:
        raise HTTPException(409, "Payroll calculation snapshots are missing")
    totals = {k: ZERO for k in ("gross_pay","net_pay","paye","nssf_employee","nssf_employer","shif_employee","housing_levy_employee","housing_levy_employer","employee_pension","other_deductions")}
    for s in snaps:
        c=s["calculation"]
        for k in totals:
            totals[k] += D(c.get(k,"0"))
    mapping = payload.get("accounts", {})
    keys = {"salary_expense","paye_payable","nssf_payable","shif_payable","housing_levy_payable","pension_payable","other_deductions_payable"}
    if not keys.issubset(mapping):
        raise HTTPException(422, {"message":"Map all required payroll accounts","required":sorted(keys)})
    ids = {int(mapping[k]) for k in keys}
    accounts = db.query(AccountingAccount).filter(AccountingAccount.organization_id==membership.organization_id,
             AccountingAccount.is_active==True, AccountingAccount.id.in_(ids)).all()
    if {a.id for a in accounts} != ids:
        raise HTTPException(404, "One or more mapped accounts are not active tenant accounts")
    by_id={a.id:a for a in accounts}
    if by_id[int(mapping["salary_expense"])].account_type != "expense":
        raise HTTPException(422, "Salary expense must map to an expense account")
    for key in keys - {"salary_expense"}:
        if by_id[int(mapping[key])].account_type != "liability":
            raise HTTPException(422, f"{key} must map to a liability account")
    from app.api.routes import _accounting_assert_period_open
    _accounting_assert_period_open(db,membership.organization_id,run.pay_date)
    credits = {
        "paye_payable": totals["paye"],
        "nssf_payable": totals["nssf_employee"] + totals["nssf_employer"],
        "shif_payable": totals["shif_employee"],
        "housing_levy_payable": totals["housing_levy_employee"] + totals["housing_levy_employer"],
        "pension_payable": totals["employee_pension"],
        "other_deductions_payable": totals["other_deductions"]
    }
    debit = totals["gross_pay"] + totals["nssf_employer"] + totals["housing_levy_employer"]
    credit = totals["net_pay"] + sum(credits.values(), ZERO)
    if money(debit) != money(credit):
        raise HTTPException(409, f"Payroll journal does not balance: debit {money(debit)} credit {money(credit)}")
    from app.core.models import AccountingJournal, AccountingJournalLine
    journal = AccountingJournal(organization_id=membership.organization_id, branch_id=None,
        journal_number="PAY-"+uuid.uuid4().hex[:14].upper(), reference=run.run_number,
        memo=f"Payroll {run.period_start} to {run.period_end}", status="posted",
        entry_date=datetime.combine(run.pay_date, datetime.min.time(), tzinfo=timezone.utc),
        created_by=user.id, posted_by=user.id, posted_at=datetime.now(timezone.utc))
    db.add(journal); db.flush()
    db.add(AccountingJournalLine(organization_id=membership.organization_id, journal_id=journal.id,
        account_id=int(mapping["salary_expense"]), description="Gross payroll expense", debit=money(debit-totals["nssf_employer"]-totals["housing_levy_employer"]), credit=ZERO))
    if totals["nssf_employer"] > 0:
        db.add(AccountingJournalLine(organization_id=membership.organization_id,journal_id=journal.id,account_id=int(mapping["salary_expense"]),description="Employer NSSF expense",debit=money(totals["nssf_employer"]),credit=ZERO))
    if totals["housing_levy_employer"] > 0:
        db.add(AccountingJournalLine(organization_id=membership.organization_id,journal_id=journal.id,account_id=int(mapping["salary_expense"]),description="Employer Housing Levy expense",debit=money(totals["housing_levy_employer"]),credit=ZERO))
    for key, amount in credits.items():
        if amount > 0:
            db.add(AccountingJournalLine(organization_id=membership.organization_id,journal_id=journal.id,
                account_id=int(mapping[key]),description=key.replace("_"," ").title(),debit=ZERO,credit=money(amount)))
    _save_record(db,membership.organization_id,user.id,"payroll_journal",
        {"key":str(run_id),"run_id":run_id,"journal_id":journal.id,"debit":str(money(debit)),
         "credit":str(money(credit)),"posted_at":datetime.now(timezone.utc).isoformat()})
    _audit(db,membership.organization_id,user.id,"hr.payroll.journal.posted","accounting_journal",journal.id,run.run_number)
    db.commit()
    return {"journal_id":journal.id,"journal_number":journal.journal_number,"status":"posted",
            "debits":str(money(debit)),"credits":str(money(credit)),"balanced":True}


@router.post("/hr/payroll/payment-batches/{batch_id}/bank-reconcile")
def bank_reconcile(batch_id: int, payload: dict=Body(...), membership=Depends(active_membership),
                   user=Depends(current_user), db: Session=Depends(get_db)):
    _require_manage(membership)
    batch=db.query(Record).filter_by(id=batch_id,organization_id=membership.organization_id,
        module_key=MODULE,record_type="payment_batch").with_for_update().first()
    if not batch or batch.data.get("method")!="bank":
        raise HTTPException(404,"Bank payment batch not found")
    statement=payload.get("transactions")
    if not isinstance(statement,list):
        raise HTTPException(422,"transactions must be a list of bank statement rows")
    d=dict(batch.data); matched=[]; unmatched=[]
    expected={f"PAY-{batch.id}-{r['employee_id']}":r for r in d["rows"]}
    seen=set()
    for tx in statement:
        ref=str(tx.get("reference","")); row=expected.get(ref)
        if not row or ref in seen or money(tx.get("amount",0)) != money(row["amount"]):
            unmatched.append({"reference":ref,"amount":str(tx.get("amount","")),"reason":"unknown_duplicate_or_amount_mismatch"})
            continue
        seen.add(ref); row["status"]="paid"; row["provider_reference"]=ref
        row["verified_at"]=datetime.now(timezone.utc).isoformat()
        matched.append(ref)
    d["bank_reconciliation"]={"matched":matched,"unmatched":unmatched,
        "reconciled_by":user.id,"reconciled_at":datetime.now(timezone.utc).isoformat()}
    d["status"]="paid" if all(x["status"]=="paid" for x in d["rows"]) else ("partial" if matched else "failed")
    batch.data=d
    if d["status"] == "paid":
        paid_run=db.query(HRPayrollRun).filter_by(id=d["run_id"],organization_id=membership.organization_id).with_for_update().first()
        if paid_run:
            paid_run.status="paid"
    _audit(db,membership.organization_id,user.id,"hr.payroll.bank.reconciled","payment_batch",batch.id,
           f"matched:{len(matched)};unmatched:{len(unmatched)}")
    db.commit()
    return {"batch_id":batch.id,"matched":len(matched),"unmatched":unmatched,"status":d["status"]}


@router.post("/hr/payroll/payment-batches/{batch_id}/payments/{employee_id}/reverse")
def reverse_salary_payment(batch_id: int, employee_id: int, payload: dict=Body(...),
                           membership=Depends(active_membership), user=Depends(current_user), db: Session=Depends(get_db)):
    _require_manage(membership)
    batch=db.query(Record).filter_by(id=batch_id,organization_id=membership.organization_id,
        module_key=MODULE,record_type="payment_batch").with_for_update().first()
    if not batch:
        raise HTTPException(404,"Payment batch not found")
    d=dict(batch.data); row=next((x for x in d["rows"] if x["employee_id"]==employee_id),None)
    if not row or row["status"]!="paid":
        raise HTTPException(409,"Only a verified settled salary payment can be reversed")
    if not payload.get("reason","").strip() or not payload.get("reversal_reference","").strip():
        raise HTTPException(422,"Reason and external reversal reference are required")
    if _record(db,membership.organization_id,"payment_reversal").filter(Record.data["batch_id"].as_integer()==batch_id).filter(Record.data["employee_id"].as_integer()==employee_id).first():
        raise HTTPException(409,"Payment already has a reversal record")
    reversal={"batch_id":batch_id,"employee_id":employee_id,"amount":row["amount"],
        "original_reference":row["provider_reference"],"reversal_reference":payload["reversal_reference"],
        "reason":payload["reason"],"created_by":user.id,"created_at":datetime.now(timezone.utc).isoformat()}
    _save_record(db,membership.organization_id,user.id,"payment_reversal",reversal)
    row["status"]="reversed"; row["reversal_reference"]=payload["reversal_reference"]
    d["status"]="partial"
    batch.data=d
    paid_run=db.query(HRPayrollRun).filter_by(id=d["run_id"],organization_id=membership.organization_id).with_for_update().first()
    if paid_run:
        paid_run.status="partial_paid"
    _audit(db,membership.organization_id,user.id,"hr.payroll.payment.reversed","payment_batch",batch_id,
           f"employee:{employee_id};reference:{payload['reversal_reference']}")
    db.commit()
    return {"batch_id":batch_id,"employee_id":employee_id,"status":"reversed","amount":row["amount"]}



@router.post("/hr/payroll/statutory-rules/{rule_id}/close")
def close_statutory_rules(rule_id: int, payload: dict=Body(...), membership=Depends(active_membership),
                          user=Depends(current_user), db: Session=Depends(get_db)):
    _require_manage(membership)
    row=db.query(Record).filter_by(id=rule_id,organization_id=membership.organization_id,
        module_key=MODULE,record_type="statutory_rule_set").with_for_update().first()
    if not row or row.data.get("status")!="active":
        raise HTTPException(404,"Active statutory rule set not found")
    try:
        end=date.fromisoformat(payload["effective_to"])
        start=date.fromisoformat(row.data["effective_from"])
    except (KeyError,ValueError):
        raise HTTPException(422,"A valid effective_to date is required")
    if end < start:
        raise HTTPException(422,"Effective end date precedes start date")
    for other in _record(db,membership.organization_id,"statutory_rule_set").all():
        if other.id != row.id and other.data.get("status")=="active":
            other_start=date.fromisoformat(other.data["effective_from"])
            if other_start <= end:
                raise HTTPException(409,"Closing date overlaps another active rule set")
    data=dict(row.data); data["effective_to"]=end.isoformat()
    data["closed_by"]=user.id; data["closed_at"]=datetime.now(timezone.utc).isoformat()
    row.data=data
    _audit(db,membership.organization_id,user.id,"hr.payroll.statutory_rules.closed","statutory_rule_set",row.id,data["effective_to"])
    db.commit()
    return {"id":row.id,"version":data["version"],"effective_to":data["effective_to"]}
