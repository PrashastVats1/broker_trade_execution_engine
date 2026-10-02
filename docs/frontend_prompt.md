# Kalpi Assignment — Bonus Frontend Implementation

You are working inside the existing Kalpi_Assignment repository.

The backend for Problem 1 (Portfolio Trade Execution Engine) is already implemented and has gone through a forensic audit.

Your task is to implement ONLY the optional bonus frontend:

> “A basic frontend interface (in any framework/language) to test the flow visually:
> upload target portfolio -> connect broker -> click execute -> view results.”

This frontend is a demonstration/test interface for the existing backend.

DO NOT rewrite, refactor, redesign, or otherwise modify the core trading engine unless a tiny backend change is absolutely required to expose an already-existing capability to the frontend.

The frontend must not compromise any existing safety, idempotency, reconciliation, or broker behavior.

---

# 1. PRIMARY GOAL

Build a small, polished, evaluator-friendly frontend that lets someone understand and test the Problem 1 flow without needing Postman.

The intended flow is:

1. Open frontend
2. Enter/upload target portfolio
3. Select broker
4. Connect broker
5. Execute portfolio
6. Watch/view order results
7. See final execution status
8. If reconciliation is required, clearly show that state and allow reconciliation

The frontend should primarily work with the existing MOCK broker so an evaluator can test the entire flow without real broker credentials.

Real broker authentication may be exposed where the existing backend already supports it, but DO NOT build complicated new OAuth infrastructure solely for the frontend.

---

# 2. IMPORTANT SCOPE RULE

This is a BONUS feature.

Do not allow frontend work to destabilize Problem 1 or Problem 2.

DO NOT:

- rewrite ExecutionService
- redesign the broker adapter architecture
- add new broker integrations
- add Kubernetes
- add a message queue
- add WebSockets unless already trivial and necessary
- add authentication systems
- add user accounts
- add a complex state-management framework
- add charts unrelated to the assignment
- build a production-grade trading dashboard
- implement actual financial/accounting calculations in the frontend
- add unnecessary backend endpoints
- change the assignment requirements

Prefer polling existing execution/status endpoints over introducing WebSockets.

If the backend already exposes everything needed, use it as-is.

---

# 3. TECHNOLOGY

Use:

- React
- TypeScript
- Vite

Use a simple styling approach already compatible with the repository.

Do not introduce a large UI framework unless the repository already uses one.

Keep dependencies minimal.

The frontend should be easy for an evaluator to install and understand.

Recommended structure:

frontend/
├── src/
│   ├── components/
│   │   ├── PortfolioEditor.tsx
│   │   ├── BrokerSelector.tsx
│   │   ├── ConnectionStatus.tsx
│   │   ├── ExecutionPanel.tsx
│   │   ├── OrderResults.tsx
│   │   └── StatusBadge.tsx
│   ├── api.ts
│   ├── types.ts
│   ├── App.tsx
│   ├── main.tsx
│   └── styles.css
├── package.json
├── tsconfig.json
├── vite.config.ts
├── Dockerfile
└── .dockerignore

Adjust this structure if the repository already has conventions.

---

# 4. UI DESIGN

Keep the UI clean and professional.

This is an engineering take-home, not a design competition.

The evaluator should immediately understand:

- what portfolio they are executing
- which broker is selected
- whether the broker is connected
- whether execution is running
- what happened to each order
- whether reconciliation is required

Suggested layout:

--------------------------------------------------
Portfolio Trade Execution Engine
--------------------------------------------------

Target Portfolio

[ Symbol ] [ Exchange ] [ ISIN ] [ Quantity ]
[ INFY   ] [ NSE     ] [ ... ] [ 10       ]
[ TCS    ] [ NSE     ] [ ... ] [ 5        ]

[ + Add Position ]

Broker

[ Mock Broker ▼ ]

Connection
● Connected

[ Connect Broker ]

--------------------------------------------------

Execution

