from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.dependencies import Services
from app.errors import DomainError
from app.models import Invoice, LedgerEntry, PaymentAttempt, Subscription
from app.repositories import LedgerRepository
from app.schemas import InvoiceCreate, PaymentCreate
from app.services import add_months
from tests.conftest import payment_payload


@pytest.mark.parametrize("price", ["0", "-1", "1.001", "NaN", "Infinity", "1000000000000"])
def test_invalid_plan_prices(client, price):
    response = client.post(
        "/api/v1/plans",
        json={
            "name": "Bad",
            "price": price,
            "billing_cycle": "monthly",
        },
    )
    assert response.status_code == 422


def test_customer_email_is_unique_case_insensitively(client):
    data = {"name": "Asha", "email": "ASHA@example.com"}
    assert client.post("/api/v1/customers", json=data).status_code == 201
    data["email"] = "asha@example.com"
    assert client.post("/api/v1/customers", json=data).status_code == 409
    assert len(client.get("/api/v1/customers").json()) == 1


def test_inactive_plan_cannot_be_subscribed(client, billing):
    plan_id = billing["plan"]["id"]
    assert client.patch(f"/api/v1/plans/{plan_id}", json={"status": "inactive"}).status_code == 200
    response = client.post(
        "/api/v1/subscriptions",
        json={
            "plan_id": plan_id,
            "customer_id": billing["customer"]["id"],
        },
    )
    assert response.status_code == 409
    assert "inactive plan" in response.json()["detail"]


def test_duplicate_active_subscription_and_resubscribe_after_cancel(client, billing):
    data = {"plan_id": billing["plan"]["id"], "customer_id": billing["customer"]["id"]}
    assert client.post("/api/v1/subscriptions", json=data).status_code == 409
    path = f"/api/v1/subscriptions/{billing['subscription']['id']}/cancel"
    first = client.post(path).json()
    assert first["status"] == "cancelled"
    assert client.post(path).json()["cancelled_at"] == first["cancelled_at"]
    assert client.post("/api/v1/subscriptions", json=data).status_code == 201


def test_cancelled_subscription_cannot_generate_invoice(client, billing):
    subscription_id = billing["subscription"]["id"]
    client.post(f"/api/v1/subscriptions/{subscription_id}/cancel")
    response = client.post("/api/v1/invoices", json={"subscription_id": subscription_id})
    assert response.status_code == 409


def test_invoice_snapshots_plan_price_at_generation(client, billing):
    client.patch(f"/api/v1/plans/{billing['plan']['id']}", json={"price": "250.00"})
    old = client.get(f"/api/v1/invoices/{billing['invoice']['id']}").json()
    assert Decimal(old["amount_due"]) == Decimal("100.00")
    new = client.post(
        "/api/v1/invoices",
        json={
            "subscription_id": billing["subscription"]["id"],
            "period_start": "2026-02-28",
            "period_end": "2026-03-31",
        },
    )
    assert new.status_code == 201
    assert Decimal(new.json()["amount_due"]) == Decimal("250.00")


def test_invoice_generation_creates_traceable_ledger_event(client, billing):
    invoice = billing["invoice"]
    ledger = client.get(f"/api/v1/customers/{billing['customer']['id']}/ledger").json()
    assert len(ledger) == 1
    assert ledger[0]["entry_type"] == "invoice_created"
    assert ledger[0]["reference_id"] == f"invoice:{invoice['id']}"
    assert ledger[0]["invoice_id"] == invoice["id"]


@pytest.mark.parametrize(
    "start,end",
    [
        (None, None),
        ("2026-02-01", "2026-03-01"),
        ("2026-01-01", "2026-04-01"),
    ],
)
def test_duplicate_or_overlapping_period_rejected(client, billing, start, end):
    body = {"subscription_id": billing["subscription"]["id"]}
    if start:
        body.update(period_start=start, period_end=end)
    response = client.post("/api/v1/invoices", json=body)
    assert response.status_code in {409, 422}
    assert len(client.get("/api/v1/invoices").json()) == 1
    assert len(client.get("/api/v1/ledger").json()) == 1


@pytest.mark.parametrize(
    "fields",
    [
        {"period_start": "2026-02-01"},
        {"period_start": "2026-03-01", "period_end": "2026-02-01"},
        {"period_start": "2025-01-01", "period_end": "2025-02-01"},
    ],
)
def test_invalid_invoice_period(client, billing, fields):
    response = client.post(
        "/api/v1/invoices",
        json={
            "subscription_id": billing["subscription"]["id"],
            **fields,
        },
    )
    assert response.status_code == 422


