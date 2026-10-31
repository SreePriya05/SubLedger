from fastapi import APIRouter

from app.dependencies import Pagination, ServiceDependency
from app.models import EntityStatus
from app.schemas import CustomerCreate, CustomerRead, CustomerUpdate

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.post("", response_model=CustomerRead, status_code=201)
def create_customer(data: CustomerCreate, services: ServiceDependency):
    return services.customers.create(data)


@router.get("", response_model=list[CustomerRead])
def list_customers(
    services: ServiceDependency, page: Pagination, status: EntityStatus | None = None
):
    return services.customer_repo.list(**page, status=status)


@router.get("/{customer_id}", response_model=CustomerRead)
def get_customer(customer_id: int, services: ServiceDependency):
    return services.customers.get(customer_id)


@router.patch("/{customer_id}", response_model=CustomerRead)
def update_customer(customer_id: int, data: CustomerUpdate, services: ServiceDependency):
    return services.customers.update(customer_id, data)
