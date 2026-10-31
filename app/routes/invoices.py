from fastapi import APIRouter

from app.dependencies import Pagination, ServiceDependency
from app.errors import require_found
from app.models import InvoiceStatus
from app.schemas import InvoiceCreate, InvoiceRead

router = APIRouter(prefix="/invoices", tags=["Invoices"])


@router.post("", response_model=InvoiceRead, status_code=201)
def generate_invoice(data: InvoiceCreate, services: ServiceDependency):
    return services.invoices.generate_invoice(data)


@router.get("", response_model=list[InvoiceRead])
def list_invoices(
    services: ServiceDependency,
    page: Pagination,
    customer_id: int | None = None,
    subscription_id: int | None = None,
    status: InvoiceStatus | None = None,
):
    return services.invoice_repo.list(
        **page, customer_id=customer_id, subscription_id=subscription_id, status=status
    )


@router.get("/{invoice_id}", response_model=InvoiceRead)
def get_invoice(invoice_id: int, services: ServiceDependency):
    return require_found(services.invoice_repo.get(invoice_id), "Invoice")
