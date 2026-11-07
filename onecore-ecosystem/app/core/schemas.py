from pydantic import BaseModel, EmailStr, Field
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
