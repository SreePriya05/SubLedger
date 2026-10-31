# SubLedger

A working billing backend for the course assignment. It manages plans, customers,
subscriptions, invoices, recorded payment attempts, and an append-only event ledger.
FastAPI provides Swagger documentation; SQLAlchemy persists data to SQLite.

Read [DESIGN.md](DESIGN.md) for the LLD: ERD, responsibilities, business-rule ownership,
patterns, transaction boundaries, and the two core workflows.

## Run locally

Requires Python 3.12 or newer. Run commands from the repository root.

**Windows PowerShell**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

**macOS / Linux**

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
cp .env.example .env
.venv/bin/python -m uvicorn app.main:app --reload
```

Open:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi.json
- Health check: http://localhost:8000/health

Tables and ledger protection triggers are created on startup. The default database
is `data/subledger.db`; data survives restarts. No seed data or credentials are required.
Environment variables override `.env`. See [.env.example](.env.example).

## Run with Docker

Requires Docker Engine / Docker Desktop running with Compose support.

```bash
docker compose up --build -d
docker compose logs -f api
docker compose down
```

The API uses port 8000. A named volume keeps the database after `down`.
`docker compose down --volumes` intentionally deletes the saved billing data.
The container runs as an unprivileged user and includes a database health check.

## Try a complete billing flow

With the API running, open a second terminal:

```powershell
.\.venv\Scripts\python.exe scripts/demo.py
```

On macOS/Linux use `.venv/bin/python scripts/demo.py`. The script creates a plan,
customer, subscription, and invoice, records a partial payment, a failed attempt,
and the final payment, then prints the paid invoice and all four ledger events.
It uses unique customer emails and payment references, so it can be rerun.

Alternatively use Swagger's **Try it out**, in this order (use returned IDs):

1. `POST /plans`

   ```json
   {"name":"Starter","description":"Monthly starter plan","billing_cycle":"monthly","price":"100.00","currency":"INR"}
   ```

2. `POST /customers`

   ```json
   {"name":"Asha","email":"asha@example.com","company_name":"Acme"}
   ```

3. `POST /subscriptions`

   ```json
   {"customer_id":1,"plan_id":1}
   ```

4. `POST /invoices`

   ```json
   {"subscription_id":1}
   ```

5. `POST /payments`

   ```json
   {"invoice_id":1,"amount":"40.00","currency":"INR","status":"success","provider_reference":"bank-attempt-001"}
   ```

6. Repeat payment with amount `"60.00"` and a new reference. Invoice becomes `paid`.
   Inspect `GET /customers/1/ledger` for the invoice and both payments.

To record a failed attempt on an open invoice use `"status":"failed"` and
`"failure_reason":"Bank declined"`. This records an event without increasing `amount_paid`.

## API list

The paths below match the assignment and appear in Swagger without a prefix.
The earlier `/api/v1` paths remain available as compatibility aliases (for example,
`/api/v1/plans`), but are hidden from Swagger to avoid duplicate operations.

| Method | Path | Purpose |
| --- | --- | --- |
| POST / GET | `/plans` | Create / list plans |
| GET / PATCH | `/plans/{id}` | Read / update name, description, price, billing cycle, currency, status |
| POST / GET | `/customers` | Create / list customers |
| GET / PATCH | `/customers/{id}` | Read / update customer |
| POST / GET | `/subscriptions` | Subscribe / list subscriptions |
| GET | `/subscriptions/{id}` | Subscription details |
| POST | `/subscriptions/{id}/activate` | Activate a cancelled subscription, checking plan/customer and duplicates |
| POST | `/subscriptions/{id}/cancel` | Immediate, repeatable cancellation |
| POST / GET | `/invoices` | Generate invoice / list invoices |
| GET | `/invoices/{id}` | Invoice with current paid amount and status |
| POST / GET | `/payments` | Record / list payment attempts |
| GET | `/payments/{id}` | Payment attempt details |
| GET | `/ledger` | List event ledger, optionally by customer or invoice |
| GET | `/customers/{id}/ledger` | Customer ledger; 404 for unknown customer |
| GET | `/health` | Database connectivity check (no API prefix) |

Lists return arrays ordered by ascending ID with `offset=0`, `limit=50` defaults
and a maximum limit of 100. Available filters are visible in Swagger:
plans/customers: `status`; subscriptions: `customer_id`, `plan_id`, `status`;
invoices: `customer_id`, `subscription_id`, `status`; payments: `invoice_id`, `status`;
ledger: `customer_id`, `invoice_id`. An unmatched list filter returns `[]`.

Success: `201` for creation, `200` for reads/updates/activation/cancellation.
Errors use `{"detail": ...}`: `404` missing entity, `409` duplicate/state/concurrency
conflict, `422` invalid input or payment amount/currency, `503` database unavailable.
Validation errors contain a list of locations and messages. A rejected operation
leaves no partial invoice, payment, or ledger records.

## Tests and quality checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

Tests use isolated temporary SQLite databases, including the production ledger
triggers. They cover plan prices, email uniqueness, inactive plans, duplicate active
subscriptions, activation/reactivation, cancellation, plan currency/cycle edits,
calendar billing periods, invoice price snapshots,
overlapping periods, partial/full/failed payments, overpayment, currency mismatch,
duplicate provider references, transaction rollback, ledger immutability, concurrent
payment updates, cancellation races, pagination, and missing resources.

GitHub Actions repeats tests and lint checks on pushes and pull requests.
`requirements*.txt` declare compatible ranges; `requirements*.lock` capture the
tested versions. Install from the lock files for repeatable setup.

## Assumptions and limitations

- The implementation follows the supplied description and assignment screenshots.
  See the requirement coverage table in DESIGN.md for implementation and test references.
  This is a backend project with Swagger documentation; a frontend is outside scope.
- Billing periods use calendar dates, inclusive start and exclusive end. Month ends
  clamp to the last valid date (January 31 -> February 28). Monthly, quarterly, and
  yearly cycles are supported. Timestamps are returned in UTC.
- Initial subscription periods are calculated at creation. There is no scheduler or
  automatic renewal. For subsequent invoices, explicitly send `period_start` and
  `period_end`; the subscription's initial current-period fields are not advanced.
  Custom periods charge one plan price, without proration. Overlaps are rejected.
- An invoice snapshots the plan's current price and currency **at invoice generation**.
  Later plan price/currency changes only affect future invoices. PATCH also supports
  billing cycle updates: new subscriptions use the new cycle, while existing stored
  periods remain unchanged. Inactive plans block creation and reactivation; existing
  active subscriptions can still be invoiced. Inactive customers cannot create or
  reactivate subscriptions.
- Invoices are generated as `issued`, default due date seven days from generation.
  The schema reserves `draft`, `overdue`, and `void` for extensions; this version has
  no transitions to them, automatic overdue job, or invoice deletion API.
- Cancellation is immediate, prevents new invoices, and keeps existing invoices
  payable. It causes no refund, credit, proration, or deletion.
- Subscriptions are active on creation. `POST /subscriptions/{id}/activate` reactivates
  a cancelled subscription only when its customer/plan are active and there is no
  other active subscription for that customer-plan pair. Repeated activation of an
  already active subscription is a no-op. Reactivation clears `cancelled_at`, retains
  original dates and financial history, and does not automatically invoice or renew.
- Supported currencies: INR, USD, EUR, GBP, AUD, CAD, SGD, AED, all modeled with two
  decimal places. Use decimal strings in requests; responses serialize money as
  strings. Amounts are positive, with at most 12 integer and 2 fractional digits.
- `provider_reference` is globally unique per **attempt**, including failures.
  Reusing it returns 409, rather than creating another attempt. A retry after failure
  needs a new reference. After an uncertain network result, list payments for the
  invoice and check the reference before retrying. This is duplicate protection,
  not an automatic idempotent replay response.
- Payments are simulated records; there is no gateway or verification of actual funds.
  Fully paid invoices reject further attempts. Failed attempts require a reason;
  their amounts may exceed the remaining balance because no money is applied.
- The ledger is an append-only **event journal**, not double-entry accounting.
  A failure entry's amount is the attempted amount, with zero balance effect.
  Do not sum all ledger amounts as a customer balance.
- SQLite is the supported database. Foreign keys, constraints, versioned writes, and
  triggers provide assignment-level safeguards; it is a single-node development
  backend. Schema initialization is for new databases, not a migration system.
  Existing schemas need deliberate migrations when models change. See DESIGN.md
  for extension notes.
- Authentication/RBAC, taxation, discounts, retries/schedulers, refunds, multi-tenancy,
  payment gateways, and production deployment are outside the assignment scope.

## Submission

Include this source, README, DESIGN, tests, requirements/lock files, Dockerfile, and
Compose file in your GitHub repository. Do not commit `.env`, `.venv`, `.tools`, or
`data/`. Run the demo and tests before submitting the repository link.
