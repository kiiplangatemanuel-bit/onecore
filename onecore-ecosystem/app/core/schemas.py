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
    cost_price: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("99999999999999.9999"))
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100, multiple_of=Decimal("0.0001"))


class InventoryProductTaxRateIn(BaseModel):
    tax_rate: Decimal = Field(ge=0, le=100, multiple_of=Decimal("0.0001"))


class InventoryMovementIn(BaseModel):
    product_id: int = Field(gt=0)
    branch_id: str | None = Field(default=None, min_length=1, max_length=36)
    warehouse_id: int | None = Field(default=None, gt=0)
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
    closing_cash: Decimal = Field(ge=0, le=Decimal("9999999999999999"), multiple_of=Decimal("0.01"))
    cash_count: dict[str,int] = Field(min_length=1, max_length=10)
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_cash_count(self):
        allowed={"1","5","10","20","40","50","100","200","500","1000"}
        if set(self.cash_count)-allowed or any(v<0 or v>1000000 for v in self.cash_count.values()):
            raise ValueError("Invalid KES denomination or quantity")
        if self.cash_count and sum(Decimal(k)*v for k,v in self.cash_count.items())!=self.closing_cash:
            raise ValueError("Denomination count must equal closing cash")
        return self


class POSCashMovementIn(BaseModel):
    movement_type: str = Field(pattern=r"^(cash_in|cash_out|safe_drop)$")
    amount: Decimal = Field(gt=0,le=Decimal("9999999999999999"),multiple_of=Decimal("0.01"))
    reason: str = Field(min_length=5,max_length=500)
    reference: str = Field(default="",max_length=120)
    idempotency_key: str = Field(min_length=8,max_length=100)


class POSShiftReviewIn(BaseModel):
    decision: str = Field(pattern=r"^(approve|reject)$")
    note: str = Field(min_length=5,max_length=500)


class POSSaleLineIn(BaseModel):
    product_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, le=Decimal("999999999999"))
    discount_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100, multiple_of=Decimal("0.0001"))


class POSPaymentIn(BaseModel):
    method: str = Field(pattern=r"^(cash|card|bank|credit|mpesa)$")
    amount: Decimal = Field(gt=0, le=Decimal("9999999999999999"), multiple_of=Decimal("0.01"))
    provider_reference: str = Field(default="", max_length=120)


class POSSaleSyncIn(BaseModel):
    client_transaction_id: str = Field(min_length=8, max_length=100)
    shift_id: int = Field(gt=0)
    branch_id: str = Field(min_length=1, max_length=36)
    customer_ref: str | None = Field(default=None, min_length=1, max_length=100)
    currency: str = Field(default="KES", pattern=r"^[A-Z]{3}$")
    offline_created_at: datetime | None = None
    lines: list[POSSaleLineIn] = Field(min_length=1, max_length=100)
    payments: list[POSPaymentIn] = Field(min_length=1, max_length=20)


class POSReturnLineIn(BaseModel):
    sale_line_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, le=Decimal("999999999"))


class POSRefundIn(BaseModel):
    method: str = Field(pattern=r"^(cash|card|bank|mpesa)$")
    amount: Decimal = Field(gt=0, le=Decimal("9999999999999999"), multiple_of=Decimal("0.01"))
    provider_reference: str = Field(default="", max_length=120)


class POSReturnIn(BaseModel):
    client_return_id: str = Field(min_length=8, max_length=100)
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value):
        if len(value.strip()) < 5:
            raise ValueError("Return reason must contain at least five non-space characters")
        return value.strip()
    lines: list[POSReturnLineIn] = Field(min_length=1, max_length=100)
    refunds: list[POSRefundIn] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_sale_lines(self):
        ids = [line.sale_line_id for line in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("Each original sale line may appear only once per return")
        return self


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


class AccountingInvoiceApprovalDecisionIn(BaseModel):
    decision: str = Field(pattern=r"^(approved|rejected)$")
    note: str = Field(default="", max_length=500)


class AccountingCreditNoteLineIn(BaseModel):
    invoice_line_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, le=Decimal("999999999"), multiple_of=Decimal("0.001"))


class AccountingCreditNoteIn(BaseModel):
    credit_note_number: str = Field(min_length=2, max_length=60, pattern=r"^[A-Za-z0-9._/-]+$")
    issue_date: date
    reason: str = Field(min_length=5, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=100)
    lines: list[AccountingCreditNoteLineIn] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_invoice_lines(self):
        ids = [line.invoice_line_id for line in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("Each invoice line may be credited only once per credit note")
        return self


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


class SchoolLearnerPlacementIn(BaseModel):
    target_class_id: int = Field(gt=0)
    effective_date: date
    change_type: str = Field(pattern=r"^(promotion|transfer)$")
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, value):
        value = value.strip()
        if len(value) < 5:
            raise ValueError("Placement reason must contain at least five non-space characters")
        return value


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


class ProcurementRequisitionLineIn(BaseModel):
    product_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, le=Decimal("999999999999"))


class ProcurementRequisitionIn(BaseModel):
    branch_id: str | None = Field(default=None, max_length=36)
    justification: str = Field(min_length=5, max_length=1000)
    lines: list[ProcurementRequisitionLineIn] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_products(self):
        ids = [line.product_id for line in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("Each product may appear only once in a requisition")
        return self


class ProcurementRequisitionReviewIn(BaseModel):
    reason: str = Field(default="", max_length=500)


class GoodsReceiptLineIn(BaseModel):
    line_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, le=Decimal("999999999999"))
    idempotency_key: str = Field(min_length=8, max_length=100)


