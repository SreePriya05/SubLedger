from fastapi import APIRouter

from app.dependencies import Pagination, ServiceDependency
from app.errors import require_found
from app.models import PaymentStatus
from app.schemas import PaymentCreate, PaymentRead, PaymentResult

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post("", response_model=PaymentResult, status_code=201)
def record_payment(data: PaymentCreate, services: ServiceDependency):
    return services.payments.record_payment(data)


@router.get("", response_model=list[PaymentRead])
def list_payments(
    services: ServiceDependency,
    page: Pagination,
    invoice_id: int | None = None,
    status: PaymentStatus | None = None,
):
    return services.payment_repo.list(**page, invoice_id=invoice_id, status=status)


@router.get("/{payment_id}", response_model=PaymentRead)
def get_payment(payment_id: int, services: ServiceDependency):
    return require_found(services.payment_repo.get(payment_id), "Payment attempt")
