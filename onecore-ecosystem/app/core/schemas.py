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