class GoodsReceiptIn(BaseModel):
    lines: list[GoodsReceiptLineIn] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_po_lines_and_keys(self):
        line_ids = [x.line_id for x in self.lines]
        keys = [x.idempotency_key for x in self.lines]
        if len(line_ids) != len(set(line_ids)):
            raise ValueError("Each purchase order line may appear only once per receipt")
        if len(keys) != len(set(keys)):
            raise ValueError("Receipt idempotency keys must be unique")
        return self


class GoodsReceiptInspectionLineIn(BaseModel):
    receipt_line_id: int = Field(gt=0)
    quantity_accepted: Decimal = Field(ge=0, le=Decimal("999999999999"))
    quantity_rejected: Decimal = Field(ge=0, le=Decimal("999999999999"))
    rejection_reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def positive_inspection_total(self):
        if self.quantity_accepted + self.quantity_rejected <= 0:
            raise ValueError("Inspection must account for a positive quantity")
        if self.quantity_rejected > 0 and len(self.rejection_reason.strip()) < 5:
            raise ValueError("A rejection reason of at least 5 characters is required")
        return self


class GoodsReceiptInspectionIn(BaseModel):
    lines: list[GoodsReceiptInspectionLineIn] = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def unique_receipt_lines(self):
        ids = [x.receipt_line_id for x in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("Each receipt line may be inspected only once per request")
        return self


class RequisitionConvertIn(BaseModel):
    supplier_id: int = Field(gt=0)
    currency: str = Field(default="KES", pattern=r"^[A-Z]{3}$")
    notes: str = Field(default="", max_length=1000)
    unit_costs: dict[int, Decimal] = Field(default_factory=dict)


class ProcurementApprovalRuleIn(BaseModel):
    minimum_amount: Decimal = Field(ge=0, le=Decimal("9999999999999999"))
    maximum_amount: Decimal | None = Field(default=None, gt=0, le=Decimal("9999999999999999"))
    approval_level: int = Field(ge=1, le=5)
    approver_role: str = Field(default="org_admin", pattern=r"^(org_admin|manager)$")

    @model_validator(mode="after")
    def valid_amount_range(self):
        if self.maximum_amount is not None and self.maximum_amount <= self.minimum_amount:
            raise ValueError("Maximum must exceed minimum")
        return self


class ProcurementRFQIn(BaseModel):
    branch_id: str | None = Field(default=None, max_length=36)
    closing_date: datetime
    notes: str = Field(default="", max_length=1000)
    supplier_ids: list[int] = Field(min_length=2, max_length=100)
    lines: list[ProcurementRequisitionLineIn] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_suppliers_products(self):
        if len(set(self.supplier_ids)) != len(self.supplier_ids):
            raise ValueError("Supplier invitations must be unique")
        ids = [x.product_id for x in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("RFQ products must be unique")
        return self


class ProcurementRFQQuoteLineIn(BaseModel):
    rfq_line_id: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0, le=Decimal("9999999999999999"))
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)


class ProcurementRFQQuoteIn(BaseModel):
    supplier_id: int = Field(gt=0)
    currency: str = Field(default="KES", pattern=r"^[A-Z]{3}$")
    delivery_days: int = Field(ge=0, le=3650)
    lines: list[ProcurementRFQQuoteLineIn] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_lines(self):
        ids = [x.rfq_line_id for x in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("Quote lines must be unique")
        return self


class SupplierInvoiceLineIn(BaseModel):
    purchase_order_line_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, le=Decimal("999999999999"))
    unit_cost: Decimal = Field(ge=0, le=Decimal("9999999999999999"))


class SupplierInvoiceIn(BaseModel):
    supplier_id: int = Field(gt=0)
    purchase_order_id: int = Field(gt=0)
    invoice_number: str = Field(min_length=2, max_length=80)
    invoice_date: date
    currency: str = Field(default="KES", pattern=r"^[A-Z]{3}$")
    tax_total: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("9999999999999999"))
    lines: list[SupplierInvoiceLineIn] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_po_lines(self):
        ids = [x.purchase_order_line_id for x in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("Invoice purchase order lines must be unique")
        return self


class SupplierReturnLineIn(BaseModel):
    receipt_line_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, le=Decimal("999999999999"))


class SupplierReturnIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)
    credit_note_reference: str = Field(default="", max_length=100)
    lines: list[SupplierReturnLineIn] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_receipt_lines(self):
        ids = [x.receipt_line_id for x in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("Return receipt lines must be unique")
        return self



class CRMQuoteConvertIn(BaseModel):
    order_number: str | None = Field(default=None, min_length=2, max_length=60,
                                      pattern=r"^[A-Za-z0-9._/-]+$")



class CRMContactConsentIn(BaseModel):
    channel: str = Field(pattern=r"^(email|sms|whatsapp)$")
    purpose: str = Field(default="marketing", pattern=r"^marketing$")
    decision: str = Field(pattern=r"^(granted|revoked)$")
    source: str = Field(min_length=2, max_length=80)
    expires_at: datetime | None = None

    @field_validator("source")
    @classmethod
    def source_not_blank(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Consent source must be provided")
        return value


class CRMCampaignIn(BaseModel):
    campaign_number: str = Field(min_length=2, max_length=60,
                                 pattern=r"^[A-Za-z0-9._/-]+$")
    name: str = Field(min_length=2, max_length=180)
    branch_id: str | None = Field(default=None, max_length=36)
    channel: str = Field(pattern=r"^(email|sms|whatsapp)$")
    message: str = Field(min_length=2, max_length=5000)

    @field_validator("name", "message")
    @classmethod
    def nonblank_campaign_fields(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Campaign name and message must not be blank")
        return value
