# Final Pre-Submission Forensic Audit

Reviewed: 2 October 2026

This audit inspects the current source and tests. It does not treat the
previous remediation report, README, or `FINAL_CHECKLIST.md` as evidence.
No repository files other than this audit were changed.

Verdict scale:

- **PASS** — the implementation does what the claim says, and a test exercises that behavior where a test is relevant.
- **PARTIAL** — the main path exists, but a listed edge is untested, narrower than the claim, or contradicted by another path.
- **FAIL** — the claim is not what the code does, or no implementation exists.

## Executive verdict

**READY WITH DOCUMENTATION FIXES**

The financial-safety remediation is present in `ExecutionService`,
`ExecutionRepository`, and `HttpBrokerAdapter.request`. Ambiguous placement
outcomes inspected below are not turned into `FAILED`, and reconciliation does
not call `place_order`.

The repository should not be described as crash-proof, as having a fully
enforced database state machine, or as having PostgreSQL concurrency proven by
the automated suite. Those claims are stronger than the code and tests.

## A. UNKNOWN / ambiguous submission

| Case | Result | Where | What the code does | Test | Remaining edge |
|---|---|---|---|---|---|
| Timeout after submission | PASS | `HttpBrokerAdapter.request`; `ExecutionService._execute_order` | Non-retryable timeout raises `OrderStatusUnknownError` on the first attempt. The service stores `UNKNOWN`. | `test_ambiguous_submission_is_unknown_and_not_retried`; per-adapter `*_submit_timeout_is_not_retried`; `test_upstox_place_timeout_is_unknown_not_retried` | The engine test uses the mock exception. It does not drive a real HTTP timeout through `ExecutionService`. |
| Transport failure after submission | PARTIAL | `HttpBrokerAdapter.request` | With `ambiguous_on_failure=True`, `httpx.TransportError` immediately becomes `OrderStatusUnknownError`. All five `place_order` methods set that flag. | None for transport specifically | Timeout is tested. Connection-reset/transport behavior is implemented but not separately tested. |
| HTTP 5xx after submission | PASS | `HttpBrokerAdapter.request` | A non-retryable 5xx with `ambiguous_on_failure=True` becomes `OrderStatusUnknownError` and is not retried. | `test_upstox_ambiguous_placement_response_is_unknown` (503, one call) | Only Upstox placement is tested. The other four adapters use the same helper, but have no equivalent test. A safe read can still retry 5xx. |
| Malformed successful placement response | PASS | `HttpBrokerAdapter.request`; adapter `place_order` methods; `ExecutionService._execute_order` | Invalid JSON becomes `OrderStatusUnknownError`. A parsed body without the expected order ID raises `BrokerUnavailableError`, which the service also maps to `UNKNOWN` because placement has started. | `test_upstox_ambiguous_placement_response_is_unknown` (HTTP 200, `not-json`) | Missing-ID responses are not separately tested. The malformed-JSON test stops at the adapter. |
| Database failure after broker acceptance | PASS | `ExecutionService._execute_order` | If saving the broker result throws, the service attempts to save `UNKNOWN` with `broker_ack_persistence_failed` and the broker order ID. It does not continue into the generic `FAILED` handler. | `test_broker_acceptance_followed_by_db_failure_becomes_unknown` | The test fails only the first acknowledgement write. If the fallback `UNKNOWN` write also fails, `_mark_unknown` swallows it and the order remains `SUBMITTING`. That double failure is untested. |
| None of these become `FAILED` | PARTIAL | `ExecutionService._execute_order` | The five cases above return `UNKNOWN` when the fallback write succeeds. | The tests named above | After `place_order` starts, `BrokerAuthenticationError`, `BrokerRateLimitError`, and `DeliveryAuthorizationRequired` are still stored as `FAILED`. A 401, 403, 428, or 429 is an explicit response, but it is not classified as ambiguous. |
| No blind resubmission | PASS | `ExecutionService.reconcile`; adapter retry guard | Placement uses one attempt. Reconciliation calls only `get_order_status`. | `test_unknown_reconciles_to_executed_without_resubmission` asserts `place_calls == 1`; timeout tests assert one HTTP call | A later request with a new idempotency key can intentionally submit another execution. |

