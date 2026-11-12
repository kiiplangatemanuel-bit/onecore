"""Tenant-scoped SACCO loan products, origination, security and projected schedules."""
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint,
    Index, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SaccoLoanProduct(Base):
    __tablename__ = "sacco_loan_products"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_sacco_loan_product_org_id"),
        UniqueConstraint("organization_id", "code", name="uq_sacco_loan_product_org_code"),
        CheckConstraint("minimum_principal > 0 AND maximum_principal >= minimum_principal", name="ck_sacco_loan_product_principal_range"),
        CheckConstraint("annual_interest_rate_bps BETWEEN 0 AND 6000", name="ck_sacco_loan_product_interest_rate"),
        CheckConstraint("minimum_term_months BETWEEN 1 AND 120 AND maximum_term_months BETWEEN minimum_term_months AND 120", name="ck_sacco_loan_product_term_range"),
        CheckConstraint("minimum_guarantors BETWEEN 0 AND 5", name="ck_sacco_loan_product_guarantors"),
        CheckConstraint("maximum_debt_service_ratio_bps BETWEEN 1000 AND 8000", name="ck_sacco_loan_product_dsr"),
        Index("ix_sacco_loan_product_org_active", "organization_id", "is_active"),
        Index("ix_sacco_loan_product_org_branch", "organization_id", "branch_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id", ondelete="SET NULL"), nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    minimum_principal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    maximum_principal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    annual_interest_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_term_months: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_term_months: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_guarantors: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    maximum_debt_service_ratio_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=4000, server_default="4000")
    requires_collateral: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class SaccoLoanApplication(Base):
    __tablename__ = "sacco_loan_applications"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_sacco_loan_application_org_id"),
        UniqueConstraint("organization_id", "idempotency_key", name="uq_sacco_loan_application_org_idempotency"),
        ForeignKeyConstraint(
            ["organization_id", "member_id"], ["sacco_members.organization_id", "sacco_members.id"],
            ondelete="RESTRICT", name="fk_sacco_loan_application_member_tenant",
        ),
        ForeignKeyConstraint(
            ["organization_id", "product_id"], ["sacco_loan_products.organization_id", "sacco_loan_products.id"],
            ondelete="RESTRICT", name="fk_sacco_loan_application_product_tenant",
        ),
        CheckConstraint("principal > 0 AND term_months BETWEEN 1 AND 120", name="ck_sacco_loan_application_terms"),
        CheckConstraint("monthly_net_income > 0 AND monthly_existing_debt >= 0", name="ck_sacco_loan_application_income"),
        CheckConstraint("assessment_status IN ('pending', 'eligible', 'ineligible')", name="ck_sacco_loan_application_assessment"),
        CheckConstraint("status IN ('pending_assessment', 'pending_guarantors', 'pending_approval', 'approved_pending_disbursement', 'rejected')", name="ck_sacco_loan_application_status"),
        Index("ix_sacco_loan_application_org_status", "organization_id", "status", "created_at"),
        Index("ix_sacco_loan_application_org_member", "organization_id", "member_id", "created_at"),
        Index("ix_sacco_loan_application_org_branch", "organization_id", "branch_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(nullable=False, index=True)
    member_id: Mapped[int] = mapped_column(nullable=False, index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id", ondelete="SET NULL"), nullable=True, index=True)
    principal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    term_months: Mapped[int] = mapped_column(Integer, nullable=False)
    purpose: Mapped[str] = mapped_column(String(500), nullable=False)
    monthly_net_income: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    monthly_existing_debt: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    first_repayment_date: Mapped[date] = mapped_column(Date, nullable=False)
    assessment_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    debt_service_ratio_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_monthly_installment: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    assessment_note: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    assessed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending_assessment", server_default="pending_assessment")
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class SaccoLoanGuarantor(Base):
    __tablename__ = "sacco_loan_guarantors"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_sacco_loan_guarantor_org_id"),
        UniqueConstraint("organization_id", "application_id", "member_id", name="uq_sacco_loan_guarantor_application_member"),
        ForeignKeyConstraint(
            ["organization_id", "application_id"], ["sacco_loan_applications.organization_id", "sacco_loan_applications.id"],
            ondelete="CASCADE", name="fk_sacco_loan_guarantor_application_tenant",
        ),
        ForeignKeyConstraint(
            ["organization_id", "member_id"], ["sacco_members.organization_id", "sacco_members.id"],
            ondelete="RESTRICT", name="fk_sacco_loan_guarantor_member_tenant",
        ),
        CheckConstraint("guaranteed_amount > 0", name="ck_sacco_loan_guarantor_amount"),
        CheckConstraint("consent_status IN ('pending', 'accepted', 'rejected')", name="ck_sacco_loan_guarantor_status"),
        Index("ix_sacco_loan_guarantor_org_application", "organization_id", "application_id", "consent_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id: Mapped[int] = mapped_column(nullable=False, index=True)
    member_id: Mapped[int] = mapped_column(nullable=False, index=True)
    guaranteed_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    consent_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    consent_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    consent_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    consent_note: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    consent_recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class SaccoLoanCollateral(Base):
    __tablename__ = "sacco_loan_collateral"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_sacco_loan_collateral_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "application_id"], ["sacco_loan_applications.organization_id", "sacco_loan_applications.id"],
            ondelete="CASCADE", name="fk_sacco_loan_collateral_application_tenant",
        ),
        CheckConstraint("declared_value > 0", name="ck_sacco_loan_collateral_value"),
        CheckConstraint("status IN ('pending_verification', 'verified', 'rejected')", name="ck_sacco_loan_collateral_status"),
        Index("ix_sacco_loan_collateral_org_application", "organization_id", "application_id", "status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id: Mapped[int] = mapped_column(nullable=False, index=True)
    collateral_type: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    declared_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    document_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending_verification", server_default="pending_verification")
    verification_note: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class SaccoLoanInstallment(Base):
    __tablename__ = "sacco_loan_installments"
    __table_args__ = (
        UniqueConstraint("organization_id", "application_id", "installment_number", name="uq_sacco_loan_installment_number"),
        ForeignKeyConstraint(
            ["organization_id", "application_id"], ["sacco_loan_applications.organization_id", "sacco_loan_applications.id"],
            ondelete="CASCADE", name="fk_sacco_loan_installment_application_tenant",
        ),
        CheckConstraint("installment_number BETWEEN 1 AND 120", name="ck_sacco_loan_installment_number"),
        CheckConstraint("principal_due >= 0 AND interest_due >= 0 AND total_due >= 0 AND ROUND(total_due, 2) = ROUND(principal_due + interest_due, 2)", name="ck_sacco_loan_installment_amounts"),
        CheckConstraint("status IN ('projected', 'due', 'paid', 'partially_paid', 'overdue', 'waived')", name="ck_sacco_loan_installment_status"),
        Index("ix_sacco_loan_installment_org_application_due", "organization_id", "application_id", "due_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id: Mapped[int] = mapped_column(nullable=False, index=True)
    installment_number: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    principal_due: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    interest_due: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_due: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="projected", server_default="projected")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
