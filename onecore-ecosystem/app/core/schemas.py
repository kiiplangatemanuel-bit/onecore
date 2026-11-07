from pydantic import BaseModel, EmailStr, Field, model_validator, field_validator
from typing import Any

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    platform_role: str
    class Config: from_attributes = True

class OrganizationIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,118}[a-z0-9]$")
    industry: str = "general"
    country: str = "KE"
    currency: str = "KES"
    timezone: str = "Africa/Nairobi"

class RecordIn(BaseModel):
    record_type: str = Field(min_length=1, max_length=100)
    data: dict[str, Any] = Field(default_factory=dict)
    branch_id: str | None = None

class RecordOut(BaseModel):
    id: int
    module_key: str
    record_type: str
    data: dict[str, Any]
    branch_id: str | None
    class Config: from_attributes = True

class BranchIn(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=180)
    address: str = Field(default="", max_length=500)


from decimal import Decimal
from pydantic import ConfigDict


class InventoryProductIn(BaseModel):
    sku: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._/-]+$")
    name: str = Field(min_length=2, max_length=180)
    description: str = Field(default="", max_length=4000)
    unit: str = Field(default="unit", min_length=1, max_length=24)
    sale_price: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("9999999999999999"))


class InventoryMovementIn(BaseModel):
    product_id: int = Field(gt=0)
    branch_id: str | None = Field(default=None, min_length=1, max_length=36)
    quantity_delta: Decimal = Field(gt=Decimal("-1000000000"), lt=Decimal("1000000000"))
    movement_type: str = Field(pattern=r"^(receipt|issue|adjustment)$")
    reference: str = Field(default="", max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=100)


class InventoryProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sku: str
    name: str
    description: str
    unit: str
    is_active: bool


from datetime import date, datetime
from decimal import Decimal


class AccountingAccountIn(BaseModel):
    code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=2, max_length=180)
    account_type: str = Field(pattern=r"^(asset|liability|equity|revenue|expense)$")


class AccountingJournalLineIn(BaseModel):
    account_id: int = Field(gt=0)
    branch_id: str | None = Field(default=None, min_length=1, max_length=36)
    description: str = Field(default="", max_length=240)
    debit: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("9999999999999999"))
    credit: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("9999999999999999"))


class AccountingJournalIn(BaseModel):
    entry_date: date
    branch_id: str | None = Field(default=None, min_length=1, max_length=36)
    reference: str = Field(default="", max_length=120)
    memo: str = Field(default="", max_length=500)
    lines: list[AccountingJournalLineIn] = Field(min_length=2, max_length=200)


class CRMContactIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=180)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, min_length=7, max_length=32)
    company: str = Field(default="", max_length=180)
    notes: str = Field(default="", max_length=4000)
    branch_id: str | None = Field(default=None, max_length=36)


class CRMLeadIn(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    contact_id: int | None = Field(default=None, gt=0)
    branch_id: str | None = Field(default=None, max_length=36)
    source: str = Field(default="other", pattern=r"^(website|referral|campaign|event|partner|walk_in|other)$")
    stage: str = Field(default="new", pattern=r"^(new|qualified|proposal|negotiation|won|lost)$")
    estimated_value: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("9999999999999999"))
    currency: str = Field(default="KES", pattern=r"^[A-Z]{3}$")
    assigned_to: int | None = Field(default=None, gt=0)
    next_step: str = Field(default="", max_length=500)


class CRMLeadStageIn(BaseModel):
    stage: str = Field(pattern=r"^(new|qualified|proposal|negotiation|won|lost)$")
    next_step: str = Field(default="", max_length=500)


class CRMActivityIn(BaseModel):
    contact_id: int | None = Field(default=None, gt=0)
    lead_id: int | None = Field(default=None, gt=0)
    activity_type: str = Field(pattern=r"^(call|email|meeting|task|note)$")
    subject: str = Field(min_length=2, max_length=180)
    notes: str = Field(default="", max_length=4000)
    due_at: datetime | None = None


class ProcurementSupplierIn(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, min_length=7, max_length=32)
    tax_pin: str = Field(default="", max_length=24)


class PurchaseOrderLineIn(BaseModel):
    product_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, le=Decimal("999999999999"))
    unit_cost: Decimal = Field(ge=0, le=Decimal("9999999999999999"))


class PurchaseOrderIn(BaseModel):
    supplier_id: int = Field(gt=0)
    branch_id: str | None = Field(default=None, max_length=36)
    currency: str = Field(default="KES", pattern=r"^[A-Z]{3}$")
    notes: str = Field(default="", max_length=1000)
    lines: list[PurchaseOrderLineIn] = Field(min_length=1, max_length=200)


