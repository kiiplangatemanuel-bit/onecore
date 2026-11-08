"""Tenant-scoped HR and payroll domain tables.

Payroll calculation details are persisted as immutable JSON snapshots on approval.
Statutory rules are tenant-owned and cannot be activated without independent review.
"""
from datetime import date, datetime, time as time_type, timezone
from decimal import Decimal
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, JSON, Numeric, String, Text, Time, text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


def now():
    return datetime.now(timezone.utc)


class HREmployee(Base):
    __tablename__ = "hr_employees"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    default_shift_id: Mapped[int | None] = mapped_column(ForeignKey("hr_shifts.id"), nullable=True)
    employee_number: Mapped[str] = mapped_column(String(60))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(320), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    department: Mapped[str] = mapped_column(String(120), default="")
    job_title: Mapped[str] = mapped_column(String(120), default="")
    employment_type: Mapped[str] = mapped_column(String(24), default="permanent")
    employment_status: Mapped[str] = mapped_column(String(24), default="active")
    hire_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    termination_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    base_salary: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    recurring_allowances: Mapped[dict] = mapped_column(JSON, default=dict)
    recurring_benefits: Mapped[dict] = mapped_column(JSON, default=dict)
    pension_contribution: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (Index("uq_hr_employee_org_number", "organization_id", "employee_number", unique=True),)


class HRLeaveRequest(Base):
    __tablename__ = "hr_leave_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr_employees.id"), index=True)
    leave_type: Mapped[str] = mapped_column(String(32))
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    days: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    reason: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(24), default="pending")
    decision_note: Mapped[str] = mapped_column(String(500), default="")
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PayrollRuleSet(Base):
    __tablename__ = "payroll_rule_sets"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    version: Mapped[int]
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    rules: Mapped[dict] = mapped_column(JSON)
    source_evidence: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="draft")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("uq_payroll_rule_org_version", "organization_id", "version", unique=True),)


class PayrollRun(Base):
    __tablename__ = "payroll_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    rule_set_id: Mapped[int] = mapped_column(ForeignKey("payroll_rule_sets.id"))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="draft")
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    employee_count: Mapped[int] = mapped_column(default=0)
    gross_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    deductions_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    net_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    employer_cost_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    calculation_snapshot: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_reference: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index("uq_payroll_run_org_idempotency", "organization_id", "idempotency_key", unique=True),
        Index("uq_payroll_run_org_branch_period", "organization_id", "branch_id", "period_start", "period_end",
              unique=True, sqlite_where=text("branch_id IS NOT NULL AND status <> 'cancelled'"), postgresql_where=text("branch_id IS NOT NULL AND status <> 'cancelled'")),
        Index("uq_payroll_run_org_all_period", "organization_id", "period_start", "period_end",
              unique=True, sqlite_where=text("branch_id IS NULL AND status <> 'cancelled'"), postgresql_where=text("branch_id IS NULL AND status <> 'cancelled'")),
    )


class PayrollPayslip(Base):
    __tablename__ = "payroll_payslips"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    payroll_run_id: Mapped[int] = mapped_column(ForeignKey("payroll_runs.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr_employees.id"), index=True)
    employee_number: Mapped[str] = mapped_column(String(60))
    employee_name: Mapped[str] = mapped_column(String(201))
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    gross_pay: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    taxable_pay: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    paye: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    overtime_pay: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    shift_differential_pay: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    unpaid_leave_deduction: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    nssf_employee: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    shif_employee: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    housing_levy_employee: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    pension_employee: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total_deductions: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_pay: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    nssf_employer: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    housing_levy_employer: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("uq_payroll_payslip_run_employee", "payroll_run_id", "employee_id", unique=True),)



class PayrollAccountingMapping(Base):
    __tablename__ = "payroll_accounting_mappings"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), unique=True, index=True)
    salary_expense_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    employer_contribution_expense_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    net_payable_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    paye_payable_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    nssf_payable_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    shif_payable_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    housing_levy_payable_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    pension_payable_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    bank_account_id: Mapped[int] = mapped_column(ForeignKey("accounting_accounts.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class PayrollAccountingLink(Base):
    __tablename__ = "payroll_accounting_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    payroll_run_id: Mapped[int] = mapped_column(ForeignKey("payroll_runs.id"), unique=True, index=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey("accounting_journals.id"), unique=True, index=True)
    mapping_snapshot: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    settlement_journal_id: Mapped[int | None] = mapped_column(ForeignKey("accounting_journals.id"), nullable=True)
    reversal_journal_id: Mapped[int | None] = mapped_column(ForeignKey("accounting_journals.id"), nullable=True)
    reversed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversal_reason: Mapped[str] = mapped_column(String(500), default="")
    __table_args__ = (Index("uq_payroll_accounting_reversal_journal", "reversal_journal_id", unique=True),
                      Index("uq_payroll_accounting_settlement_journal", "settlement_journal_id", unique=True))



class HRShift(Base):
    __tablename__ = "hr_shifts"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    shift_code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))
    start_time: Mapped[time_type] = mapped_column(Time)
    end_time: Mapped[datetime.time] = mapped_column(Time)
    break_minutes: Mapped[int] = mapped_column(default=0)
    differential_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("uq_hr_shift_org_code", "organization_id", "shift_code", unique=True),)


class HRAttendance(Base):
    __tablename__ = "hr_attendance"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr_employees.id"), index=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("hr_shifts.id"))
    attendance_date: Mapped[date] = mapped_column(Date, index=True)
    clock_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clock_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_minutes: Mapped[int] = mapped_column(default=0)
    worked_minutes: Mapped[int] = mapped_column(default=0)
    overtime_minutes: Mapped[int] = mapped_column(default=0)
    differential_minutes: Mapped[int] = mapped_column(default=0)
    differential_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(24), default="present")
    approval_status: Mapped[str] = mapped_column(String(24), default="pending")
    notes: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("uq_hr_attendance_org_employee_date", "organization_id", "employee_id", "attendance_date", unique=True),)