## B. SUBMITTING recovery

**Result: PARTIAL**

`ExecutionService.reconcile` includes `OrderStatus.SUBMITTING` and calls
`adapter.get_order_status(order.broker_order_id, order.client_order_id)`.
It never calls `place_order`.

`test_submitting_order_can_be_reconciled` proves both `SUBMITTING → EXECUTED`
and `SUBMITTING → REJECTED` when the mock lookup receives `broker_order_id=None`
and returns a correlated result.

When no broker order ID is stored:

- Zerodha searches `/orders` by `tag`.
- DhanHQ calls `/orders/external/{correlationId}`.
- Groww calls `/v1/order/status/reference/{order_reference_id}`.
- Upstox calls order details with `tag`.
- Angel One returns `UNKNOWN` immediately and does not call its details endpoint. Its verified contract cannot recover this window. `client_order_id` is still sent as `ordertag` at placement, but status lookup does not use it.

No adapter test proves recovery through those real correlation endpoints. The
Dhan test `test_dhan_status_uses_correlation_when_order_id_lost` covers the
adapter lookup itself, not an interrupted `SUBMITTING` execution.

## C. UNKNOWN execution halt

**Result: PARTIAL**

`ExecutionService.execute` stops the loop when `_execute_order` returns
`UNKNOWN`, marks every later order `SKIPPED`, and does not call
`_execute_order` for those orders. Aggregation then returns
`RECONCILIATION_REQUIRED` because `UNKNOWN` dominates.

The tested scenario is only:

```text
INFY timeout → UNKNOWN
TCS not called → SKIPPED
```

`test_unknown_stops_and_skips_subsequent_orders` proves that case and proves
`state.orders == {}`.

The requested three-order scenario is not tested:

```text
order 1 EXECUTED
order 2 UNKNOWN
orders 3+ SKIPPED
```

Code inspection says order 1 would already have been submitted, order 2 would
stop the loop, and orders 3+ would receive no `resolve_instrument` or
`place_order` call. That exact broker-call assertion is absent.

`SKIPPED` is not itself reconcilable and is not automatically resumed.

## D. Idempotency

| Claim | Result | Evidence | Edge |
|---|---|---|---|
| Same key and same payload returns the original execution | PASS | `ExecutionService.execute` calls `find_idempotent` before creating work. `test_idempotent_replay_returns_existing_execution` | Replay returns the stored execution even if its status is still `PENDING` or `RUNNING`. It does not resume a crashed execution. |
| Same key and different payload conflicts | PASS | `ExecutionRepository._validate_request_hash` raises `IdempotencyConflictError`. `test_idempotency_key_payload_conflict` and `test_api_idempotency_payload_conflict_returns_409` | Conflict is 409 at the API. |
| Lookup happens before holdings validation | PASS | `find_idempotent` is before `_instructions`. `test_first_time_idempotent_replay_precedes_changed_holdings` adds holdings after success and still returns the original ID | A different payload still conflicts before holdings are read. That variant is not explicitly tested. |
| Concurrent insert reloads the winner | PASS | `create_or_get` catches `IntegrityError`, then `find_idempotent` loads the committed row. `test_concurrent_identical_requests_return_one_execution` forces both initial lookups to miss | The test is SQLite and service-level. It is not an HTTP or PostgreSQL test. |
| No unexpected 500 | PARTIAL | The idempotency race itself returns the winner instead of propagating the unique-key error | Any other `IntegrityError` whose key cannot be reloaded is re-raised. There is no API test proving the concurrent response is not 500. |
| Deterministic equivalent-request hash | PARTIAL | Hash is `SHA256(request.model_dump_json(exclude={"confirm_live"}))` | Pydantic field order makes one model serialization stable, but there is no test for key reordering, decimal formatting, or explicit canonical JSON. `confirm_live` is intentionally excluded. |

The unique `idempotency_key` index remains the final authority. The application
no longer relies only on the initial `SELECT`.

## E. State machine

**Result: PARTIAL**

`validate_order_transition` in `app/domain.py` is the single transition check.
`ExecutionRepository.update_order` calls it under `SELECT ... FOR UPDATE`.
Direct assignment of `OrderStatus` outside that method is not the normal write
path.