class PurchaseOrderReceiptLineIn(BaseModel):
    line_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, le=Decimal("999999999999"))
    idempotency_key: str = Field(min_length=8, max_length=100)


class PurchaseOrderReceiptIn(BaseModel):
    lines: list[PurchaseOrderReceiptLineIn] = Field(min_length=1, max_length=200)


class POSShiftOpenIn(BaseModel):
    branch_id: str = Field(min_length=1, max_length=36)
    opening_cash: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("9999999999999999"))


class POSShiftCloseIn(BaseModel):
    closing_cash: Decimal = Field(ge=0, le=Decimal("9999999999999999"))


class POSSaleLineIn(BaseModel):
    product_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, le=Decimal("999999999999"))


class POSPaymentIn(BaseModel):
    method: str = Field(pattern=r"^(cash|card|bank|credit)$")
    amount: Decimal = Field(gt=0, le=Decimal("9999999999999999"), multiple_of=Decimal("0.01"))
    provider_reference: str = Field(default="", max_length=120)


class POSSaleSyncIn(BaseModel):
    client_transaction_id: str = Field(min_length=8, max_length=100)
    shift_id: int = Field(gt=0)
    branch_id: str = Field(min_length=1, max_length=36)
    currency: str = Field(default="KES", pattern=r"^[A-Z]{3}$")
    offline_created_at: datetime | None = None
    lines: list[POSSaleLineIn] = Field(min_length=1, max_length=100)
    payments: list[POSPaymentIn] = Field(min_length=1, max_length=20)


class SchoolClassIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    stream: str = Field(default="", max_length=40)
    academic_year: int = Field(ge=2000, le=2200)
    branch_id: str | None = Field(default=None, max_length=36)


class SchoolLearnerIn(BaseModel):
    admission_number: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9/_-]+$")
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    class_id: int | None = Field(default=None, gt=0)
    branch_id: str | None = Field(default=None, max_length=36)
    guardian_name: str = Field(default="", max_length=180)
    guardian_phone: str = Field(default="", max_length=32)


class SchoolSubjectIn(BaseModel):
    code: str = Field(min_length=1, max_length=24, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=120)


class SchoolAssessmentIn(BaseModel):
    class_id: int = Field(gt=0)
    subject_id: int = Field(gt=0)
    title: str = Field(min_length=2, max_length=160)
    academic_year: int = Field(ge=2000, le=2200)
    term: str = Field(min_length=1, max_length=24)
    maximum_score: Decimal = Field(gt=0, le=Decimal("999999"))
    weight: Decimal = Field(default=Decimal("1"), gt=0, le=Decimal("100"))


class SchoolMarkItemIn(BaseModel):
    learner_id: int = Field(gt=0)
    score: Decimal = Field(ge=0, le=Decimal("999999"))


class SchoolMarksIn(BaseModel):
    marks: list[SchoolMarkItemIn] = Field(min_length=1, max_length=500)


class SchoolGradeBandIn(BaseModel):
    scale_name: str = Field(default="default", min_length=1, max_length=80)
    grade: str = Field(min_length=1, max_length=12)
    minimum_percent: Decimal = Field(ge=0, le=100)
    maximum_percent: Decimal = Field(ge=0, le=100)
    points: Decimal = Field(default=Decimal("0"), ge=0, le=100)


class AccountingInvoiceLineIn(BaseModel):
    account_id: int = Field(gt=0)
    tax_account_id: int | None = Field(default=None, gt=0)
    description: str = Field(min_length=2, max_length=240)
    quantity: Decimal = Field(gt=0, le=Decimal("999999999"), multiple_of=Decimal("0.001"))
    unit_price: Decimal = Field(ge=0, le=Decimal("9999999999999999"), multiple_of=Decimal("0.01"))
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)


class AccountingInvoiceIn(BaseModel):
    invoice_type: str = Field(pattern=r"^(receivable|payable)$")
    contact_id: int | None = Field(default=None, gt=0)
    supplier_id: int | None = Field(default=None, gt=0)
    branch_id: str | None = Field(default=None, max_length=36)
    invoice_number: str = Field(min_length=2, max_length=60, pattern=r"^[A-Za-z0-9._/-]+$")
    issue_date: date
    due_date: date
    currency: str = Field(default="KES", pattern=r"^[A-Z]{3}$")
    control_account_id: int = Field(gt=0)
    lines: list[AccountingInvoiceLineIn] = Field(min_length=1, max_length=200)


class AccountingInvoicePaymentIn(BaseModel):
    payment_account_id: int = Field(gt=0)
    amount: Decimal = Field(gt=0, le=Decimal("9999999999999999"), multiple_of=Decimal("0.01"))
    payment_date: date
    reference: str = Field(default="", max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=100)


