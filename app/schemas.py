from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models import (
    BillingCycle,
    EntityStatus,
    EntryType,
    InvoiceStatus,
    PaymentStatus,
    SubscriptionStatus,
)

Money = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2, allow_inf_nan=False)]
Currency = Literal["INR", "USD", "EUR", "GBP", "AUD", "CAD", "SGD", "AED"]
Name = Annotated[str, Field(min_length=1, max_length=100)]


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True, extra="forbid")


class PlanCreate(Schema):
    name: Name
    description: Annotated[str, Field(max_length=2000)] | None = None
    billing_cycle: BillingCycle
    price: Money
    currency: Currency = "INR"
    status: EntityStatus = EntityStatus.active


class PatchSchema(Schema):
    @model_validator(mode="before")
    @classmethod
    def prevent_nulls(cls, data):
        if isinstance(data, dict):
            nullable = {"description", "company_name"}
            for key, value in data.items():
                if value is None and key not in nullable:
                    raise ValueError(f"{key} cannot be null")
        return data


class PlanUpdate(PatchSchema):
    name: Name | None = None
    description: Annotated[str, Field(max_length=2000)] | None = None
    price: Money | None = None
    billing_cycle: BillingCycle | None = None
    currency: Currency | None = None
    status: EntityStatus | None = None


class PlanRead(PlanCreate):
    id: int
    created_at: datetime
    updated_at: datetime


class CustomerCreate(Schema):
    name: Name
    email: Annotated[EmailStr, Field(max_length=254)]
    company_name: Annotated[str, Field(max_length=150)] | None = None
    status: EntityStatus = EntityStatus.active

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return str(value).lower()


class CustomerUpdate(PatchSchema):
    name: Name | None = None
    email: Annotated[EmailStr, Field(max_length=254)] | None = None
    company_name: Annotated[str, Field(max_length=150)] | None = None
    status: EntityStatus | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return str(value).lower()


class CustomerRead(CustomerCreate):
    id: int
    created_at: datetime


class SubscriptionCreate(Schema):
    customer_id: Annotated[int, Field(gt=0)]
    plan_id: Annotated[int, Field(gt=0)]
    start_date: date | None = None


class SubscriptionRead(Schema):
    id: int
    customer_id: int
    plan_id: int
    status: SubscriptionStatus
    start_date: date
    current_period_start: date
    current_period_end: date
    cancelled_at: datetime | None


class InvoiceCreate(Schema):
    subscription_id: Annotated[int, Field(gt=0)]
    period_start: date | None = None
    period_end: date | None = None
    due_date: date | None = None

    @model_validator(mode="after")
    def validate_period(self):
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("Provide both period_start and period_end, or neither")
        if self.period_start is not None and self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start")
        return self


class InvoiceRead(Schema):
    id: int
    subscription_id: int
    customer_id: int
    amount_due: Decimal
    amount_paid: Decimal
    currency: Currency
    status: InvoiceStatus
    period_start: date
    period_end: date
    due_date: date
    created_at: datetime


class PaymentCreate(Schema):
    invoice_id: Annotated[int, Field(gt=0)]
    amount: Money
    currency: Currency
    status: PaymentStatus
    provider_reference: Annotated[str, Field(min_length=1, max_length=150)]
    failure_reason: Annotated[str, Field(min_length=1, max_length=500)] | None = None

    @model_validator(mode="after")
    def validate_failure_reason(self):
        if self.status == PaymentStatus.failed and not self.failure_reason:
            raise ValueError("failure_reason is required for a failed payment")
        if self.status == PaymentStatus.success and self.failure_reason is not None:
            raise ValueError("A successful payment cannot have a failure_reason")
        return self


class PaymentRead(Schema):
    id: int
    invoice_id: int
    amount: Decimal
    currency: Currency
    status: PaymentStatus
    provider_reference: str
    failure_reason: str | None
    created_at: datetime


class PaymentResult(Schema):
    payment_attempt: PaymentRead
    invoice: InvoiceRead


class LedgerRead(Schema):
    id: int
    customer_id: int
    invoice_id: int
    entry_type: EntryType
    amount: Decimal
    currency: Currency
    reference_id: str
    description: str
    created_at: datetime
