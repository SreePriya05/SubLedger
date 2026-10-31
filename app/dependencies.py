from typing import Annotated

from fastapi import Depends, Query

from app.db import SessionLocal
from app.repositories import (
    CustomerRepository,
    InvoiceRepository,
    LedgerRepository,
    PaymentAttemptRepository,
    PlanRepository,
    SubscriptionRepository,
)
from app.services import (
    CustomerService,
    InvoiceService,
    LedgerService,
    PaymentService,
    PlanService,
    SubscriptionService,
)


def get_session():
    with SessionLocal() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


class Services:
    """Composition root: every dependency uses the same request-scoped transaction."""

    def __init__(self, session):
        self.plan_repo = PlanRepository(session)
        self.customer_repo = CustomerRepository(session)
        self.subscription_repo = SubscriptionRepository(session)
        self.invoice_repo = InvoiceRepository(session)
        self.payment_repo = PaymentAttemptRepository(session)
        self.ledger_repo = LedgerRepository(session)
        self.plans = PlanService(self.plan_repo)
        self.customers = CustomerService(self.customer_repo)
        self.subscriptions = SubscriptionService(
            self.subscription_repo, self.customer_repo, self.plan_repo
        )
        self.ledger = LedgerService(self.ledger_repo, self.customer_repo)
        self.invoices = InvoiceService(
            self.subscription_repo, self.plan_repo, self.invoice_repo, self.ledger
        )
        self.payments = PaymentService(
            self.invoice_repo, self.payment_repo, self.ledger, self.invoices
        )


def get_services(session=Depends(get_session, scope="function")):
    return Services(session)


ServiceDependency = Annotated[Services, Depends(get_services)]


def pagination(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return {"offset": offset, "limit": limit}


Pagination = Annotated[dict, Depends(pagination)]
