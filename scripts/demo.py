"""Run against a running API: python scripts/demo.py [--base-url http://localhost:8000]."""

import argparse
import json
import urllib.error
import urllib.request
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description="Demonstrate SubLedger's core billing flow")
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    suffix = uuid4().hex[:12]

    def request(path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            f"{args.base_url.rstrip('/')}/{path}",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"API error {exc.code}: {exc.read().decode()}") from exc
        except urllib.error.URLError as exc:
            raise SystemExit(f"Cannot reach API. Start uvicorn first. {exc.reason}") from exc

    plan = request(
        "plans",
        {
            "name": "Demo Starter",
            "billing_cycle": "monthly",
            "price": "100.00",
            "currency": "INR",
        },
    )
    customer = request(
        "customers", {"name": "Demo Customer", "email": f"demo-{suffix}@example.com"}
    )
    subscription = request("subscriptions", {"customer_id": customer["id"], "plan_id": plan["id"]})
    invoice = request("invoices", {"subscription_id": subscription["id"]})
    for index, (amount, status, reason) in enumerate(
        [
            ("40.00", "success", None),
            ("10.00", "failed", "Bank declined"),
            ("60.00", "success", None),
        ]
    ):
        result = request(
            "payments",
            {
                "invoice_id": invoice["id"],
                "amount": amount,
                "currency": "INR",
                "status": status,
                "failure_reason": reason,
                "provider_reference": f"demo-{suffix}-{index}",
            },
        )
        print(
            f"{status} {amount}: invoice={result['invoice']['status']}, "
            f"amount_paid={result['invoice']['amount_paid']}"
        )
    ledger = request(f"customers/{customer['id']}/ledger")
    assert result["invoice"]["status"] == "paid"
    assert len(ledger) == 4
    print(json.dumps({"invoice": result["invoice"], "ledger": ledger}, indent=2))


if __name__ == "__main__":
    main()