class AccountingFiscalPeriodIn(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9._/-]+$")
    start_date: date
    end_date: date


class AccountingBudgetLineIn(BaseModel):
    account_id: int = Field(gt=0)
    branch_id: str | None = Field(default=None, max_length=36)
    amount: Decimal = Field(ge=0, le=Decimal("9999999999999999"), multiple_of=Decimal("0.01"))


class AccountingBudgetIn(BaseModel):
    fiscal_period_id: int = Field(gt=0)
    name: str = Field(min_length=2, max_length=180)
    lines: list[AccountingBudgetLineIn] = Field(min_length=1, max_length=500)


class AccountingFixedAssetIn(BaseModel):
    asset_code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9._/-]+$")
    name: str = Field(min_length=2, max_length=180)
    branch_id: str | None = Field(default=None, max_length=36)
    acquisition_date: date
    cost: Decimal = Field(gt=0, le=Decimal("9999999999999999"), multiple_of=Decimal("0.01"))
    salvage_value: Decimal = Field(ge=0, le=Decimal("9999999999999999"), multiple_of=Decimal("0.01"))
    useful_life_months: int = Field(ge=1, le=1200)
    asset_account_id: int = Field(gt=0)
    accumulated_depreciation_account_id: int = Field(gt=0)
    depreciation_expense_account_id: int = Field(gt=0)
    payment_account_id: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_salvage_value(self):
        if self.salvage_value >= self.cost:
            raise ValueError("Salvage value must be less than asset cost")
        if len({self.asset_account_id, self.accumulated_depreciation_account_id,
                self.depreciation_expense_account_id, self.payment_account_id}) != 4:
            raise ValueError("Fixed asset ledger accounts must be distinct")
        return self


class AccountingDepreciationIn(BaseModel):
    period_date: date
    idempotency_key: str = Field(min_length=8, max_length=100)


class AccountingBankStatementLineIn(BaseModel):
    transaction_date: date
    description: str = Field(min_length=1, max_length=240)
    reference: str = Field(default="", max_length=120)
    amount: Decimal = Field(ge=Decimal("-9999999999999999"), le=Decimal("9999999999999999"), multiple_of=Decimal("0.01"))

    @field_validator("amount")
    @classmethod
    def amount_must_be_nonzero(cls, value):
        if value == 0:
            raise ValueError("Statement line amount must not be zero")
        return value


class AccountingBankStatementIn(BaseModel):
    bank_account_id: int = Field(gt=0)
    branch_id: str | None = Field(default=None, max_length=36)
    statement_reference: str = Field(min_length=2, max_length=80)
    start_date: date
    end_date: date
    opening_balance: Decimal = Field(ge=Decimal("-9999999999999999"), le=Decimal("9999999999999999"), multiple_of=Decimal("0.01"))
    closing_balance: Decimal = Field(ge=Decimal("-9999999999999999"), le=Decimal("9999999999999999"), multiple_of=Decimal("0.01"))
    lines: list[AccountingBankStatementLineIn] = Field(min_length=0, max_length=5000)


class AccountingBankMatchIn(BaseModel):
    statement_line_id: int = Field(gt=0)
    journal_line_id: int = Field(gt=0)


class CRMQuoteLineIn(BaseModel):
    description: str = Field(min_length=2, max_length=240)
    quantity: Decimal = Field(gt=0, le=Decimal("999999999"), multiple_of=Decimal("0.001"))
    unit_price: Decimal = Field(ge=0, le=Decimal("9999999999999999"), multiple_of=Decimal("0.01"))
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)


class CRMQuoteIn(BaseModel):
    contact_id: int = Field(gt=0)
    lead_id: int | None = Field(default=None, gt=0)
    branch_id: str | None = Field(default=None, max_length=36)
    quote_number: str = Field(min_length=2, max_length=60, pattern=r"^[A-Za-z0-9._/-]+$")
    currency: str = Field(default="KES", pattern=r"^[A-Z]{3}$")
    issue_date: date
    valid_until: date
    lines: list[CRMQuoteLineIn] = Field(min_length=1, max_length=200)


class SchoolAttendanceItemIn(BaseModel):
    learner_id: int = Field(gt=0)
    status: str = Field(pattern=r"^(present|absent|late|excused)$")
    note: str = Field(default="", max_length=500)


class SchoolAttendanceIn(BaseModel):
    class_id: int = Field(gt=0)
    attendance_date: date
    entries: list[SchoolAttendanceItemIn] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_learners(self):
        ids = [entry.learner_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("Each learner may appear only once per attendance register")
        return self