Legal transitions are:

| From | To |
|---|---|
| `PENDING` | `SUBMITTING`, `FAILED`, `SKIPPED` |
| `SUBMITTING` | `SUBMITTED`, `OPEN`, `PARTIALLY_FILLED`, `EXECUTED`, `REJECTED`, `FAILED`, `CANCELLED`, `UNKNOWN` |
| `SUBMITTED` | `OPEN`, `PARTIALLY_FILLED`, `EXECUTED`, `REJECTED`, `CANCELLED`, `UNKNOWN` |
| `OPEN` | `OPEN`, `PARTIALLY_FILLED`, `EXECUTED`, `REJECTED`, `CANCELLED`, `UNKNOWN` |
| `PARTIALLY_FILLED` | `PARTIALLY_FILLED`, `EXECUTED`, `CANCELLED`, `UNKNOWN` |
| `UNKNOWN` | `UNKNOWN`, `SUBMITTED`, `OPEN`, `PARTIALLY_FILLED`, `EXECUTED`, `REJECTED`, `CANCELLED` |
| `EXECUTED`, `REJECTED`, `FAILED`, `CANCELLED`, `SKIPPED` | no other state |

Same-state writes are allowed. Terminal states cannot move, so
`EXECUTED → OPEN`, `EXECUTED → PARTIALLY_FILLED`, and `CANCELLED → OPEN` are
rejected. `test_invalid_terminal_transition_and_overfill_are_rejected` proves
those three regressions.

`filled_quantity` must satisfy `0 <= filled <= quantity` before the write.
The same bounds exist as `ck_orders_filled_quantity_bounds`, and `quantity > 0`
exists as `ck_orders_quantity_positive`, in both the ORM and Alembic `0002`.

The database does not enforce the transition table or the status vocabulary.
The overfill test hits the Python check before SQL, so it does not prove the
PostgreSQL constraint. `SUBMITTING → FAILED` remains legal and is used for
authentication, rate-limit, and delivery-authorization responses.

## F. Crash and failure windows

| Window | Persisted state | Broker may have an order | Reconciliation | Duplicate submission |
|---|---|---|---|---|
| 1. Execution commit, crash before any broker call | Execution `PENDING` or `RUNNING`; orders `PENDING` | No | No. `PENDING` is not in the reconciliation set, and there is no startup sweep | Same key returns the stuck execution and does not submit. A new key can submit a second execution |
| 2. `SUBMITTING` committed, crash before the broker request | Order `SUBMITTING`; normally no broker order ID | No, if the crash truly precedes the request | Yes. Lookup is attempted. A not-found result becomes or remains non-terminal rather than being resubmitted | No automatic resubmission |
| 3. Broker accepts, crash before acknowledgement | Database remains `SUBMITTING` without the broker ID | Yes | Yes only where correlation/tag lookup exists. Angel One stays unresolved without its broker order ID | No automatic resubmission |
| 4. Broker accepts, acknowledgement update fails | Tested path: `UNKNOWN` plus broker order ID. If the fallback write also fails: `SUBMITTING` | Yes | The tested path can be reconciled by broker ID. The double-failure path falls into window 3 | No automatic resubmission. The tested path does not become `FAILED` |
| 5. Reconciliation lookup succeeds, status update fails | Previous order state remains | Yes, unchanged | `reconcile` does not catch a generic persistence exception, so the API can return 500 before finalization. Retrying reconciliation repeats the read-only lookup | No resubmission. This window is untested |

## G. First-time portfolio

| Claim | Result | Evidence | Edge |
|---|---|---|---|
| Idempotency precedes holdings validation | PASS | `execute` then `_instructions`; holdings replay test | Covered in section D |
| Existing holdings are rejected | PASS | Any holding quantity greater than zero raises `ExistingHoldingsError`. `test_first_time_rejects_nonempty_account` | The API maps it to 409, but that HTTP mapping is not tested. Holdings completeness depends on each adapter |
| Symbol and instrument validation | PASS | `InstrumentInput` pattern, exchange, segment, ISIN, and quantity bounds. `test_invalid_quantity_and_symbol_are_rejected` | Core validation is syntactic. Exact broker identity resolution is adapter-specific |
| Every first-time order is `BUY` | PASS | `_instructions` constructs `Side.BUY`. `test_first_time_portfolio_buys_all_items` | The test covers two symbols |
| Partial-failure behavior is tested | FAIL | Rebalance partial failure is tested | No first-time test covers one rejected buy plus one successful buy |

