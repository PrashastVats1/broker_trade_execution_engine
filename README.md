# Kalpi Portfolio Trade Execution Engine

A Python/FastAPI backend that accepts a first-time portfolio or explicit
rebalance instructions, executes normalized orders through a broker adapter,
tracks uncertain and partial outcomes, and notifies the caller.

This is an **assignment demonstration**, not production-ready real-money
infrastructure. Live broker execution is disabled by default.

## What is implemented

- First-time portfolio: verify holdings are empty, then create BUY orders.
- Explicit rebalance: execute supplied BUY/SELL instructions without computing
  a delta.
- Durable executions and orders, request idempotency, partial failure, and
  explicit reconciliation.
- `UNKNOWN` order and `RECONCILIATION_REQUIRED` execution states when a broker
  may have accepted an order but the response/status is unavailable.
- Mock broker for deterministic local and CI use.
- Real HTTP-contract adapters for Zerodha, DhanHQ, Angel One, Groww, and
  Upstox.
- Console and optional webhook notifications.
- PostgreSQL, Alembic, Docker, OpenAPI, tests, linting, and strict type checks.
- A point-in-time-correct multi-frequency financial data platform design.

No frontend is included. Backend correctness and documentation were prioritized.

## Broker support status

All five real adapters are **contract-tested, not live-certified**. Tests use
captured shapes from current official documentation with `httpx.MockTransport`;
they do not fabricate a successful live trade.

- **Upstox:** OAuth authorization code, holdings, instrument search, V3 place,
  status/tag lookup, and cancellation. Official order sandbox exists.
- **Zerodha:** Kite redirect/checksum exchange, instrument CSV, holdings,
  place/history/cancel, and HTTP 428 delivery authorization handling.
- **Groww:** API key token generation, official instrument CSV, holdings,
  place, reference/order status, and cancellation.
- **Angel One:** SmartAPI daily login contract, instrument master, holdings,
  place, individual status, and cancellation. Instrument-master availability is
  a documented operational risk.
- **DhanHQ:** consent/token contract, instrument CSV/security IDs, holdings,
  place, order/correlation status, and cancellation.
- **Mock:** fully runnable locally; never represented as a real integration.

FYERS and Indiabulls were excluded because their complete current
broker-specific REST contracts could not be independently verified from
accessible official documentation. See
[broker research](docs/broker-integrations.md) for sources, dates, auth
lifecycles, limits, static-IP rules, instrument identity, sandbox availability,
and DDPI/eDIS constraints.

## Architecture

The project is a modular monolith:

```text
FastAPI routes
    -> ExecutionService
        -> ExecutionRepository -> PostgreSQL
        -> BrokerRegistry -> BrokerAdapter -> broker API
        -> NotificationService -> console/webhook
```

The execution engine works only with normalized holdings, instruments, order
requests, and results. Broker response types never enter core logic. Adding a
sixth broker requires a new `BrokerAdapter`, registry/configuration entry,
official-source documentation, and contract tests—no execution-service change.

Detailed design:

- [Trade execution architecture](docs/trade-execution-architecture.md)
- [Broker integration research](docs/broker-integrations.md)
- [Multi-frequency data platform](docs/multi-frequency-data-platform.md)

## Execution safety

`POST /api/v1/executions` requires `Idempotency-Key`. The database stores a
SHA-256 hash of the Pydantic JSON payload, excluding `confirm_live`, under a
unique constraint. Same key/same payload returns the existing execution; same
key/different payload returns HTTP 409.

The service persists `SUBMITTING` before calling a broker and does not hold a
database transaction open over the network. Current holdings and status reads
opt into at most three attempts, with jitter. Numeric `Retry-After` is honored
only on a 429 from those reads, and only up to five seconds. Order placement
uses one attempt and is never blindly retried. A submission timeout becomes
`UNKNOWN`; reconciliation uses the broker order ID or, where the verified
contract provides it, the correlation field.
Transport failures, 5xx responses, malformed placement responses, and failure
to persist a broker acknowledgement are also treated as ambiguous rather than
as proof that an order failed.