def test_partial_then_full_payment(client, billing):
    invoice_id = billing["invoice"]["id"]
    first = client.post("/api/v1/payments", json=payment_payload(invoice_id))
    assert first.status_code == 201
    assert first.json()["invoice"]["status"] == "partially_paid"
    assert Decimal(first.json()["invoice"]["amount_paid"]) == Decimal("40.00")
    second = client.post(
        "/api/v1/payments",
        json=payment_payload(invoice_id, amount="60.00", provider_reference="provider-attempt-2"),
    )
    assert second.status_code == 201
    assert second.json()["invoice"]["status"] == "paid"
    assert Decimal(second.json()["invoice"]["amount_paid"]) == Decimal("100.00")
    ledger = client.get("/api/v1/ledger").json()
    assert [entry["entry_type"] for entry in ledger] == [
        "invoice_created",
        "payment_success",
        "payment_success",
    ]
    assert ledger[1]["reference_id"] == f"payment_attempt:{first.json()['payment_attempt']['id']}"


def test_failed_payment_has_no_financial_effect(client, billing):
    invoice_id = billing["invoice"]["id"]
    response = client.post(
        "/api/v1/payments",
        json=payment_payload(
            invoice_id,
            status="failed",
            failure_reason="Bank declined",
        ),
    )
    assert response.status_code == 201
    assert response.json()["invoice"]["status"] == "issued"
    assert Decimal(response.json()["invoice"]["amount_paid"]) == Decimal("0")
    assert response.json()["payment_attempt"]["failure_reason"] == "Bank declined"
    assert client.get("/api/v1/ledger").json()[-1]["entry_type"] == "payment_failure"


def test_overpayment_rejected_without_attempt_or_ledger(client, billing):
    invoice_id = billing["invoice"]["id"]
    client.post("/api/v1/payments", json=payment_payload(invoice_id))
    response = client.post(
        "/api/v1/payments",
        json=payment_payload(invoice_id, amount="60.01", provider_reference="too-much"),
    )
    assert response.status_code == 422
    assert len(client.get("/api/v1/payments").json()) == 1
    assert len(client.get("/api/v1/ledger").json()) == 2


def test_duplicate_provider_reference_does_not_double_count(client, billing):
    data = payment_payload(billing["invoice"]["id"])
    assert client.post("/api/v1/payments", json=data).status_code == 201
    assert client.post("/api/v1/payments", json=data).status_code == 409
    invoice = client.get(f"/api/v1/invoices/{data['invoice_id']}").json()
    assert Decimal(invoice["amount_paid"]) == Decimal("40.00")
    assert len(client.get("/api/v1/payments").json()) == 1


@pytest.mark.parametrize(
    "fields",
    [
        {"currency": "USD"},
        {"amount": "0"},
        {"amount": "-10"},
        {"amount": "0.001"},
        {"status": "failed"},
        {"failure_reason": "cannot be set on success"},
        {"provider_reference": "  "},
        {"amount": "NaN"},
    ],
)
def test_invalid_payment_rejected(client, billing, fields):
    response = client.post(
        "/api/v1/payments", json=payment_payload(billing["invoice"]["id"], **fields)
    )
    assert response.status_code == 422
    assert client.get("/api/v1/payments").json() == []


def test_paid_invoice_cannot_receive_more_attempts(client, billing):
    invoice_id = billing["invoice"]["id"]
    client.post("/api/v1/payments", json=payment_payload(invoice_id, amount="100"))
    response = client.post(
        "/api/v1/payments", json=payment_payload(invoice_id, provider_reference="extra-attempt")
    )
    assert response.status_code == 409


def test_ledger_failure_rolls_back_entire_payment(client, billing, monkeypatch):
    def fail_append(*args, **kwargs):
        raise DomainError("Simulated ledger failure")

    monkeypatch.setattr(LedgerRepository, "append", fail_append)
    response = client.post("/api/v1/payments", json=payment_payload(billing["invoice"]["id"]))
    assert response.status_code == 409
    assert client.get("/api/v1/payments").json() == []
    invoice = client.get(f"/api/v1/invoices/{billing['invoice']['id']}").json()
    assert Decimal(invoice["amount_paid"]) == Decimal("0")
    assert invoice["status"] == "issued"
    assert len(client.get("/api/v1/ledger").json()) == 1