## H. Rebalance

| Claim | Result | Evidence | Edge |
|---|---|---|---|
| Explicit BUY/SELL instructions are preserved | PASS | `_instructions` returns `request.orders` unchanged. `test_mixed_rebalance_preserves_instruction_order` | The engine does not calculate a delta |
| Sequence is preserved | PASS | Orders are enumerated and stored with `sequence`. The mixed test checks symbol, side, and quantity order | Persistence order comes from the relationship `order_by` |
| Duplicate symbols | PARTIAL | No validator rejects two instructions for one symbol | Both instructions are submitted in order. The policy is neither rejection nor documented aggregation |
| Partial failure | PASS | `test_partial_failure_keeps_successful_trades` and `test_api_partial_failure` | Success, rejection, success becomes `PARTIAL_SUCCESS`. This is distinct from the UNKNOWN halt |

## I. Retries

**Result: PARTIAL**

`HttpBrokerAdapter.request` uses one attempt when `safe_to_retry` is false.
Every current `place_order` uses that default and also sets
`ambiguous_on_failure=True`. Timeout, transport failure, 5xx, and malformed
placement JSON therefore cannot loop back into another submission.

Safe reads pass `safe_to_retry=True`, allowing three attempts. Delay comes from
`retry_delay`: exponential base `0.05 * 2**attempt`, multiplied by a random
factor from 0.8 to 1.2. A numeric `Retry-After` is honored only for the 429
branch, and only up to five seconds. HTTP-date `Retry-After` values fall back
to jitter. The 5xx retry branch does not pass the response into `retry_delay`,
so it ignores `Retry-After`.

No test asserts jitter, `Retry-After`, or the three-attempt ceiling. Timeout
tests do prove that placement is not repeated.

## J. API

| Condition | Result | Actual behavior | Test |
|---|---|---|---|
| Validation failure | PASS | Missing idempotency header and invalid quantity return 422 | `test_api_requires_idempotency_header_and_valid_quantity` |
| Idempotency conflict | PASS | 409 `idempotency_conflict` | `test_api_idempotency_payload_conflict_returns_409` |
| Not found | PARTIAL | Missing execution returns 404 in `get_execution` and `reconcile` | No test |
| Live execution blocked | PARTIAL | `PermissionError` becomes 403 when a live adapter is used without both switches | No API test. This is not user authentication |
| Broker failure | PARTIAL | `BrokerUnavailableError` maps to 503 and the generic `TradeEngineError` maps to 502 | `test_api_maps_domain_errors` raises errors from a synthetic route, not from an execution |
| Reconciliation-required execution | PARTIAL | The execution is still HTTP 201/200 and carries `status=RECONCILIATION_REQUIRED` | Engine tests prove the status. No API test does |
| Rate limiting | PARTIAL | A propagated `BrokerRateLimitError` maps to 429 | During execution, that error is caught and stored as order `FAILED`; the HTTP response remains 201. The 429 test does not exercise execution |
| `/ready` checks the database | PARTIAL | `ExecutionRepository.ping` runs `SELECT 1` | It checks the configured database connection, not specifically PostgreSQL, schema presence, or migration level. No failure test exists |

Authentication failure maps to 401, delivery authorization to 409, and
instrument-resolution failure to 422 when those exceptions escape the service.
Inside execution, instrument resolution is stored on the order and does not
escape as 422.

## K. Security

