import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db import build_engine, initialize_database
from app.dependencies import get_session
from app.main import app


@pytest.fixture
def session_factory(tmp_path):
    engine = build_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    initialize_database(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def client(session_factory, monkeypatch):
    def test_session():
        with session_factory() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    app.dependency_overrides[get_session] = test_session
    monkeypatch.setattr("app.main.engine", session_factory.kw["bind"])
    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def billing(client):
    def create(path, body):
        response = client.post(f"/api/v1/{path}", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    plan = create(
        "plans",
        {
            "name": "Starter",
            "price": "100.00",
            "billing_cycle": "monthly",
            "currency": "INR",
        },
    )
    customer = create("customers", {"name": "Asha", "email": "asha@example.com"})
    subscription = create(
        "subscriptions",
        {
            "plan_id": plan["id"],
            "customer_id": customer["id"],
            "start_date": "2026-01-31",
        },
    )
    invoice = create("invoices", {"subscription_id": subscription["id"]})
    return {"plan": plan, "customer": customer, "subscription": subscription, "invoice": invoice}


def payment_payload(invoice_id, **overrides):
    payload = {
        "invoice_id": invoice_id,
        "amount": "40.00",
        "currency": "INR",
        "status": "success",
        "provider_reference": "provider-attempt-1",
    }
    payload.update(overrides)
    return payload