[ Execute Portfolio ]

Idempotency Key
[ automatically generated / displayed ]

Execution Status
RECONCILIATION_REQUIRED

--------------------------------------------------

Orders

INFY
BUY 10
✓ EXECUTED

TCS
BUY 5
⚠ UNKNOWN
Reconciliation required

HDFCBANK
BUY 8
⏸ SKIPPED
Not submitted because a previous order
entered UNKNOWN state

--------------------------------------------------

[ Reconcile Execution ]

Do not overcomplicate this layout.

---

# 5. PORTFOLIO INPUT

The user must be able to enter a target portfolio.

Support at minimum:

- symbol
- exchange
- quantity

If the backend requires additional fields such as ISIN or segment, expose those only where required.

Provide:

- Add position
- Remove position
- Edit quantity
- Basic validation

Reject:

- empty symbols
- invalid quantities
- negative quantities
- zero quantities
- malformed values

Do not duplicate complex backend validation.

The backend remains the source of truth.

---

# 6. OPTIONAL FILE UPLOAD

The assignment says “upload target portfolio”.

Implement a simple CSV upload if it can be done cleanly.

Example:

symbol,exchange,quantity
INFY,NSE,10
TCS,NSE,5
HDFCBANK,NSE,8

The frontend should:

1. Accept CSV.
2. Parse it.
3. Display the parsed rows.
4. Allow the user to review/edit them.
5. Submit only after validation.

Do not add Excel parsing unless trivial.

If CSV upload adds excessive complexity, a clearly documented portfolio editor is acceptable, but prefer CSV because the assignment explicitly mentions upload.

---

# 7. BROKER SELECTION

Provide a broker selector.

At minimum include:

- Mock Broker

Also show the five real brokers if the backend supports them:

- Zerodha
- DhanHQ
- Angel One
- Groww
- Upstox

However:

DO NOT pretend a real broker is connected when it isn't.

For unconfigured brokers display an appropriate state such as:

"Not configured"

or

"Authentication required"

The frontend must never fake successful broker connectivity.

---

# 8. MOCK BROKER FLOW

The MOCK broker must be the easiest path for an evaluator.

The expected flow should be:

1. Select Mock Broker
2. Click Connect
3. UI shows connected
4. Enter portfolio
5. Click Execute Portfolio
6. Backend executes
7. Frontend displays execution/order results

The evaluator should not need:

- broker credentials
- OAuth
- external accounts
- environment secrets

to demonstrate the application.

---

# 9. REAL BROKER CONNECTION

Reuse the backend's existing authentication/connect endpoints.

Do not implement new authentication protocols in the frontend.

For OAuth flows:

- redirect the user to the backend's existing authorization endpoint
- show connection status after returning
- do not store broker secrets in localStorage
- do not expose access tokens in the browser
- do not log credentials or tokens

If the backend's current OAuth flow is demo-oriented, reflect that honestly in the UI.

---

# 10. EXECUTION

The Execute button must call the existing execution API.

Before executing:

- validate portfolio
- ensure broker selection
- ensure connection requirements are satisfied
- disable duplicate clicks while request is running

Generate/use an idempotency key appropriately.

Do not create a new idempotency key every time the frontend polls.

The execution request itself should have exactly one logical idempotency key.

Display:

- execution ID
- execution status
- broker
- created time if available

---

# 11. EXECUTION STATUS

Support the backend's actual execution states.

Do not invent states.

At minimum handle:

- PENDING
- RUNNING
- SUCCESS
- PARTIAL_SUCCESS
- RECONCILIATION_REQUIRED
- FAILED

Use clear visual distinctions.

For example:

SUCCESS
✓ Execution completed

PARTIAL_SUCCESS
! Some orders succeeded and others failed

RECONCILIATION_REQUIRED
! A broker outcome is ambiguous and requires reconciliation

FAILED
✕ Execution failed

Do not call an UNKNOWN order "failed".