| Claim | Result | What is true | Edge |
|---|---|---|---|
| Live execution disabled by default | PASS | `Settings.allow_live_trading` defaults to false. Compose sets `ALLOW_LIVE_TRADING=false` | A live adapter also requires `confirm_live=true` |
| `confirm_live` is not authentication | PASS | It is a request flag combined with the environment switch. README states that production requires authenticated, authorized users | Both flags only prevent accidental execution |
| No production secrets committed | PASS | `.env.example` contains empty credential names. Reviewed source has no real tokens | Test fixtures use obvious fake values such as `token` and `secret` |
| Credentials cannot leak through repr | FAIL | `BrokerCredentials` is a normal dataclass. Its default repr includes `access_token` and `api_secret` | No reviewed code logs the credential object, but any accidental log or exception of that object would expose it |
| Authorization headers and tokens are not logged | PASS | `ConsoleNotifier` logs execution ID, status, broker, order summary, and error text. It does not log headers or credential fields | Broker error text, capped at 500 characters in `request`, can still enter logs and webhooks |
| Production authentication requirement is documented | PASS | README “Configuration and real brokers” and the architecture security section | The API itself has no user authentication |

`logger` in `app/main.py` is unused. OAuth state remains one in-memory value
per broker.

## L. Database and migrations

| Claim | Result | Evidence | Edge |
|---|---|---|---|
| Fresh database works | PARTIAL | Tests call `create_schema`, which runs `Base.metadata.create_all`, against temporary SQLite files | No automated fresh-PostgreSQL test is in the suite |
| Migration `0001 → 0002` works | PARTIAL | `0002` revises `0001` and adds the two quantity checks. The prior Compose run logged this upgrade | This audit did not start PostgreSQL again or query `pg_constraint` |
| Runtime schema creation does not conflict with Alembic | PARTIAL | Compose sets `AUTO_CREATE_SCHEMA=false` and the container runs `alembic upgrade head` | The application default is still `auto_create_schema=True`. Running `create_all` and Alembic against one database can conflict because `create_all` does not stamp `alembic_version` |
| Constraints exist in PostgreSQL | PARTIAL | ORM and migration `0002` define them | The suite proves the Python guard on SQLite, not the PostgreSQL catalog |
| PostgreSQL is exercised somewhere | PARTIAL | Compose is configured for PostgreSQL 16 and a prior smoke run used it | The current automated suite uses only SQLite |

## M. Test quality

| Required behavior | Result | Test | What it proves | Gap |
|---|---|---|---|---|
| UNKNOWN reconciles to EXECUTED | PASS | `test_unknown_reconciles_to_executed_without_resubmission` | Lost response, later status lookup, one placement | Mock correlation only |
| SUBMITTING reconciliation | PASS | `test_submitting_order_can_be_reconciled` | Both executed and rejected outcomes, with no broker ID | Does not use a real adapter |
| Broker accepted and DB update fails | PASS | `test_broker_acceptance_followed_by_db_failure_becomes_unknown` | First acknowledgement failure becomes `UNKNOWN` with broker ID | Second persistence failure is untested |
| 5xx after submission | PARTIAL | `test_upstox_ambiguous_placement_response_is_unknown` | Upstox 503 raises unknown and is called once | Not wired through execution or the other adapters |
| Malformed placement response | PARTIAL | Same Upstox test, with HTTP 200 and invalid JSON | Adapter classification | Missing order-ID bodies and engine persistence are untested |
| Concurrent idempotency | PASS | `test_concurrent_identical_requests_return_one_execution` | Forced lost-lookup race returns one execution and notifies once | SQLite only; no HTTP assertion |
| Invalid transition | PASS | `test_invalid_terminal_transition_and_overfill_are_rejected` | Executed and cancelled regressions, plus overfill | Not every illegal transition or the SQL constraint |
| UNKNOWN halts later orders | PARTIAL | `test_unknown_stops_and_skips_subsequent_orders` | First unknown order skips the second and makes no mock fill | Does not prove success, then unknown, then orders 3+ |
| API idempotency conflict | PASS | `test_api_idempotency_payload_conflict_returns_409` | HTTP 409 and error code | None material |
| API error mapping | PARTIAL | `test_api_maps_domain_errors` | Handler status codes for five exceptions | Synthetic endpoint; 404, 403, and execution-path rate limiting are absent |
| First-time partial failure | FAIL | None | Nothing | Rebalance partial failure does not prove the first-time workflow |

## N. Five broker adapters

