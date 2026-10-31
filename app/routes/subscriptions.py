from fastapi import APIRouter

from app.dependencies import Pagination, ServiceDependency
from app.models import SubscriptionStatus
from app.schemas import SubscriptionCreate, SubscriptionRead

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])


@router.post("", response_model=SubscriptionRead, status_code=201)
def create_subscription(data: SubscriptionCreate, services: ServiceDependency):
    return services.subscriptions.create(data)


@router.get("", response_model=list[SubscriptionRead])
def list_subscriptions(
    services: ServiceDependency,
    page: Pagination,
    customer_id: int | None = None,
    plan_id: int | None = None,
    status: SubscriptionStatus | None = None,
):
    return services.subscription_repo.list(
        **page, customer_id=customer_id, plan_id=plan_id, status=status
    )


@router.get("/{subscription_id}", response_model=SubscriptionRead)
def get_subscription(subscription_id: int, services: ServiceDependency):
    return services.subscriptions.get(subscription_id)


@router.post("/{subscription_id}/activate", response_model=SubscriptionRead)
def activate_subscription(subscription_id: int, services: ServiceDependency):
    return services.subscriptions.activate(subscription_id)


@router.post("/{subscription_id}/cancel", response_model=SubscriptionRead)
def cancel_subscription(subscription_id: int, services: ServiceDependency):
    return services.subscriptions.cancel(subscription_id)
