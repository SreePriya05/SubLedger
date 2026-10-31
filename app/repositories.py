"""All SQL queries live here. Repositories flush but never commit transactions."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Customer, Invoice, LedgerEntry, PaymentAttempt, Plan, Subscription


class Repository:
    model = None

    def __init__(self, session: Session):
        self.session = session

    def get(self, entity_id: int):
        return self.session.get(self.model, entity_id)

    def list(self, *, offset=0, limit=50, **filters):
        query = select(self.model)
        for field, value in filters.items():
            if value is not None:
                query = query.where(getattr(self.model, field) == value)
        return self.session.scalars(query.order_by(self.model.id).offset(offset).limit(limit)).all()

    def create(self, **fields):
        obj = self.model(**fields)
        self.session.add(obj)
        self.session.flush()
        return obj

    def update(self, obj, **fields):
        for name, value in fields.items():
            setattr(obj, name, value)
        self.session.flush()
        return obj


class PlanRepository(Repository):
    model = Plan


class CustomerRepository(Repository):
    model = Customer

    def by_email(self, email: str):
        return self.session.scalar(select(Customer).where(Customer.email == email))


class SubscriptionRepository(Repository):
    model = Subscription

    def active_for(self, customer_id: int, plan_id: int):
        return self.session.scalar(
            select(Subscription).where(
                Subscription.customer_id == customer_id,
                Subscription.plan_id == plan_id,
                Subscription.status == "active",
            )
        )


class InvoiceRepository(Repository):
    model = Invoice

    def overlapping(self, subscription_id, period_start, period_end):
        return self.session.scalar(
            select(Invoice)
            .where(
                Invoice.subscription_id == subscription_id,
                Invoice.period_start < period_end,
                Invoice.period_end > period_start,
            )
            .limit(1)
        )


class PaymentAttemptRepository(Repository):
    model = PaymentAttempt

    def by_reference(self, reference: str):
        return self.session.scalar(
            select(PaymentAttempt).where(PaymentAttempt.provider_reference == reference)
        )


class LedgerRepository:
    """Deliberately exposes no update/delete API."""

    def __init__(self, session: Session):
        self.session = session

    def append(self, **fields):
        entry = LedgerEntry(**fields)
        self.session.add(entry)
        self.session.flush()
        return entry

    def list(self, *, customer_id=None, invoice_id=None, offset=0, limit=50):
        query = select(LedgerEntry)
        if customer_id is not None:
            query = query.where(LedgerEntry.customer_id == customer_id)
        if invoice_id is not None:
            query = query.where(LedgerEntry.invoice_id == invoice_id)
        return self.session.scalars(
            query.order_by(LedgerEntry.id).offset(offset).limit(limit)
        ).all()