def test_ledger_failure_rolls_back_invoice(client, billing, monkeypatch):
    def fail_append(*args, **kwargs):
        raise DomainError("Simulated ledger failure")

    monkeypatch.setattr(LedgerRepository, "append", fail_append)
    response = client.post(
        "/api/v1/invoices",
        json={
            "subscription_id": billing["subscription"]["id"],
            "period_start": "2026-03-01",
            "period_end": "2026-04-01",
        },
    )
    assert response.status_code == 409
    assert len(client.get("/api/v1/invoices").json()) == 1


@pytest.mark.parametrize(
    "action", ["UPDATE ledger_entries SET amount=1", "DELETE FROM ledger_entries"]
)
def test_database_blocks_ledger_mutations(session_factory, billing, action):
    with session_factory() as session:
        with pytest.raises(IntegrityError, match="append-only"):
            session.execute(text(action))
        session.rollback()
        assert session.scalar(select(func.count()).select_from(LedgerEntry)) == 1


def test_orm_blocks_ledger_mutation(session_factory, billing):
    with session_factory() as session:
        entry = session.get(LedgerEntry, 1)
        entry.description = "tampered"
        with pytest.raises(ValueError, match="append-only"):
            session.flush()


def test_concurrent_payments_cannot_lose_update(session_factory, billing):
    invoice_id = billing["invoice"]["id"]
    with session_factory() as first, session_factory() as second:
        # Hold references so both sessions retain the same initial invoice version.
        old_first = first.get(Invoice, invoice_id)
        old_second = second.get(Invoice, invoice_id)
        assert old_first.version == old_second.version
        Services(first).payments.record_payment(
            PaymentCreate(
                **payment_payload(invoice_id, amount="60.00", provider_reference="concurrent-1")
            )
        )
        first.commit()
        with pytest.raises(StaleDataError):
            Services(second).payments.record_payment(
                PaymentCreate(
                    **payment_payload(invoice_id, amount="60.00", provider_reference="concurrent-2")
                )
            )
        second.rollback()
    with session_factory() as session:
        assert session.get(Invoice, invoice_id).amount_paid == Decimal("60.00")
        assert session.scalar(select(func.count()).select_from(PaymentAttempt)) == 1
        assert session.scalar(select(func.count()).select_from(LedgerEntry)) == 2


def test_cancellation_cannot_race_invoice_generation(session_factory, billing):
    subscription_id = billing["subscription"]["id"]
    with session_factory() as first, session_factory() as second:
        stale = second.get(Subscription, subscription_id)
        Services(first).subscriptions.cancel(subscription_id)
        first.commit()
        assert stale.status == "active"
        with pytest.raises(StaleDataError):
            Services(second).invoices.generate_invoice(
                InvoiceCreate(
                    subscription_id=subscription_id,
                    period_start=date(2026, 3, 1),
                    period_end=date(2026, 4, 1),
                )
            )
        second.rollback()


def test_missing_entities_return_404(client):
    for resource in ("plans", "customers", "subscriptions", "invoices", "payments"):
        assert client.get(f"/api/v1/{resource}/999").status_code == 404
    assert client.post("/api/v1/invoices", json={"subscription_id": 999}).status_code == 404
    assert client.post("/api/v1/payments", json=payment_payload(999)).status_code == 404
    assert client.get("/api/v1/customers/999/ledger").status_code == 404


def test_pagination_and_filters(client, billing):
    assert client.get("/api/v1/plans?status=inactive").json() == []
    assert client.get("/api/v1/invoices?customer_id=999").json() == []
    assert client.get("/api/v1/ledger?invoice_id=999").json() == []
    assert client.get("/api/v1/plans?offset=1&limit=1").json() == []
    assert client.get("/api/v1/plans?limit=101").status_code == 422


def test_null_patch_and_unknown_fields_are_rejected(client, billing):
    path = f"/api/v1/plans/{billing['plan']['id']}"
    assert client.patch(path, json={"price": None}).status_code == 422
    assert client.patch(path, json={"unknown_field": "USD"}).status_code == 422
    assert client.patch(path, json={"description": None}).status_code == 200


@pytest.mark.parametrize(
    "start,months,end",
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),
        (date(2024, 2, 29), 12, date(2025, 2, 28)),
        (date(2026, 11, 30), 3, date(2027, 2, 28)),
    ],
)
def test_calendar_billing_periods(start, months, end):
    assert add_months(start, months) == end
