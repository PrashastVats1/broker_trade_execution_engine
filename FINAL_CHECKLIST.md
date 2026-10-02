# Final Assignment Checklist

Verified on **2 October 2026**.

## Problem 1

- [x] Python 3.12 and FastAPI backend.
- [x] First-time portfolio validates empty holdings and creates BUY orders.
- [x] Explicit BUY/SELL rebalance instructions execute without delta logic.
- [x] Broker-independent domain models and `BrokerAdapter` interface.
- [x] Fully runnable `MockBrokerAdapter`.
- [x] Five real API-contract adapters: Upstox, Zerodha, Groww, Angel One,
  DhanHQ.
- [x] Each real adapter has current official sources and verification date in
  `docs/broker-integrations.md`.
- [x] FYERS and Indiabulls are excluded rather than implemented from uncertain
  contracts.
- [x] Exact instrument resolution rejects zero/multiple matches.
- [x] Durable execution/order IDs and required idempotency key.
- [x] Same-key/different-payload conflict handling.
- [x] Order states include submitted, open, partial, executed, rejected,
  cancelled, failed, and unknown.
- [x] Ambiguous submission is not retried and becomes
  `RECONCILIATION_REQUIRED`.
- [x] Explicit reconciliation endpoint.
- [x] Order placement is not retried. Current safe reads opt into bounded retry.
- [x] Partial execution summary.
- [x] Console and optional webhook notification abstraction.
- [x] Notification failure does not alter trade outcome.
- [x] PostgreSQL schema and Alembic migration.
- [x] FastAPI OpenAPI documentation and explicit Pydantic schemas.
- [x] Environment-based configuration and `.env.example`.
- [x] Live execution disabled by default and requires two explicit switches.
- [x] No frontend; backend quality was prioritized.

## Broker truthfulness

- [x] Mock and real adapters are clearly separated.
- [x] Real adapters are labelled **contract-tested, not live-certified**.
- [x] No live trade, benchmark, sandbox pass, or production-readiness claim.
- [x] Auth lifecycle, static IP, limits, instruments, DDPI/eDIS, and sandbox
  caveats are documented.
- [x] No API keys, access tokens, secrets, authorization headers, PINs, OTPs, or
  TOTP seeds committed.

## Problem 2

- [x] `docs/multi-frequency-data-platform.md` is 1,229 words.
- [x] Covers NSE+BSE, 5,000+ symbols, ticks, EOD, quarterly, and annual data.
- [x] Distinguishes economic period, announcement, source availability,
  ingestion, and system-valid time.
- [x] Models immutable corrections/restatements and late-arriving data.
- [x] Gives a concrete point-in-time EPS-TTM/P/E join.
- [x] Covers hot/warm/cold retention, OHLC downsampling, and raw expiry.
- [x] Covers tick-triggered and fundamental-triggered compute.
- [x] Separates live under-200 ms and historical ~750-point API paths.
- [x] Documents versioned cache invalidation and failure behavior.
- [x] Justifies NATS JetStream, ClickHouse, PostgreSQL, Redis, and Parquet by
  workload and identifies simpler/alternative choices.
- [x] Includes a Mermaid architecture diagram for both P/E paths.

## Actual verification

Commands run successfully on 2 October 2026:

```text
.venv/bin/pytest
58 passed

.venv/bin/ruff check app tests migrations
All checks passed

.venv/bin/mypy app
Success: no issues found in 14 source files
```

The automated suite uses SQLite. It does not by itself prove PostgreSQL
constraints or concurrency. The same-day Compose rerun rebuilt the API,
reported both containers healthy, and returned `/health`, `/ready`, and a
mock execution `201`. Alembic connected to PostgreSQL and found the existing
volume already at head, so it did not repeat the `0001 → 0002` upgrade log.

Earlier migration and container results:

```text
DATABASE_URL=sqlite+aiosqlite:////tmp/kalpi-migration-test.db \
  .venv/bin/alembic upgrade head
Migration 0001 was applied in that earlier run. Migration 0002 was later
applied by the Compose API container.

docker build -t kalpi-trade-engine:test .
Image built successfully

docker-compose up -d --build
PostgreSQL became healthy; API started

GET /health
200 {"status":"ok"}

GET /openapi.json
200

POST /api/v1/executions using MockBrokerAdapter
201 SUCCESS with persisted execution and executed order
```

The local machine exposes Docker through Podman. Legacy `docker compose`
initially targeted a missing Docker socket; verification succeeded by starting
the user Podman socket and running `docker-compose` against that socket. This is
an environment issue, not a repository requirement. Services were stopped and
removed after the smoke test.

## Production hardening still required

- [ ] Live-certify each broker with account-owner credentials and controlled
  minimum-quantity tests.
- [ ] Add authenticated users, authorization policy, and tenant isolation.
- [ ] Store broker tokens in a KMS-backed encrypted credential vault.
- [ ] Move executions to a durable worker/outbox and add startup reconciliation.
- [ ] Consume broker postbacks/order WebSockets.
- [ ] Add distributed per-account rate limiting.
- [ ] Add scheduled atomic instrument-master refresh and stale-data alerts.
- [ ] Complete broker-specific DDPI/eDIS user journeys.
- [ ] Add HTTPS, static egress IPs, production secret management, monitoring,
  alerting, and operational runbooks.
