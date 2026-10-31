"""Business workflows. Dependencies are injected; services never construct DB sessions."""

import calendar
from datetime import timedelta

from pydantic import ValidationError

from app.errors import DomainError, require_found
from app.models import utcnow
from app.schemas import PlanCreate


def add_months(day, months):
    month_index = day.year * 12 + day.month - 1 + months
    year, month = divmod(month_index, 12)
    month += 1
    return day.replace(
        year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1])
    )


class PlanService:
    def __init__(self, plan_repo):
        self.plans = plan_repo

    def create(self, data):
        fields = data.model_dump()
        self.validate(fields)
        return self.plans.create(**fields)

    @staticmethod
    def validate(fields):
        # Services also guard non-HTTP callers; schemas remain the single validation definition.
        try:
            PlanCreate.model_validate(fields)
        except ValidationError as exc:
            raise DomainError(
                "Invalid plan price, billing cycle, currency, or details", 422
            ) from exc

    def get(self, plan_id):
        return require_found(self.plans.get(plan_id), "Plan")

    def update(self, plan_id, data):
        plan = self.get(plan_id)
        fields = data.model_dump(exclude_unset=True)
        merged = {name: getattr(plan, name) for name in PlanCreate.model_fields}
        self.validate(merged | fields)
        return self.plans.update(plan, **fields)


class CustomerService:
    def __init__(self, customer_repo):
        self.customers = customer_repo

    def create(self, data):
        if self.customers.by_email(data.email):
            raise DomainError("Customer email already exists")
        return self.customers.create(**data.model_dump())

    def get(self, customer_id):
        return require_found(self.customers.get(customer_id), "Customer")

    def update(self, customer_id, data):
        customer = self.get(customer_id)
        fields = data.model_dump(exclude_unset=True)
        if "email" in fields:
            existing = self.customers.by_email(fields["email"])
            if existing and existing.id != customer.id:
                raise DomainError("Customer email already exists")
        return self.customers.update(customer, **fields)


class SubscriptionService:
    def __init__(self, subscription_repo, customer_repo, plan_repo):
        self.subscriptions = subscription_repo
        self.customers = customer_repo
        self.plans = plan_repo

    def get(self, subscription_id):
        return require_found(self.subscriptions.get(subscription_id), "Subscription")

    def _validate_activation(self, customer_id, plan_id):
        customer = require_found(self.customers.get(customer_id), "Customer")
        plan = require_found(self.plans.get(plan_id), "Plan")
        if customer.status != "active":
            raise DomainError("Cannot subscribe an inactive customer")
        if plan.status != "active":
            raise DomainError("Cannot subscribe to an inactive plan")
        if self.subscriptions.active_for(customer.id, plan.id):
            raise DomainError("Customer already has an active subscription to this plan")
        return plan

    def create(self, data):
        plan = self._validate_activation(data.customer_id, data.plan_id)
        start = data.start_date or utcnow().date()
        months = {"monthly": 1, "quarterly": 3, "yearly": 12}[plan.billing_cycle]
        try:
            end = add_months(start, months)
        except ValueError as exc:
            raise DomainError("Billing period exceeds the supported date range", 422) from exc
        return self.subscriptions.create(
            customer_id=data.customer_id,
            plan_id=plan.id,
            start_date=start,
            current_period_start=start,
            current_period_end=end,
        )

    def activate(self, subscription_id):
        subscription = self.get(subscription_id)
        if subscription.status == "active":
            return subscription
        self._validate_activation(subscription.customer_id, subscription.plan_id)
        return self.subscriptions.update(subscription, status="active", cancelled_at=None)

    def cancel(self, subscription_id):
        subscription = self.get(subscription_id)
        if subscription.status == "cancelled":
            return subscription
        return self.subscriptions.update(subscription, status="cancelled", cancelled_at=utcnow())


