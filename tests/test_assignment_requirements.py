from decimal import Decimal

import pytest

from app.dependencies import Services
from app.errors import DomainError
from app.schemas import PlanCreate
from tests.conftest import payment_payload


def test_assignment_endpoints_and_versioned_aliases(client):
    plan = client.post(
        "/plans",
        json={
            "name": "Assignment plan",
            "billing_cycle": "monthly",
            "price": "100.00",
        },
    )
    assert plan.status_code == 201
    plan_id = plan.json()["id"]
    assert client.get("/plans").json() == client.get("/api/v1/plans").json()
    assert client.patch(f"/plans/{plan_id}", json={"status": "inactive"}).status_code == 200
    customer = client.post("/customers", json={"name": "Asha", "email": "asha@example.com"})
    assert customer.status_code == 201
    paths = client.get("/openapi.json").json()["paths"]
    assert {"get", "post"} <= paths["/plans"].keys()
    assert "patch" in paths["/plans/{plan_id}"]
    assert "post" in paths["/customers"]
    assert not any(path.startswith("/api/v1") for path in paths)


def test_activation_restores_same_subscription_and_preserves_history(client, billing):
    subscription_id = billing["subscription"]["id"]
    client.post(f"/subscriptions/{subscription_id}/cancel")
    response = client.post(f"/subscriptions/{subscription_id}/activate")
    assert response.status_code == 200
    active = response.json()
    assert active["status"] == "active"
    assert active["cancelled_at"] is None
    assert active["start_date"] == billing["subscription"]["start_date"]
    assert active["current_period_start"] == billing["subscription"]["current_period_start"]
    assert active["current_period_end"] == billing["subscription"]["current_period_end"]
    assert client.post(f"/subscriptions/{subscription_id}/activate").json() == active
    assert len(client.get("/subscriptions").json()) == 1
    assert client.get(f"/invoices/{billing['invoice']['id']}").json() == billing["invoice"]
    # Activation does not reset the invoice history or allow a period to be billed twice.
    assert client.post("/invoices", json={"subscription_id": subscription_id}).status_code == 409
    assert (
        client.post(
            "/invoices",
            json={
                "subscription_id": subscription_id,
                "period_start": "2026-03-01",
                "period_end": "2026-04-01",
            },
        ).status_code
        == 201
    )


@pytest.mark.parametrize("resource", ["plans", "customers"])
def test_activation_requires_active_customer_and_plan(client, billing, resource):
    subscription_id = billing["subscription"]["id"]
    client.post(f"/subscriptions/{subscription_id}/cancel")
    entity_id = billing["plan" if resource == "plans" else "customer"]["id"]
    assert client.patch(f"/{resource}/{entity_id}", json={"status": "inactive"}).status_code == 200
    assert client.post(f"/subscriptions/{subscription_id}/activate").status_code == 409
    cancelled = client.get(f"/subscriptions/{subscription_id}").json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancelled_at"] is not None


def test_activation_cannot_duplicate_another_active_subscription(client, billing):
    subscription_id = billing["subscription"]["id"]
    client.post(f"/subscriptions/{subscription_id}/cancel")
    replacement = client.post(
        "/subscriptions",
        json={
            "customer_id": billing["customer"]["id"],
            "plan_id": billing["plan"]["id"],
        },
    )
    assert replacement.status_code == 201
    assert client.post(f"/subscriptions/{subscription_id}/activate").status_code == 409
    assert client.get(f"/subscriptions/{subscription_id}").json()["status"] == "cancelled"
    active = client.get("/subscriptions?status=active").json()
    assert [item["id"] for item in active] == [replacement.json()["id"]]


def test_activate_missing_subscription(client):
    assert client.post("/subscriptions/999/activate").status_code == 404


def test_plan_cycle_currency_and_price_updates_preserve_existing_invoices(client, billing):
    plan_id = billing["plan"]["id"]
    response = client.patch(
        f"/plans/{plan_id}",
        json={
            "billing_cycle": "quarterly",
            "currency": "USD",
            "price": "250.00",
        },
    )
    assert response.status_code == 200
    assert response.json()["billing_cycle"] == "quarterly"
    assert response.json()["currency"] == "USD"
    old = client.get(f"/invoices/{billing['invoice']['id']}").json()
    assert old["currency"] == "INR"
    assert Decimal(old["amount_due"]) == Decimal("100.00")
    payment = client.post("/payments", json=payment_payload(old["id"]))
    assert payment.status_code == 201
    assert payment.json()["invoice"]["currency"] == "INR"
    new = client.post(
        "/invoices",
        json={
            "subscription_id": billing["subscription"]["id"],
            "period_start": "2026-03-01",
            "period_end": "2026-06-01",
        },
    )
    assert new.status_code == 201
    assert new.json()["currency"] == "USD"
    assert Decimal(new.json()["amount_due"]) == Decimal("250.00")
    assert (
        client.get(f"/subscriptions/{billing['subscription']['id']}").json()
        == billing["subscription"]
    )
    customer = client.post("/customers", json={"name": "New", "email": "new@example.com"}).json()
    subscription = client.post(
        "/subscriptions",
        json={
            "customer_id": customer["id"],
            "plan_id": plan_id,
            "start_date": "2026-01-31",
        },
    )
    assert subscription.status_code == 201
    assert subscription.json()["current_period_end"] == "2026-04-30"
    ledger = client.get("/ledger").json()
    assert [entry["currency"] for entry in ledger] == ["INR", "INR", "USD"]


@pytest.mark.parametrize(
    "fields",
    [
        {"price": "0"},
        {"billing_cycle": "weekly"},
        {"currency": "INVALID"},
        {"status": "deleted"},
        {"billing_cycle": None},
        {"currency": None},
    ],
)
def test_invalid_plan_edits_leave_plan_unchanged(client, billing, fields):
    path = f"/plans/{billing['plan']['id']}"
    assert client.patch(path, json=fields).status_code == 422
    assert client.get(path).json() == billing["plan"]


@pytest.mark.parametrize(
    "fields",
    [
        {"price": Decimal("0")},
        {"billing_cycle": "weekly"},
        {"status": "deleted"},
    ],
)
def test_plan_service_validates_non_http_callers(session_factory, fields):
    # model_construct intentionally bypasses schema checks to exercise service ownership.
    data = PlanCreate.model_construct(
        **{
            "name": "Invalid",
            "price": Decimal("100"),
            "billing_cycle": "monthly",
            "currency": "INR",
            "status": "active",
            **fields,
        }
    )
    with session_factory() as session:
        services = Services(session)
        # Intentionally malformed enum fields emit a serialization warning before revalidation.
        with (
            pytest.warns(UserWarning, match="Pydantic serializer warnings"),
            pytest.raises(DomainError) as error,
        ):
            services.plans.create(data)
        assert error.value.status_code == 422
        assert services.plan_repo.list() == []