All five are contract-tested with `httpx.MockTransport`. None is live-certified.
The application reports `live_certified: false`.

| Broker | Adapter | Placement and status | Ambiguous placement | Correlation without broker ID | Contract tests |
|---|---|---|---|---|---|
| Zerodha | `ZerodhaAdapter` | `POST /orders/regular`; status by order history or order list | `ambiguous_on_failure=True` | `tag`, truncated to 20 characters | `tests/test_zerodha_adapter.py` |
| DhanHQ | `DhanAdapter` | `POST /orders`; status by order ID or external correlation path | `ambiguous_on_failure=True` | `correlationId`, truncated to 30 characters | `tests/test_dhan_adapter.py` |
| Angel One | `AngelOneAdapter` | SmartAPI `placeOrder`; details by unique order ID | `ambiguous_on_failure=True` | Not available. Missing ID returns `UNKNOWN` | `tests/test_angel_one_adapter.py` |
| Groww | `GrowwAdapter` | `POST /v1/order/create`; status by Groww ID or reference ID | `ambiguous_on_failure=True` | `order_reference_id`, truncated to 20 characters | `tests/test_groww_adapter.py` |
| Upstox | `UpstoxAdapter` | `POST /v3/order/place`; `GET /v2/order/details` | `ambiguous_on_failure=True`; 503 and invalid JSON tested | `tag`, truncated to 20 characters | `tests/test_upstox_adapter.py` |

Authentication paths are:

- Zerodha: redirect and checksum token exchange.
- DhanHQ: consent generation and consent consumption.
- Angel One: daily login contract; the test checks that PIN/TOTP are not persisted.
- Groww: API-key token generation.
- Upstox: authorization-code exchange.

Each adapter has a full contract test and a timeout test. Only Upstox has the
additional 5xx and malformed-placement assertions.

## O. Documentation consistency

Documentation is mostly aligned, but these claims are stronger than the proof:

- README says the service stores a “canonical request hash.” The hash is
  Pydantic JSON with `confirm_live` removed, not explicitly canonicalized.
- The architecture state diagram omits legal transitions that the code allows,
  including `SUBMITTING → FAILED`, direct terminal outcomes from `SUBMITTING`,
  and `UNKNOWN → OPEN/SUBMITTED/PARTIALLY_FILLED/CANCELLED`.
- README says reconciliation “preserves recoverable state.” `PENDING` orders
  are not recoverable, and Angel One `SUBMITTING` orders without a broker ID
  are not recoverable.
- README lists auth, rate-limit, 5xx, and malformed-response normalization as
  suite coverage. Rate-limit and 5xx normalization are not proven for every
  adapter or for the execution API.
- `FINAL_CHECKLIST.md` marks PostgreSQL schema and Alembic as verified. The
  migration exists, but the automated suite does not exercise PostgreSQL.
- “Bounded retry only for safe reads” is true of the current call sites, not
  enforced by the helper against a future retryable POST.
- The architecture says authorization headers are never logged. That is true
  of the current logging statements, while `BrokerCredentials` repr is still
  unsafe.
- Both README and architecture correctly say the five real adapters are not
  live-certified and that the service is not production-ready.

## P. Assignment compliance

Checked against `docs/assignment_requirements.md` without broadening it.

| Requirement | Result | Evidence |
|---|---|---|
| Python FastAPI backend | PASS | `app/main.py` |
| At least five Indian broker integrations | PASS | Zerodha, DhanHQ, Angel One, Groww, and Upstox. FYERS and Indiabulls are absent because their contracts were not verified |
| Adapter pattern for a sixth broker | PASS | `BrokerAdapter` and `BrokerRegistry` |
| First-time portfolio buys the requested quantities | PASS | Empty-holdings check and forced `BUY` |
| Rebalance uses explicit supplied instructions | PASS | No delta calculation |
| Notification of executed and failed orders | PASS | `ConsoleNotifier`; optional webhook |
| Docker and Compose | PASS | `Dockerfile`, `docker-compose.yml` |
| README setup, architecture, and rebalance explanation | PASS | `README.md` |
| No third-party broker SDK requiring justification | PASS | Direct HTTP adapters and `httpx` |
| Frontend bonus | Not implemented | Intentionally omitted |
| Problem 2 design document and diagram | PASS | `docs/multi-frequency-data-platform.md` |
| Public GitHub submission | Not verifiable from code | Repository files do not prove that the project has been pushed publicly |

