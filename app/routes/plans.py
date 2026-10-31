from fastapi import APIRouter

from app.dependencies import Pagination, ServiceDependency
from app.models import EntityStatus
from app.schemas import PlanCreate, PlanRead, PlanUpdate

router = APIRouter(prefix="/plans", tags=["Plans"])


@router.post("", response_model=PlanRead, status_code=201)
def create_plan(data: PlanCreate, services: ServiceDependency):
    return services.plans.create(data)


@router.get("", response_model=list[PlanRead])
def list_plans(services: ServiceDependency, page: Pagination, status: EntityStatus | None = None):
    return services.plan_repo.list(**page, status=status)


@router.get("/{plan_id}", response_model=PlanRead)
def get_plan(plan_id: int, services: ServiceDependency):
    return services.plans.get(plan_id)


@router.patch("/{plan_id}", response_model=PlanRead)
def update_plan(plan_id: int, data: PlanUpdate, services: ServiceDependency):
    return services.plans.update(plan_id, data)
