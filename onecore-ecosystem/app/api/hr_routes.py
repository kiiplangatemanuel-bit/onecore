"""Tenant-scoped HR employee, leave, attendance and payroll preparation APIs."""
from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Query
from app.core.database import get_db
from app.core.models import User, Membership, Branch, AuditEvent, HREmployee, HRLeaveRequest, HRAttendance, HRPayrollProfile, HRPayrollRun, HRPayrollLine, HRPayrollItem
from app.core.schemas import HREmployeeIn, HRLeaveRequestIn, HRLeaveDecisionIn, HRPayrollProfileIn, HRPayrollRunIn, HRPayrollItemIn, HRPayrollApproveIn
from app.core.security import current_user
from app.core.tenancy import active_membership
from app.core.authorization import require_permission, branch_scope_ids, can_access_branch
from app.services.hr import business_days, worked_minutes, payroll_money, payroll_item_hash, payroll_totals
router = APIRouter(prefix="/api/v1")
def audit(db, user_id, org_id, action, resource_type="", resource_id="", detail=""):
    db.add(AuditEvent(actor_user_id=user_id, organization_id=org_id, action=action, resource_type=resource_type, resource_id=str(resource_id), detail=detail[:2000]))
    db.commit()
def _hr_branch_check(db, membership, branch_id):
    if branch_id is None: return
    branch = db.query(Branch).filter_by(id=branch_id, organization_id=membership.organization_id).first()
    if not branch or not can_access_branch(membership, branch_id): raise HTTPException(404, "Branch not found")
@router.post("/hr/employees",status_code=201)
def create_hr_employee(payload:HREmployeeIn,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    _hr_branch_check(db,membership,payload.branch_id)
    if payload.user_id and not db.query(Membership).filter_by(
        user_id=payload.user_id,organization_id=membership.organization_id,is_active=True
    ).first():
        raise HTTPException(404,"Linked user is not an active member of this organization")
    if db.query(HREmployee).filter_by(
        organization_id=membership.organization_id,
        employee_number=payload.employee_number.strip().upper()).first():
        raise HTTPException(409,"Employee number already exists in this organization")
    row=HREmployee(organization_id=membership.organization_id,branch_id=payload.branch_id,
        user_id=payload.user_id,employee_number=payload.employee_number.strip().upper(),
        first_name=payload.first_name,last_name=payload.last_name,
        email=str(payload.email).lower() if payload.email else None,
        phone=payload.phone.strip() if payload.phone else None,
        department=payload.department.strip(),job_title=payload.job_title.strip(),
        employment_type=payload.employment_type,status="active",
        start_date=payload.start_date,created_by=user.id)
    db.add(row)
    try: db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,"Employee number conflicts with an existing employee")
    db.refresh(row)
    audit(db,user.id,membership.organization_id,"hr.employee.created","hr_employee",row.id)
    return {"id":row.id,"employee_number":row.employee_number,
        "name":f"{row.first_name} {row.last_name}","branch_id":row.branch_id,"status":row.status}