That distinction is one of the important safety properties of the backend.

---

# 12. ORDER RESULTS

Display every order returned by the backend.

For each order show:

- symbol/instrument
- side
- requested quantity
- filled quantity if available
- order status
- broker order ID if available
- error/reason if available
- sequence/order number if useful

Support statuses including:

- PENDING
- SUBMITTING
- SUBMITTED
- OPEN
- PARTIALLY_FILLED
- EXECUTED
- REJECTED
- FAILED
- CANCELLED
- UNKNOWN
- SKIPPED

Do not hide UNKNOWN or SKIPPED orders.

---

# 13. IMPORTANT UNKNOWN / RECONCILIATION UX

This is particularly important.

If an order becomes UNKNOWN, make the reason obvious.

Example:

--------------------------------------------------
⚠ Reconciliation Required

TCS
BUY 5

Status:
UNKNOWN

The broker outcome could not be determined safely.

No automatic resubmission was performed.

Orders after this trade were not submitted.
--------------------------------------------------

Then provide:

[ Reconcile Execution ]

When reconciliation succeeds, refresh the execution and show the new state.

If reconciliation resolves the order to EXECUTED:

✓ TCS EXECUTED

If it resolves to REJECTED:

✕ TCS REJECTED

Do not create a frontend retry that calls execute again.

Reconciliation must call the backend reconciliation endpoint.

---

# 14. SKIPPED ORDER UX

If UNKNOWN causes subsequent orders to be skipped, make this explicit.

Example:

WIPRO
BUY 10

⏸ SKIPPED

Not submitted because an earlier order entered
UNKNOWN state.

Do not imply that SKIPPED means broker rejection.

---

# 15. POLLING

If execution is asynchronous or the API returns before the final state:

Use simple polling.

Suggested behavior:

- poll execution status every 1–2 seconds
- stop when terminal/reconciliation-required state is reached
- have a reasonable maximum polling duration
- show "Waiting for execution status..." while polling

Do not introduce WebSockets unless the existing backend already provides them.

Do not hammer the backend.

---

# 16. ERROR HANDLING

The UI should handle:

- validation errors
- 400/422
- 401/403
- 404
- 409 idempotency conflict
- 429
- 500/502/503
- network failure
- timeout

Display useful human-readable messages.

Do not expose stack traces.

Do not display broker credentials or access tokens.

Do not turn backend errors into misleading "execution failed" messages when the actual state is UNKNOWN or reconciliation-required.

---

# 17. API LAYER

Create a small typed API client.

For example:

api.ts

Functions such as:

- connectBroker()
- getBrokerStatus()
- createExecution()
- getExecution()
- reconcileExecution()

Use TypeScript types corresponding to the actual FastAPI response models.

Do NOT guess the API contract.

Inspect the existing FastAPI routes and Pydantic models first.

If an endpoint doesn't exist, determine whether the frontend can work without it before proposing a backend addition.

---

# 18. CORS / FRONTEND-BACKEND CONNECTION

Configure development access cleanly.

For example:

Frontend:
http://localhost:5173

Backend:
http://localhost:8000

Use an environment variable such as:

VITE_API_BASE_URL=http://localhost:8000

Do not hardcode production URLs.

If a small CORS backend change is necessary, make the minimum safe change and document it.

Do not introduce wildcard production CORS unnecessarily.

---

# 19. DOCKER COMPOSE

Integrate the frontend into the existing docker-compose setup only if this can be done cleanly.

Preferred:

services:
  postgres
  api
  frontend

Frontend should depend on the API being available where appropriate.

The evaluator should ideally be able to run:

docker compose up --build

and access the UI.

If adding the frontend to Compose introduces unnecessary complexity, keep the existing backend Compose behavior intact and document the separate frontend command.

Do not break the existing Compose smoke test.

---

# 20. TESTING

Add lightweight frontend tests only where useful.

At minimum verify:

- portfolio validation
- CSV parsing
- execution request construction
- execution result rendering
- UNKNOWN rendering
- SKIPPED rendering
- reconciliation action

Do not spend hours building a huge frontend test suite.

The existing backend tests remain authoritative for trading behavior.

---

# 21. ACCESSIBILITY / UX

Keep basic accessibility:

- labels for form controls
- keyboard-accessible buttons
- readable status text
- disabled states while requests are running
- useful error messages

Do not spend time on pixel-perfect design.

---

# 22. SECURITY

The frontend must NEVER:

- store broker access tokens in localStorage
- print credentials
- print authorization headers
- expose API secrets
- fake broker connection status
- bypass backend validation
- treat `confirm_live` as authentication

The backend remains responsible for execution authorization and safety.

Remember:

`confirm_live` is a safety flag, NOT authentication.

Live execution remains disabled by default.

---

# 23. README

Update the README with a small section:

## Bonus Frontend

Explain:

- what it does
- how to run it
- how to use Mock Broker
- how to execute a sample portfolio
- how reconciliation is displayed
- that real broker integrations are contract-tested, not live-certified
- that live trading is disabled by default

Include a quick demo flow:

1. Start Compose
2. Open frontend
3. Select Mock Broker
4. Upload sample CSV
5. Connect
6. Execute
7. View order results

Do not overclaim production readiness.

---

# 24. SAMPLE DATA

Add a small sample portfolio file:

frontend/sample-portfolio.csv

Example:

symbol,exchange,quantity
INFY,NSE,10
TCS,NSE,5
HDFCBANK,NSE,8

Make sure it is clearly labeled as demo data.

---

# 25. VISUAL QUALITY

Aim for:

- clean
- simple
- professional
- good spacing
- clear hierarchy
- obvious primary action
- obvious execution state

Do NOT create a generic "AI startup dashboard".

This is a financial trade execution engine.

The UI should look like an engineering tool.

---

# 26. DO NOT CHANGE THE ASSIGNMENT REQUIREMENTS

`docs/assignment_requirements.md` is immutable.

Do not edit it.

Do not change Problem 2.

Do not alter the broker research to accommodate the frontend.

Do not remove existing tests.

Do not weaken safety behavior to make the UI easier.

---

# 27. IMPLEMENTATION PROCESS

Before writing frontend code:

1. Inspect the current FastAPI routes.
2. Inspect request/response schemas.
3. Inspect broker connection endpoints.
4. Inspect execution endpoints.
5. Inspect reconciliation endpoints.
6. Inspect docker-compose.
7. Inspect existing README.
8. Determine the minimum API surface needed.

Then implement the frontend.

Do not guess backend contracts.

---

# 28. VALIDATION

After implementation run:

1. Frontend typecheck
2. Frontend build
3. Existing backend tests
4. Ruff
5. mypy
6. Docker build
7. docker compose up --build
8. Verify PostgreSQL
9. Verify API health
10. Verify frontend loads
11. Verify Mock Broker connection
12. Execute sample portfolio
13. Verify execution results appear
14. Verify existing backend smoke tests still pass

Do not consider the frontend complete if it breaks the existing backend Compose workflow.

---

# 29. FINAL REPORT

When finished, report:

### Frontend implemented
- framework
- files created
- features implemented

### Backend changes
- explicitly list any backend changes
- if none, say "No backend changes required."

### Validation
- frontend build
- backend tests
- lint
- typecheck
- Docker
- Compose
- manual smoke test

### Known limitations
Be honest.

Especially mention:
- mock broker is the recommended evaluator flow
- real brokers are not live-certified
- live trading remains disabled by default
- OAuth behavior depends on existing backend implementation

### IMPORTANT FINAL RULE

This is a BONUS frontend.

If you encounter a problem that would require significant changes to the backend execution engine, STOP and report the problem instead of rewriting the backend.

Preserve the current working Problem 1 and Problem 2 implementation.