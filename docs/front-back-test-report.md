# Frontend and backend walkthrough

Observed: 2 October 2026, 18:20 IST.

The Compose services were already running before this walkthrough:

- PostgreSQL: healthy
- API: healthy on port 8000
- Frontend: running on port 8080

Chrome opened `http://localhost:8080/` and used the page that Compose is serving. The IDE browser could not set the CSV file input, so this run used Chrome directly against that same page. No code was changed during the walkthrough.

## What the page showed before any action

- Title: Portfolio Trade Execution Engine.
- The selected broker was already `mock`, displayed as Mock Broker.
- The broker list contained Angel One, DhanHQ, Groww, Mock Broker, Upstox, and Zerodha.
- Connection text was "Not connected".
- Execute portfolio was disabled.
- The portfolio table had one empty row.
- Orders said "No orders yet."
- The page requested `GET /api/v1/brokers` and received HTTP 200. Every returned broker had `live_certified: false`.
- The browser console recorded no messages or page errors.

## CSV upload

The file input received `frontend/sample-portfolio.csv`.

The table then contained three rows:

| Symbol | Exchange | ISIN | Quantity |
|---|---|---|---|
| INFY | NSE | empty | 10 |
| TCS | NSE | empty | 5 |
| HDFCBANK | NSE | empty | 8 |

After that update, the file input itself contained no file. The parsed rows remained visible and editable. No additional API request was made by the upload.

## Connect

Clicking Connect broker sent `GET /api/v1/brokers/mock/status`.

The response was HTTP 200:

```json
{"name":"mock","mode":"mock","configured":true,"live_certified":false}
```

The connection section then read:

```text
Connected
Mock broker is ready. No credentials are required.
```

Execute portfolio became enabled. No credential form appeared, and no token was shown.

## Execute

Clicking Execute portfolio sent:

1. `OPTIONS /api/v1/executions` — HTTP 200
2. `POST /api/v1/executions` — HTTP 201

The page showed this idempotency key:

```text
7f79244a-4f44-459d-a13f-5de29d786317
```

The API response identified the workflow as `FIRST_TIME`, the broker as `mock`, the execution status as `SUCCESS`, and the notification status as `SENT`.

## Results shown

The page displayed:

- Execution ID: `da9d9dc7-c90a-4099-88e9-63638b75136e`
- Broker: mock
- Created: 02/10/2026, 18:20:29
- Execution status: `SUCCESS`
- Text: "Execution completed."

The orders were:

| Order | Result shown |
|---|---|
| 1. INFY BUY 10 | `EXECUTED`, filled quantity 10, broker order ID `mock-2`, message "mock fill" |
| 2. TCS BUY 5 | `EXECUTED`, filled quantity 5, broker order ID `mock-3`, message "mock fill" |
| 3. HDFCBANK BUY 8 | `EXECUTED`, filled quantity 8, broker order ID `mock-4`, message "mock fill" |

The API returned the same three orders, all with side `BUY`, average price `100.0000`, and no error code. The page did not display the average price or `notification_status`.

No order was `UNKNOWN` or `SKIPPED`. No Reconcile execution button was present.

The broker order IDs began at `mock-2`, so this running API process had already accepted an earlier mock order before this CSV execution.

The browser console still had no messages or page errors after execution.