Once any order becomes `UNKNOWN`, the engine stops that execution. Remaining
`PENDING` orders become `SKIPPED` and are never submitted. The execution remains
`RECONCILIATION_REQUIRED`. This is intentional: after losing certainty about an
external financial side effect, the service must not create additional
dependent financial side effects.

This is not an exactly-once guarantee. Network partitions and external broker
APIs make exactly-once execution impossible without broker-provided semantics
that these APIs do not promise.

Orders execute sequentially in request order. This is deterministic and
conservative for broker limits, but it is not smart order routing. Market-order
defaults are visible in the API and still carry slippage risk.

## API

FastAPI serves Swagger UI at `/docs` and OpenAPI JSON at `/openapi.json`.

Main endpoints:

```text
GET  /health
GET  /ready
GET  /api/v1/brokers
GET  /api/v1/brokers/{broker}/status
GET  /api/v1/brokers/{broker}/auth/start
POST /api/v1/brokers/{broker}/auth/complete
POST /api/v1/executions
GET  /api/v1/executions/{execution_id}
GET  /api/v1/executions/{execution_id}/orders
POST /api/v1/executions/{execution_id}/reconcile
```

Example mock rebalance:

```bash
curl -X POST http://localhost:8000/api/v1/executions \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-rebalance-001' \
  -d '{
    "broker": "mock",
    "workflow": "REBALANCE",
    "orders": [
      {"symbol": "RELIANCE", "side": "SELL", "quantity": 5},
      {"symbol": "INFY", "side": "BUY", "quantity": 10},
      {"symbol": "TCS", "side": "SELL", "quantity": 2}
    ]
  }'
```

First-time input:

```json
{
  "broker": "mock",
  "workflow": "FIRST_TIME",
  "portfolio": [
    {"symbol": "RELIANCE", "quantity": 10},
    {"symbol": "TCS", "quantity": 5}
  ]
}
```

Defaults are explicit in the schema: NSE, cash equity, delivery product, market
order, and DAY validity. A real adapter must resolve one exact current
instrument and rejects ambiguity.

## Local development

Requirements: Python 3.12+.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check app tests
.venv/bin/mypy app
DATABASE_URL=sqlite+aiosqlite:///./kalpi.db .venv/bin/uvicorn app.main:app
```

SQLite is supported for fast local tests. PostgreSQL is the deployment database
because idempotency, durable state, constraints, and concurrent transactions
are part of the safety model.

## Docker

Copy only configuration keys you need; never insert credentials into an image:

```bash
cp .env.example .env
docker compose up --build
curl http://localhost:8000/health
docker compose down
```

Compose starts PostgreSQL, waits for health, applies Alembic migrations, and
starts the API on port 8000. The bonus frontend is served at
<http://localhost:8080>. Live trading remains disabled.

## Bonus frontend

The optional React/Vite interface exercises the existing execution API. It does
not place live trades or certify a real broker.

Only Mock Broker is usable for execution right now. **Execute portfolio** stays
disabled until Mock is selected and connected. Zerodha, DhanHQ, Angel One,
Groww, and Upstox are contract-tested adapters; choosing one in the UI does not
configure a live session, so Connect stays "Not configured" and execution does
not run.

```bash
docker compose up --build
```

Open <http://localhost:8080>. For local frontend development instead:

```bash
cd frontend
npm install
npm run dev
```

That development server uses `http://localhost:5173` and calls
`VITE_API_BASE_URL`, which defaults to `http://localhost:8000`. The API allows
those two local origins only.

Demo flow:

1. Start Compose.
2. Open the frontend.
3. Select Mock Broker. Execution only works with Mock.
4. Upload `frontend/sample-portfolio.csv` and review the rows.
5. Click Connect broker. Mock requires no credentials. Wait until the status says Connected.
6. Click Execute portfolio.
7. Read each order result.

