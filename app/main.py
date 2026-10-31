import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm.exc import StaleDataError

from app.config import get_settings
from app.db import engine, initialize_database
from app.errors import DomainError
from app.routes import router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app):
    initialize_database(engine)
    yield
    engine.dispose()


app = FastAPI(
    title=get_settings().app_name,
    description=(
        "Assignment billing backend: plans, customers, subscriptions, invoices, "
        "payment recording and an append-only event ledger. Amounts use decimal strings."
    ),
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(router)
# Preserve URLs used by the initial implementation; Swagger shows assignment paths.
app.include_router(router, prefix="/api/v1", include_in_schema=False)


@app.exception_handler(DomainError)
async def domain_error(_request: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(IntegrityError)
async def integrity_error(_request: Request, _exc: IntegrityError):
    return JSONResponse(
        status_code=409,
        content={"detail": "Operation conflicts with an existing record or database constraint"},
    )


@app.exception_handler(StaleDataError)
async def concurrent_update(_request: Request, _exc: StaleDataError):
    return JSONResponse(
        status_code=409,
        content={"detail": "Record changed concurrently; fetch its latest state before retrying"},
    )


@app.exception_handler(OperationalError)
async def database_unavailable(_request: Request, exc: OperationalError):
    logger.error("Database operation failed", exc_info=exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "Database temporarily unavailable; retry later"},
        headers={"Retry-After": "1"},
    )


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError):
    # Omit raw input/context so invalid Decimal NaN and ValueError objects remain JSON-safe.
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
                for error in exc.errors()
            ]
        },
    )


@app.get("/health", tags=["Health"])
def health():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}