class LedgerService:
    def __init__(self, ledger_repo, customer_repo):
        self.ledger = ledger_repo
        self.customers = customer_repo

    def list(self, **filters):
        return self.ledger.list(**filters)

    def customer_history(self, customer_id, **page):
        require_found(self.customers.get(customer_id), "Customer")
        return self.ledger.list(customer_id=customer_id, **page)

    def invoice_created(self, invoice):
        return self.ledger.append(
            customer_id=invoice.customer_id,
            invoice_id=invoice.id,
            entry_type="invoice_created",
            amount=invoice.amount_due,
            currency=invoice.currency,
            reference_id=f"invoice:{invoice.id}",
            description=f"Invoice {invoice.id} issued",
        )

    def payment_recorded(self, invoice, payment):
        return self.ledger.append(
            customer_id=invoice.customer_id,
            invoice_id=invoice.id,
            entry_type="payment_success" if payment.status == "success" else "payment_failure",
            amount=payment.amount,
            currency=payment.currency,
            reference_id=f"payment_attempt:{payment.id}",
            description=f"Payment {payment.provider_reference}: {payment.status}",
        )


class InvoiceService:
    def __init__(self, subscription_repo, plan_repo, invoice_repo, ledger_service):
        self.subscriptions = subscription_repo
        self.plans = plan_repo
        self.invoices = invoice_repo
        self.ledger = ledger_service

    def apply_successful_payment(self, invoice, amount):
        """Own invoice totals and transitions; PaymentService orchestrates the payment workflow."""
        paid = invoice.amount_paid + amount
        status = "paid" if paid == invoice.amount_due else "partially_paid"
        return self.invoices.update(invoice, amount_paid=paid, status=status)

    def generate_invoice(self, data):
        subscription = require_found(self.subscriptions.get(data.subscription_id), "Subscription")
        if subscription.status != "active":
            raise DomainError("Invoices require an active subscription")
        plan = require_found(self.plans.get(subscription.plan_id), "Plan")
        start = data.period_start or subscription.current_period_start
        end = data.period_end or subscription.current_period_end
        if start < subscription.start_date:
            raise DomainError("Invoice period cannot begin before the subscription", 422)
        if self.invoices.overlapping(subscription.id, start, end):
            raise DomainError("An invoice already covers part or all of this billing period")
        try:
            due_date = data.due_date or (utcnow().date() + timedelta(days=7))
        except OverflowError as exc:
            raise DomainError("Due date exceeds the supported date range", 422) from exc
        # Versioned update serializes generation and cancellation on this subscription.
        self.subscriptions.update(subscription, version=subscription.version + 1)
        invoice = self.invoices.create(
            subscription_id=subscription.id,
            customer_id=subscription.customer_id,
            amount_due=plan.price,
            currency=plan.currency,
            period_start=start,
            period_end=end,
            due_date=due_date,
        )
        self.ledger.invoice_created(invoice)
        return invoice


class PaymentService:
    def __init__(self, invoice_repo, payment_attempt_repo, ledger_service, invoice_service):
        self.invoices = invoice_repo
        self.payments = payment_attempt_repo
        self.ledger = ledger_service
        self.invoice_service = invoice_service

    def record_payment(self, data):
        invoice = require_found(self.invoices.get(data.invoice_id), "Invoice")
        if self.payments.by_reference(data.provider_reference):
            raise DomainError(
                "provider_reference already recorded; use a unique reference per attempt"
            )
        if invoice.status in {"draft", "void", "paid"}:
            raise DomainError("Invoice is not open for payments")
        if data.currency != invoice.currency:
            raise DomainError("Payment currency must match the invoice", 422)
        if data.status == "success" and data.amount > invoice.amount_due - invoice.amount_paid:
            raise DomainError("Successful payment exceeds the invoice remaining balance", 422)
        payment = self.payments.create(**data.model_dump())
        if data.status == "success":
            self.invoice_service.apply_successful_payment(invoice, data.amount)
        self.ledger.payment_recorded(invoice, payment)
        return {"payment_attempt": payment, "invoice": invoice}
