from fastapi import APIRouter

from app.dependencies import Pagination, ServiceDependency
from app.schemas import LedgerRead

router = APIRouter(tags=["Ledger"])


@router.get("/ledger", response_model=list[LedgerRead])
def list_ledger(
    services: ServiceDependency,
    page: Pagination,
    customer_id: int | None = None,
    invoice_id: int | None = None,
):
    return services.ledger.list(**page, customer_id=customer_id, invoice_id=invoice_id)


@router.get("/customers/{customer_id}/ledger", response_model=list[LedgerRead])
def customer_ledger(customer_id: int, services: ServiceDependency, page: Pagination):
    return services.ledger.customer_history(customer_id, **page)
