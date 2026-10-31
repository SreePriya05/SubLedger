from fastapi import APIRouter

from app.routes import customers, invoices, ledger, payments, plans, subscriptions

router = APIRouter()
for module in (plans, customers, subscriptions, invoices, payments, ledger):
    router.include_router(module.router)