`UNKNOWN` means the broker outcome is ambiguous. The screen says no automatic
resubmission occurred, and later orders marked `SKIPPED` were not sent.
Reconcile calls the backend reconciliation endpoint; it does not execute the
portfolio again.

The five real adapters remain contract-tested, not live-certified. Live trading
stays disabled unless the backend operator separately enables it. `confirm_live`
is not an authentication control and is not exposed by this interface.

## Configuration and real brokers

Configuration is read from environment variables; see `.env.example`. Tokens,
API secrets, authorization headers, PINs, OTPs, and TOTP seeds must not be
committed or logged.

To make a live call, the operator must intentionally set
`ALLOW_LIVE_TRADING=true`, configure one broker, satisfy its static-IP/app/DDPI
requirements, and send `"confirm_live": true`. These switches prevent accidental
live execution; they do not authenticate or authorize a user and do not make
the project production-ready. Production live execution requires authenticated,
authorized users and account-scoped policy. The normal local/demo path is the
MockBroker and requires no real broker credentials.

OAuth/consent tokens are held only in process memory in this assignment. A
restart loses callback-generated tokens. Production requires authenticated user
identity and a KMS-backed encrypted credential store.

## Tests

The suite includes:

- first-time, multiple buys, multiple sells, and mixed rebalances;
- quantity/symbol validation and exact instrument resolution;
- partial rejection, including a first-time portfolio, and notification failure;
- request idempotency and payload conflict;
- timeout after possible acceptance, failed status lookup, and an
  executed/unknown/skipped three-order sequence;
- Upstox HTTP 503 and malformed placement responses classified as unknown;
- authentication, rate-limit, and delivery-authorization responses treated as
  explicit outcomes rather than ambiguous submissions;
- all five real adapter request/response mappings;
- API/OpenAPI and end-to-end mock behavior.

Live tests are deliberately not part of the default suite. Upstox sandbox tests
can be added as credential-gated tests without changing contract tests.

## Dependency choices

- **FastAPI/Pydantic:** explicit validated API contracts and generated OpenAPI.
- **SQLAlchemy/Alembic/PostgreSQL:** portable transactions, constraints, and
  migrations for execution state.
- **httpx:** async timeouts plus deterministic transport-level contract tests.
  Broker SDKs were not used because direct official REST mappings are easier to
  audit and normalize consistently.
- **pytest:** fast failure-focused unit and API testing.

No queue, Kafka, Kubernetes, event sourcing, CQRS, or microservice split is used
for Problem 1. A durable worker would be a production hardening step, but is not
needed to demonstrate the bounded synchronous assignment flow.

## Known limitations and production hardening

- Real adapters have not placed live orders.
- In-process execution is not crash-proof. Reconciliation can investigate
  `SUBMITTING`, `UNKNOWN`, and acknowledged open orders. It does not resume
  `PENDING` orders left by a crash before submission. Angel One cannot resolve
  a `SUBMITTING` order without its broker order ID. Replaying the same
  idempotency key returns that execution and does not submit it again.
  Production should use a durable worker/outbox.
- Broker postbacks/WebSockets are not consumed.
- Tokens are not persisted in an encrypted credential vault.
- End-user authentication, authorization, tenancy, and audit retention are not
  implemented.
- Delivery TPIN/OTP remains a broker-controlled human step.
- Instrument masters need scheduled atomic refresh and stale-data monitoring.
- Rate policies are documented and calls are sequential, but a distributed
  per-account limiter is required when horizontally scaled.
- Static egress IP, HTTPS, secret manager, alerting, runbooks, and controlled
  broker certification are mandatory before real money.

## Repository map

```text
app/                 domain, orchestration, persistence, API, adapters
frontend/            bonus React execution interface
tests/               core, API, and broker contract tests
docs/                assignment sources, research, and architecture
migrations/          Alembic schema history
Dockerfile
docker-compose.yml
pyproject.toml
FINAL_CHECKLIST.md
```

The immutable assignment source is
[`docs/assignment_requirements.md`](docs/assignment_requirements.md).