@router.get("/hr/employees")
def list_hr_employees(membership=Depends(active_membership),db:Session=Depends(get_db),
                      limit:int=Query(default=100,ge=1,le=500)):
    require_permission(membership,"read")
    q=db.query(HREmployee).filter_by(organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:return []
        q=q.filter(HREmployee.branch_id.in_(allowed))
    rows=q.order_by(HREmployee.id.desc()).limit(limit).all()
    return [{"id":x.id,"employee_number":x.employee_number,
        "name":f"{x.first_name} {x.last_name}","email":x.email,"phone":x.phone,
        "department":x.department,"job_title":x.job_title,
        "employment_type":x.employment_type,"status":x.status,
        "start_date":x.start_date.isoformat(),"branch_id":x.branch_id} for x in rows]


@router.post("/hr/leave-requests",status_code=201)
def create_hr_leave_request(payload:HRLeaveRequestIn,membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    employee=db.query(HREmployee).filter_by(
        id=payload.employee_id,organization_id=membership.organization_id,status="active"
    ).first()
    if not employee or not can_access_branch(membership,employee.branch_id):
        raise HTTPException(404,"Active employee not found")
    if employee.user_id==user.id:
        require_permission(membership,"create")
    else:
        require_permission(membership,"manage")
    days=business_days(payload.start_date,payload.end_date)
    if days<=0:
        raise HTTPException(422,"Leave period must include at least one working day")
    overlap=db.query(HRLeaveRequest).filter(
        HRLeaveRequest.organization_id==membership.organization_id,
        HRLeaveRequest.employee_id==employee.id,
        HRLeaveRequest.status.in_(["pending","approved"]),
        HRLeaveRequest.start_date<=payload.end_date,
        HRLeaveRequest.end_date>=payload.start_date,
    ).first()
    if overlap:
        raise HTTPException(409,"Leave dates overlap an existing pending or approved request")
    row=HRLeaveRequest(organization_id=membership.organization_id,
        employee_id=employee.id,branch_id=employee.branch_id,leave_type=payload.leave_type,
        start_date=payload.start_date,end_date=payload.end_date,
        working_days=Decimal(days),reason=payload.reason.strip(),status="pending",
        requested_by=user.id)
    db.add(row);db.commit();db.refresh(row)
    audit(db,user.id,membership.organization_id,"hr.leave.requested",
          "hr_leave_request",row.id,f"employee:{employee.id};days:{days}")
    return {"id":row.id,"employee_id":employee.id,"start_date":row.start_date.isoformat(),
        "end_date":row.end_date.isoformat(),"working_days":str(row.working_days),"status":row.status}


@router.get("/hr/my-leave-requests")
def list_my_hr_leave_requests(membership=Depends(active_membership),
                              user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"read")
    employee=db.query(HREmployee).filter_by(
        organization_id=membership.organization_id,user_id=user.id,status="active"
    ).first()
    if not employee:return []
    rows=db.query(HRLeaveRequest).filter_by(
        organization_id=membership.organization_id,employee_id=employee.id
    ).order_by(HRLeaveRequest.id.desc()).limit(200).all()
    return [{"id":x.id,"leave_type":x.leave_type,"start_date":x.start_date.isoformat(),
        "end_date":x.end_date.isoformat(),"working_days":str(x.working_days),
        "reason":x.reason,"status":x.status,"decision_note":x.decision_note} for x in rows]


@router.get("/hr/leave-requests")
def list_hr_leave_requests(membership=Depends(active_membership),db:Session=Depends(get_db),
                           limit:int=Query(default=100,ge=1,le=500)):
    require_permission(membership,"manage")
    q=db.query(HRLeaveRequest).filter_by(organization_id=membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:return []
        q=q.filter(HRLeaveRequest.branch_id.in_(allowed))
    rows=q.order_by(HRLeaveRequest.id.desc()).limit(limit).all()
    result=[]
    for x in rows:
        employee=db.query(HREmployee).filter_by(
            id=x.employee_id,organization_id=membership.organization_id).first()
        result.append({"id":x.id,"employee_id":x.employee_id,
            "employee_name":f"{employee.first_name} {employee.last_name}" if employee else "Unknown",
            "employee_number":employee.employee_number if employee else "",
            "leave_type":x.leave_type,"start_date":x.start_date.isoformat(),
            "end_date":x.end_date.isoformat(),"working_days":str(x.working_days),
            "reason":x.reason,"status":x.status,"decision_note":x.decision_note})
    return result


@router.post("/hr/leave-requests/{request_id}/decision")
def decide_hr_leave_request(request_id:int,payload:HRLeaveDecisionIn,
    membership=Depends(active_membership),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"manage")
    row=db.query(HRLeaveRequest).filter_by(
        id=request_id,organization_id=membership.organization_id
    ).with_for_update().first()
    if not row or not can_access_branch(membership,row.branch_id):
        raise HTTPException(404,"Leave request not found")
    employee=db.query(HREmployee).filter_by(
        id=row.employee_id,organization_id=membership.organization_id).first()
    if employee and employee.user_id==user.id:
        raise HTTPException(403,"Employees cannot approve or reject their own leave")
    if row.status!="pending":
        raise HTTPException(409,"Only pending leave requests can be decided")
    row.status=payload.decision;row.decided_by=user.id
    row.decided_at=datetime.now(timezone.utc);row.decision_note=payload.note.strip()
    db.commit()
    audit(db,user.id,membership.organization_id,f"hr.leave.{payload.decision}",
          "hr_leave_request",row.id)
    return {"id":row.id,"status":row.status,"decided_at":row.decided_at.isoformat()}



@router.post("/hr/attendance/clock-in", status_code=201)
def hr_attendance_clock_in(membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    employee=db.query(HREmployee).filter_by(
        organization_id=membership.organization_id,user_id=user.id,status="active"
    ).first()
    if not employee or not can_access_branch(membership,employee.branch_id):
        raise HTTPException(404,"An active employee profile linked to your account was not found")
    today=datetime.now(timezone.utc).date()
    existing=db.query(HRAttendance).filter_by(
        organization_id=membership.organization_id,employee_id=employee.id,
        attendance_date=today
    ).with_for_update().first()
    if existing:
        raise HTTPException(409,"Attendance has already been started for today")
    row=HRAttendance(organization_id=membership.organization_id,
        employee_id=employee.id,branch_id=employee.branch_id,attendance_date=today,
        clock_in_at=datetime.now(timezone.utc))
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,"Attendance was already started for today")
    db.refresh(row)
    audit(db,user.id,membership.organization_id,"hr.attendance.clocked_in",
          "hr_attendance",row.id)
    return {"id":row.id,"attendance_date":row.attendance_date.isoformat(),
        "clock_in_at":row.clock_in_at.isoformat(),"status":"clocked_in"}


@router.post("/hr/attendance/clock-out")
def hr_attendance_clock_out(membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_permission(membership,"create")
    employee=db.query(HREmployee).filter_by(
        organization_id=membership.organization_id,user_id=user.id,status="active"
    ).first()
    if not employee or not can_access_branch(membership,employee.branch_id):
        raise HTTPException(404,"An active employee profile linked to your account was not found")
    today=datetime.now(timezone.utc).date()
    row=db.query(HRAttendance).filter_by(
        organization_id=membership.organization_id,employee_id=employee.id,
        attendance_date=today
    ).with_for_update().first()
    if not row:
        raise HTTPException(409,"Clock in before clocking out")
    if row.clock_out_at:
        raise HTTPException(409,"Attendance has already been clocked out")
    now_utc=datetime.now(timezone.utc)
    started=row.clock_in_at
    if started.tzinfo is None:
        started=started.replace(tzinfo=timezone.utc)
    try:
        elapsed=worked_minutes(started,now_utc)
    except ValueError:
        raise HTTPException(409,"Clock-in timestamp is invalid")
    row.clock_out_at=now_utc
    row.worked_minutes=elapsed
    db.commit()
    audit(db,user.id,membership.organization_id,"hr.attendance.clocked_out",
          "hr_attendance",row.id,f"worked_minutes:{elapsed}")
    return {"id":row.id,"attendance_date":row.attendance_date.isoformat(),
        "clock_in_at":started.isoformat(),"clock_out_at":now_utc.isoformat(),
        "worked_minutes":elapsed,"status":"completed"}


@router.get("/hr/my-attendance")
def hr_my_attendance(membership=Depends(active_membership),
    user:User=Depends(current_user),db:Session=Depends(get_db),
    limit:int=Query(default=31,ge=1,le=180)):
    require_permission(membership,"read")
    employee=db.query(HREmployee).filter_by(
        organization_id=membership.organization_id,user_id=user.id,status="active"
    ).first()
    if not employee:
        return []
    rows=db.query(HRAttendance).filter_by(
        organization_id=membership.organization_id,employee_id=employee.id
    ).order_by(HRAttendance.attendance_date.desc()).limit(limit).all()
    return [{"id":x.id,"attendance_date":x.attendance_date.isoformat(),
        "clock_in_at":x.clock_in_at.isoformat(),
        "clock_out_at":x.clock_out_at.isoformat() if x.clock_out_at else None,
        "worked_minutes":x.worked_minutes,"status":"completed" if x.clock_out_at else "clocked_in"}
        for x in rows]


@router.get("/hr/attendance")
def hr_attendance_report(membership=Depends(active_membership),
    db:Session=Depends(get_db),limit:int=Query(default=100,ge=1,le=500)):
    require_permission(membership,"manage")
    q=db.query(HRAttendance,HREmployee).join(
        HREmployee,HREmployee.id==HRAttendance.employee_id
    ).filter(HRAttendance.organization_id==membership.organization_id)
    allowed=branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:return []
        q=q.filter(HRAttendance.branch_id.in_(allowed))
    rows=q.order_by(HRAttendance.attendance_date.desc(),HRAttendance.id.desc()).limit(limit).all()
    return [{"id":x.id,"employee_id":employee.id,
        "employee_number":employee.employee_number,
        "employee_name":f"{employee.first_name} {employee.last_name}",
        "branch_id":x.branch_id,"attendance_date":x.attendance_date.isoformat(),
        "clock_in_at":x.clock_in_at.isoformat(),
        "clock_out_at":x.clock_out_at.isoformat() if x.clock_out_at else None,
        "worked_minutes":x.worked_minutes,
        "status":"completed" if x.clock_out_at else "clocked_in"}
        for x,employee in rows]




# Payroll uses effective-dated base pay and explicit one-off earning/deduction items.
# Statutory calculations and payment execution are deliberately not inferred.
def _hr_payroll_run_lines(db, membership, run):
    lines = db.query(HRPayrollLine).filter_by(
        organization_id=membership.organization_id, run_id=run.id
    ).order_by(HRPayrollLine.employee_number, HRPayrollLine.employee_id).all()
    if not lines:
        raise HTTPException(404, "Payroll run not found")
    if any(not can_access_branch(membership, line.branch_id) for line in lines):
        raise HTTPException(404, "Payroll run not found")
    return lines


def _hr_payroll_run_out(run):
    return {
        "id": run.id, "run_number": run.run_number,
        "period_start": run.period_start.isoformat(),
        "period_end": run.period_end.isoformat(),
        "pay_date": run.pay_date.isoformat(), "currency": run.currency,
        "status": run.status, "gross_total": str(run.gross_total),
        "deductions_total": str(run.deductions_total),
        "net_total": str(run.net_total), "created_by": run.created_by,
        "approved_by": run.approved_by,
        "approved_at": run.approved_at.isoformat() if run.approved_at else None,
    }


@router.post("/hr/payroll/profiles", status_code=201)
def create_hr_payroll_profile(payload: HRPayrollProfileIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    employee = db.query(HREmployee).filter_by(
        id=payload.employee_id, organization_id=membership.organization_id, status="active"
    ).first()
    if not employee or not can_access_branch(membership, employee.branch_id):
        raise HTTPException(404, "Active employee not found")
    if payload.effective_from < employee.start_date:
        raise HTTPException(422, "Payroll profile cannot start before the employee start date")
    if employee.end_date and (payload.effective_to is None or payload.effective_to > employee.end_date):
        raise HTTPException(422, "Payroll profile must end no later than the employee end date")
    q = db.query(HRPayrollProfile).filter(
        HRPayrollProfile.organization_id == membership.organization_id,
        HRPayrollProfile.employee_id == employee.id,
        HRPayrollProfile.effective_from <= (payload.effective_to or date.max),
        or_(HRPayrollProfile.effective_to.is_(None),
            HRPayrollProfile.effective_to >= payload.effective_from),
    )
    if q.first():
        raise HTTPException(409, "Payroll profile effective dates overlap an existing profile")
    row = HRPayrollProfile(
        organization_id=membership.organization_id, employee_id=employee.id,
        branch_id=employee.branch_id, currency=payload.currency,
        base_period_pay=payroll_money(payload.base_period_pay),
        effective_from=payload.effective_from, effective_to=payload.effective_to,
        created_by=user.id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Payroll profile conflicts with an existing effective date")
    db.refresh(row)
    audit(db, user.id, membership.organization_id, "hr.payroll.profile.created",
          "hr_payroll_profile", row.id, f"employee:{employee.id};currency:{row.currency}")
    return {"id": row.id, "employee_id": employee.id, "currency": row.currency,
            "base_period_pay": str(row.base_period_pay),
            "effective_from": row.effective_from.isoformat(),
            "effective_to": row.effective_to.isoformat() if row.effective_to else None}


@router.get("/hr/payroll/profiles")
def list_hr_payroll_profiles(membership=Depends(active_membership), db: Session=Depends(get_db),
    limit: int=Query(default=200, ge=1, le=1000)):
    require_permission(membership, "manage")
    q = db.query(HRPayrollProfile, HREmployee).join(
        HREmployee, HREmployee.id == HRPayrollProfile.employee_id
    ).filter(HRPayrollProfile.organization_id == membership.organization_id)
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            return []
        q = q.filter(HRPayrollProfile.branch_id.in_(allowed))
    rows = q.order_by(HRPayrollProfile.effective_from.desc(),
                      HRPayrollProfile.id.desc()).limit(limit).all()
    return [{
        "id": profile.id, "employee_id": employee.id,
        "employee_number": employee.employee_number,
        "employee_name": f"{employee.first_name} {employee.last_name}",
        "currency": profile.currency, "base_period_pay": str(profile.base_period_pay),
        "effective_from": profile.effective_from.isoformat(),
        "effective_to": profile.effective_to.isoformat() if profile.effective_to else None,
        "branch_id": profile.branch_id,
    } for profile, employee in rows]


@router.post("/hr/payroll/runs", status_code=201)
def create_hr_payroll_run(payload: HRPayrollRunIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    overlap = db.query(HRPayrollRun).filter(
        HRPayrollRun.organization_id == membership.organization_id,
        HRPayrollRun.period_start <= payload.period_end,
        HRPayrollRun.period_end >= payload.period_start,
    ).first()
    if overlap:
        raise HTTPException(409, f"Payroll period overlaps existing run {overlap.run_number}")
    employee_query = db.query(HREmployee).filter(
        HREmployee.organization_id == membership.organization_id,
        HREmployee.status == "active",
        HREmployee.start_date <= payload.period_end,
        or_(HREmployee.end_date.is_(None), HREmployee.end_date >= payload.period_start),
    )
    allowed = branch_scope_ids(membership)
    if allowed is not None:
        if not allowed:
            raise HTTPException(403, "No branch access is assigned")
        employee_query = employee_query.filter(HREmployee.branch_id.in_(allowed))
    employees = employee_query.order_by(HREmployee.employee_number).all()
    if not employees:
        raise HTTPException(409, "No active employees are eligible for this payroll period")
    profiles = db.query(HRPayrollProfile).filter(
        HRPayrollProfile.organization_id == membership.organization_id,
        HRPayrollProfile.effective_from <= payload.period_start,
        or_(HRPayrollProfile.effective_to.is_(None),
            HRPayrollProfile.effective_to >= payload.period_end),
        HRPayrollProfile.employee_id.in_([employee.id for employee in employees]),
    ).all()
    profile_map = {}
    for profile in profiles:
        if profile.employee_id in profile_map:
            raise HTTPException(409, "An employee has multiple effective payroll profiles")
        profile_map[profile.employee_id] = profile
    missing = [employee.employee_number for employee in employees if employee.id not in profile_map]
    if missing:
        raise HTTPException(409, {"message": "Every eligible employee needs a profile covering the entire payroll period",
                                  "employees_missing_profiles": missing})
    currencies = {profile_map[employee.id].currency for employee in employees}
    if len(currencies) != 1:
        raise HTTPException(422, "A payroll run can contain only one currency; separate the workforce by currency")
    currency = next(iter(currencies))
    run = HRPayrollRun(
        organization_id=membership.organization_id,
        run_number="PAY-" + uuid.uuid4().hex[:12].upper(),
        period_start=payload.period_start, period_end=payload.period_end,
        pay_date=payload.pay_date, currency=currency, status="draft",
        created_by=user.id,
    )
    db.add(run)
    db.flush()
    gross_total = Decimal("0.00")
    for employee in employees:
        profile = profile_map[employee.id]
        base = payroll_money(profile.base_period_pay)
        gross_total += base
        db.add(HRPayrollLine(
            organization_id=membership.organization_id, run_id=run.id,
            employee_id=employee.id, branch_id=employee.branch_id,
            employee_number=employee.employee_number,
            employee_name=f"{employee.first_name} {employee.last_name}",
            department=employee.department, job_title=employee.job_title,
            base_pay=base, gross_pay=base, deductions_total=Decimal("0.00"),
            net_pay=base,
        ))
    run.gross_total = payroll_money(gross_total)
    run.deductions_total = Decimal("0.00")
    run.net_total = payroll_money(gross_total)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Payroll period conflicts with another run")
    db.refresh(run)
    audit(db, user.id, membership.organization_id, "hr.payroll.run.created",
          "hr_payroll_run", run.id, f"employees:{len(employees)};currency:{currency}")
    return {**_hr_payroll_run_out(run), "employee_count": len(employees)}


@router.get("/hr/payroll/runs")
def list_hr_payroll_runs(membership=Depends(active_membership), db: Session=Depends(get_db),
    limit: int=Query(default=100, ge=1, le=500)):
    require_permission(membership, "manage")
    runs = db.query(HRPayrollRun).filter_by(
        organization_id=membership.organization_id
    ).order_by(HRPayrollRun.period_start.desc(), HRPayrollRun.id.desc()).limit(limit).all()
    visible = []
    for run in runs:
        lines = db.query(HRPayrollLine).filter_by(
            organization_id=membership.organization_id, run_id=run.id
        ).all()
        if lines and all(can_access_branch(membership, line.branch_id) for line in lines):
            visible.append({**_hr_payroll_run_out(run), "employee_count": len(lines)})
    return visible


@router.get("/hr/payroll/runs/{run_id}")
def get_hr_payroll_run(run_id: int, membership=Depends(active_membership),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    run = db.query(HRPayrollRun).filter_by(
        id=run_id, organization_id=membership.organization_id
    ).first()
    if not run:
        raise HTTPException(404, "Payroll run not found")
    lines = _hr_payroll_run_lines(db, membership, run)
    result = []
    for line in lines:
        items = db.query(HRPayrollItem).filter_by(
            organization_id=membership.organization_id, payroll_line_id=line.id
        ).order_by(HRPayrollItem.id).all()
        result.append({
            "id": line.id, "employee_id": line.employee_id,
            "employee_number": line.employee_number, "employee_name": line.employee_name,
            "department": line.department, "job_title": line.job_title,
            "base_pay": str(line.base_pay), "gross_pay": str(line.gross_pay),
            "deductions_total": str(line.deductions_total), "net_pay": str(line.net_pay),
            "items": [{"id": item.id, "item_type": item.item_type, "code": item.code,
                       "description": item.description, "amount": str(item.amount)}
                      for item in items],
        })
    return {**_hr_payroll_run_out(run), "employee_count": len(lines), "lines": result}


@router.post("/hr/payroll/runs/{run_id}/items", status_code=201)
def add_hr_payroll_item(run_id: int, payload: HRPayrollItemIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    run = db.query(HRPayrollRun).filter_by(
        id=run_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not run:
        raise HTTPException(404, "Payroll run not found")
    if run.status != "draft":
        raise HTTPException(409, "Only draft payroll runs can be changed")
    line = db.query(HRPayrollLine).filter_by(
        organization_id=membership.organization_id, run_id=run.id,
        employee_id=payload.employee_id
    ).first()
    if not line or not can_access_branch(membership, line.branch_id):
        raise HTTPException(404, "Payroll employee line not found")
    request_hash = payroll_item_hash(payload)
    existing = db.query(HRPayrollItem).filter_by(
        organization_id=membership.organization_id, client_item_id=payload.client_item_id
    ).first()
    if existing:
        if existing.request_hash != request_hash or existing.run_id != run.id:
            raise HTTPException(409, "Payroll item ID was reused with different data")
        return {"id": existing.id, "status": "already_recorded",
                "gross_pay": str(line.gross_pay), "deductions_total": str(line.deductions_total),
                "net_pay": str(line.net_pay)}
    item = HRPayrollItem(
        organization_id=membership.organization_id, run_id=run.id,
        payroll_line_id=line.id, item_type=payload.item_type,
        code=payload.code.strip().upper(), description=payload.description.strip(),
        amount=payroll_money(payload.amount), client_item_id=payload.client_item_id,
        request_hash=request_hash, created_by=user.id,
    )
    items = db.query(HRPayrollItem).filter_by(
        organization_id=membership.organization_id, payroll_line_id=line.id
    ).all() + [item]
    try:
        gross, deductions, net = payroll_totals(line.base_pay, items)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    previous_gross = Decimal(str(line.gross_pay))
    previous_deductions = Decimal(str(line.deductions_total))
    previous_net = Decimal(str(line.net_pay))
    line.gross_pay, line.deductions_total, line.net_pay = gross, deductions, net
    db.add(item)
    all_lines = db.query(HRPayrollLine).filter_by(
        organization_id=membership.organization_id, run_id=run.id
    ).all()
    run.gross_total = payroll_money(sum((Decimal(str(x.gross_pay)) for x in all_lines), Decimal("0.00")) - previous_gross + gross)
    run.deductions_total = payroll_money(sum((Decimal(str(x.deductions_total)) for x in all_lines), Decimal("0.00")) - previous_deductions + deductions)
    run.net_total = payroll_money(sum((Decimal(str(x.net_pay)) for x in all_lines), Decimal("0.00")) - previous_net + net)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(HRPayrollItem).filter_by(
            organization_id=membership.organization_id, client_item_id=payload.client_item_id
        ).first()
        if existing and existing.request_hash == request_hash and existing.run_id == run.id:
            refreshed_line = db.query(HRPayrollLine).filter_by(
                organization_id=membership.organization_id, run_id=run.id,
                employee_id=payload.employee_id
            ).first()
            return {"id": existing.id, "status": "already_recorded",
                    "gross_pay": str(refreshed_line.gross_pay),
                    "deductions_total": str(refreshed_line.deductions_total),
                    "net_pay": str(refreshed_line.net_pay)}
        raise HTTPException(409, "Payroll item conflicts with an existing item ID")
    db.refresh(item)
    audit(db, user.id, membership.organization_id, "hr.payroll.item.added",
          "hr_payroll_item", item.id, f"run:{run.id};employee:{line.employee_id};type:{item.item_type}")
    return {"id": item.id, "status": "recorded", "gross_pay": str(line.gross_pay),
            "deductions_total": str(line.deductions_total), "net_pay": str(line.net_pay),
            "run_gross_total": str(run.gross_total), "run_net_total": str(run.net_total)}


@router.post("/hr/payroll/runs/{run_id}/approve")
def approve_hr_payroll_run(run_id: int, payload: HRPayrollApproveIn,
    membership=Depends(active_membership), user: User=Depends(current_user),
    db: Session=Depends(get_db)):
    require_permission(membership, "manage")
    run = db.query(HRPayrollRun).filter_by(
        id=run_id, organization_id=membership.organization_id
    ).with_for_update().first()
    if not run:
        raise HTTPException(404, "Payroll run not found")
    if run.status != "draft":
        raise HTTPException(409, "Only draft payroll runs can be approved")
    if run.created_by == user.id:
        raise HTTPException(403, "The payroll run creator cannot approve the same run")
    lines = _hr_payroll_run_lines(db, membership, run)
    if not lines or any(Decimal(str(line.net_pay)) < 0 for line in lines):
        raise HTTPException(409, "Payroll run contains an invalid net pay")
    run.status = "approved"
    run.approved_by = user.id
    run.approved_at = datetime.now(timezone.utc)
    run.approval_note = payload.note.strip()
    db.commit()
    audit(db, user.id, membership.organization_id, "hr.payroll.run.approved",
          "hr_payroll_run", run.id, f"employees:{len(lines)}")
    return _hr_payroll_run_out(run)


@router.get("/hr/payroll/my-payslips")
def list_my_hr_payslips(membership=Depends(active_membership),
    user: User=Depends(current_user), db: Session=Depends(get_db),
    limit: int=Query(default=24, ge=1, le=120)):
    require_permission(membership, "read")
    employee = db.query(HREmployee).filter_by(
        organization_id=membership.organization_id, user_id=user.id, status="active"
    ).first()
    if not employee or not can_access_branch(membership, employee.branch_id):
        return []
    q = db.query(HRPayrollLine, HRPayrollRun).join(
        HRPayrollRun, HRPayrollRun.id == HRPayrollLine.run_id
    ).filter(HRPayrollLine.organization_id == membership.organization_id,
             HRPayrollLine.employee_id == employee.id, HRPayrollRun.status == "approved")
    rows = q.order_by(HRPayrollRun.period_end.desc()).limit(limit).all()
    payslips = []
    for line, run in rows:
        items = db.query(HRPayrollItem).filter_by(
            organization_id=membership.organization_id, payroll_line_id=line.id
        ).order_by(HRPayrollItem.id).all()
        payslips.append({
            "run_number": run.run_number, "period_start": run.period_start.isoformat(),
            "period_end": run.period_end.isoformat(), "pay_date": run.pay_date.isoformat(),
            "currency": run.currency, "employee_number": line.employee_number,
            "employee_name": line.employee_name, "base_pay": str(line.base_pay),
            "gross_pay": str(line.gross_pay), "deductions_total": str(line.deductions_total),
            "net_pay": str(line.net_pay),
            "items": [{"item_type": item.item_type, "code": item.code,
                       "description": item.description, "amount": str(item.amount)}
                      for item in items],
        })
    return payslips




