"""Pydantic request/response schemas (validation at the boundary)."""
from decimal import Decimal

from pydantic import BaseModel, Field


class SetupRequest(BaseModel):
    token: str = Field(min_length=16)
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    is_active: bool
    permissions: list[str] = []


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12, max_length=128)
    roles: list[str] = Field(default_factory=list)


class RoleOut(BaseModel):
    id: int
    name: str
    is_system: bool
    description: str
    permissions: list[str] = []


class CreateRoleRequest(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    description: str = Field(default="", max_length=255)
    permissions: list[str] = Field(default_factory=list)


class AuditOut(BaseModel):
    id: int
    created_at: str
    actor_id: int | None
    action: str
    entity: str
    entity_id: str | None
    details: dict | None
    prev_hash: str
    hash: str


class CreatePeriodRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    starts_on: str
    ends_on: str


class CreateAccountRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    type: str
    parent_id: int | None = None
    description: str = Field(default="", max_length=500)


class UpdateAccountRequest(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    is_active: bool | None = None


class VoucherLineRequest(BaseModel):
    account_id: int
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    narrative: str = Field(default="", max_length=500)


class CreateVoucherRequest(BaseModel):
    voucher_type: str = Field(min_length=1, max_length=24)
    fy_id: int
    voucher_date: str
    narration: str = Field(default="", max_length=500)
    lines: list[VoucherLineRequest] = Field(default_factory=list)