## Critical findings

1. A crash after the execution is saved but before submission leaves `PENDING`
   orders outside reconciliation. Replaying the same key will not resume them,
   while a new key can create a second execution.
2. Angel One cannot investigate a `SUBMITTING` order unless its broker order ID
   was saved. The code returns `UNKNOWN` rather than resubmitting, but it
   cannot prove the broker outcome.
3. If both the acknowledgement write and the `UNKNOWN` fallback write fail,
   the order remains `SUBMITTING`. This is safe from blind resubmission, but
   it is not the tested `UNKNOWN` outcome.

## Medium findings

1. Authentication, rate-limit, and delivery-authorization errors after
   `place_order` begins are stored as `FAILED`, unlike timeout, transport,
   5xx, malformed, and persistence failures.
2. A rate-limited execution normally returns HTTP 201 with a failed order.
   HTTP 429 is only produced when `BrokerRateLimitError` escapes the service.
3. The success-then-UNKNOWN-then-skip scenario and first-time partial failure
   are untested.
4. Duplicate rebalance symbols are silently accepted.
5. Reconciliation persistence failures propagate as unhandled exceptions.
6. `/ready` only executes `SELECT 1`; it does not prove schema or migration
   readiness.
7. Default `auto_create_schema=True` can conflict with Alembic outside the
   Compose configuration.
8. Jitter and `Retry-After` are implemented but untested, and `Retry-After`
   applies only to numeric 429 retries.
9. `BrokerCredentials` has an unsafe default repr.
10. Automated tests do not exercise PostgreSQL concurrency or catalog
    constraints.

## Documentation mismatches

1. “Canonical request hash” overstates the hash implementation.
2. The published state diagram is narrower than `ORDER_STATUS_TRANSITIONS`.
3. “Reconciliation preserves recoverable state” does not cover `PENDING` or
   Angel One without a broker order ID.
4. Test-coverage bullets imply broader rate-limit, 5xx, and malformed coverage
   than the suite contains.
5. PostgreSQL is the deployment database, but the checklist can be read as
   saying the test suite verified it.
6. Safe retry is a call-site convention, not a guard that rejects unsafe POST
   retries.

## Interview-risk questions

1. Why can `SUBMITTING` legally transition to `FAILED` if ambiguous outcomes
   must not become failed?
2. What happens if the process dies after the execution commit but before the
   first broker call?
3. How does Angel One reconciliation work when the placement response was lost?
4. Why is the concurrent idempotency test sufficient if it runs on SQLite
   rather than PostgreSQL?
5. Why does a broker 429 during execution return 201 instead of 429?
6. What guarantees that two semantically identical payloads produce one hash?
7. Why are duplicate instructions for the same symbol allowed?
8. Which database constraint prevents an illegal status transition?
9. What exactly has been live-certified for each of the five brokers?
10. Why is `SELECT 1` called readiness?

## Final submission checklist

- [x] Ambiguous timeout, 5xx, malformed JSON, and acknowledgement-persistence
  failure paths are implemented.
- [x] Reconciliation can inspect `SUBMITTING` and does not resubmit.
- [x] UNKNOWN stops later orders in the tested two-order case.
- [x] Idempotency lookup precedes holdings validation, and the unique-key race
  reloads the winner.
- [x] Terminal order regressions tested are rejected.
- [x] Five real adapters are present and contract-tested, not live-certified.
- [x] Live trading defaults off, and `confirm_live` is documented as a safety
  flag rather than authentication.
- [ ] Correct the state diagram and recoverable-state wording before submission.
- [ ] Be ready to explain Angel One, `PENDING` crash behavior, HTTP 429 versus
  order `FAILED`, and SQLite-versus-PostgreSQL test limits.
- [ ] Do not describe the suite as having verified PostgreSQL constraints,
  every broker’s 5xx behavior, or the three-order UNKNOWN halt unless those
  tests are added later.
