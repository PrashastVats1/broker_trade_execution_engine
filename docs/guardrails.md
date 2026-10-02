# CURSOR EXECUTION / QUALITY GATES

You are implementing a time-constrained take-home assignment.

Your priority is NOT maximum code volume.

Your priority is:

CORRECTNESS > TESTABILITY > ARCHITECTURE > DOCUMENTATION > POLISH

The final repository must be something I can actually clone, run, test, inspect, and explain to an experienced backend engineer.

==================================================
1. WORK IN SMALL VERIFIED PHASES
==================================================

Do not generate the entire application in one pass.

Before changing code:

1. Inspect the existing repository.
2. Understand the current structure.
3. Check installed/runtime versions.
4. Check git status.
5. Identify existing files that should be preserved.
6. Create/update the implementation plan.

Then implement one phase at a time.

After every major phase:

- run tests
- run type/lint checks if configured
- inspect failures
- fix them
- only then continue

Do not mark a phase complete because code "looks correct."

A phase is complete only when the relevant commands have actually been run successfully.

==================================================
2. NEVER FABRICATE EXTERNAL INTEGRATIONS
==================================================

This is especially important for broker integrations.

Do NOT create fake-looking implementations such as:

async def place_order(...):
    return {"status": "success"}

and call that a broker integration.

Every broker adapter must clearly be one of:

A. REAL IMPLEMENTATION
   Uses the broker's documented API/SDK.

B. MOCK IMPLEMENTATION
   Explicitly used for local development/testing.

C. PARTIAL IMPLEMENTATION
   Clearly documented if the broker's current API/access requirements prevent a complete implementation.

Never blur these categories.

README.md must clearly state which is which.

==================================================
3. VERIFY BROKER DOCUMENTATION
==================================================

Before implementing each real broker adapter, verify:

- authentication mechanism
- access-token lifecycle
- order endpoint/API
- holdings/positions endpoint
- order-status endpoint
- relevant rate limits
- required headers
- request format
- response format
- error format

Prefer official documentation.

Record the source URL and date checked in:

docs/broker-integrations.md

If documentation cannot be verified, do not invent an implementation.

Use an explicit TODO/limitation instead.

==================================================
4. MOCK FIRST, REAL ADAPTER SECOND
==================================================

Build the complete execution engine against a MockBrokerAdapter first.

The execution engine should not know whether it is talking to:

MockBrokerAdapter
ZerodhaAdapter
FyersAdapter
etc.

For example:

ExecutionEngine
        |
        v
BrokerAdapter
        |
        +-- MockBrokerAdapter
        +-- ZerodhaAdapter
        +-- FyersAdapter
        +-- ...

This allows the complete assignment workflow to be tested without external credentials.

==================================================
5. DESIGN FOR FAILURE, NOT JUST SUCCESS
==================================================

Every important workflow must have tests for failure.

At minimum:

SUCCESS
FAILURE
TIMEOUT
RATE LIMIT
AUTH FAILURE
ORDER REJECTION
PARTIAL FAILURE
UNKNOWN ORDER STATUS
NOTIFICATION FAILURE
DUPLICATE REQUEST

Especially test:

BROKER ACCEPTS ORDER
        ↓
NETWORK TIMEOUT
        ↓
CLIENT DOES NOT KNOW RESULT

The system must NOT automatically submit the same order again without reconciliation.

Represent this explicitly as something like:

UNKNOWN

and explain the recovery/reconciliation process.

==================================================
6. IDEMPOTENCY IS REQUIRED
==================================================

The execution endpoint must support an idempotency key.

Example:

POST /api/v1/executions
Idempotency-Key: abc123

If the same request arrives again with the same key:

Do not create a second execution.

Return the existing execution/result where appropriate.

Test this.

This is particularly important because this is a trading system.

==================================================
7. NO "EXACTLY ONCE" CLAIMS
==================================================

Do not claim that the system provides exactly-once financial order execution unless that is genuinely achievable with the selected broker APIs.

External broker APIs and network failures make this a distributed-systems problem.

Use language such as:

- idempotency
- reconciliation
- order-status verification
- at-least-once request risk
- unknown execution state

Explain the practical limitation.

==================================================
8. DOMAIN MODELS MUST BE BROKER-INDEPENDENT
==================================================

Do not leak Zerodha/Fyers/etc. response objects into the core domain.

Create normalized models.

For example:

OrderRequest
OrderResult
Holding
Position
BrokerAccount
Execution
ExecutionResult

Broker adapters translate:

Broker-specific response
        ↓
Normalized domain model

The core execution engine works only with normalized models.

==================================================
9. KEEP THE CORE LOGIC PURE WHERE POSSIBLE
==================================================

Avoid putting business logic inside FastAPI route handlers.

Bad:

@app.post("/execute")
def execute(...):
    validate()
    connect()
    place_order()
    retry()
    notify()
    save()
    ...

Prefer:

API route
   ↓
ExecutionService
   ↓
OrderManager
   ↓
BrokerAdapter

Routes should primarily:

- validate input
- call application services
- return response

==================================================
10. DATABASE SHOULD HAVE A PURPOSE
==================================================

If PostgreSQL is introduced, use it for something meaningful.

Potential persisted entities:

executions
orders
idempotency keys
broker connections/metadata
audit events

Do not create 20 tables just to make the architecture look impressive.

Document why each persisted entity exists.

==================================================
11. TRANSACTION BOUNDARIES
==================================================

Be explicit about database transactions.

For example:

1. Create execution.
2. Create order records.
3. Commit before external broker call where appropriate.
4. Submit broker order.
5. Update order status.
6. Record broker response.
7. Notify consumer.

Do not hold a database transaction open while waiting indefinitely for an external broker.

Think carefully about failure between each step.

==================================================
12. ASYNC VS SYNC
==================================================

Use async where it provides real value.

FastAPI + async HTTP calls are reasonable.

Do not make every function async merely because FastAPI supports async.

Explain important concurrency decisions.

If multiple orders can safely be executed concurrently, consider it.

But do not introduce concurrency that could create broker rate-limit problems or make execution ordering unsafe.

==================================================
13. RATE LIMITING
==================================================

Do not implement naive:

retry()
retry()
retry()

Use:

- bounded retries
- exponential backoff
- jitter
- retry only where safe

For order submission, carefully distinguish:

SAFE TO RETRY

from:

MUST RECONCILE FIRST

Document this.

==================================================
14. OBSERVABILITY
==================================================

Add structured logging around:

execution_id
order_id
broker
symbol
side
quantity
status
latency
error category

Never log:

access tokens
refresh tokens
API secrets
authorization headers
full sensitive broker responses

Make logs useful for debugging a failed execution.

==================================================
15. CONFIGURATION
==================================================

All environment-specific configuration should come from environment variables.

Provide:

.env.example

Never commit:

.env
credentials
tokens
private keys

Check git status and git diff before finalizing.

==================================================
16. TEST PYRAMID
==================================================

Prioritize:

Many unit tests
        ↓
Some integration tests
        ↓
Small number of API/e2e tests

Unit test:

- execution logic
- adapters
- retry behavior
- idempotency
- state transitions
- validation

Integration test:

- database
- FastAPI
- mock broker

End-to-end test:

- submit portfolio
- execute
- receive result
- inspect final status

Do not make the whole test suite dependent on live broker APIs.

==================================================
17. TEST THE ASSIGNMENT AS A REVIEWER WOULD
==================================================

Create a final test scenario:

Scenario:

User connects MockBroker.

Current holdings:

RELIANCE: 10
TCS: 5

Requested rebalance:

SELL RELIANCE: 5
BUY INFY: 10
SELL TCS: 2

Expected:

RELIANCE SELL 5
INFY BUY 10
TCS SELL 2

Then test:

INFY fails.

Expected final result:

PARTIAL_SUCCESS

and the notification clearly identifies:

successful orders
failed orders
execution ID
failure reason

Then test retry/idempotency.

==================================================
18. API CONTRACT
==================================================

Keep request and response schemas explicit.

Generate OpenAPI documentation.

Do not return arbitrary dictionaries everywhere.

Use Pydantic response models.

Document example requests and responses.

==================================================
19. SECURITY REVIEW
==================================================

Before finalizing, inspect the code for:

- hardcoded secrets
- token leakage
- unsafe logging
- missing input validation
- SQL injection risk
- unsafe URL construction
- insecure CORS
- debug mode
- exposed credentials
- unprotected sensitive endpoints

This is a financial platform assignment.

==================================================
20. PROBLEM 2 MUST BE FINANCIALLY CORRECT
==================================================

Do not write a generic "data platform" architecture.

The design must explicitly handle:

announcement time
availability time
economic period
ingestion time
restatements
late-arriving data
look-ahead bias

The historical query should conceptually answer:

"What information was available at timestamp T?"

rather than:

"What is the latest value for this company?"

Use concrete examples.

==================================================
21. DO NOT OVERENGINEER PROBLEM 2
==================================================

A founding engineer should demonstrate judgment.

Do not automatically choose:

Kafka
Kubernetes
Spark
Flink
Cassandra
Redis
ClickHouse
Snowflake

just because they are popular.

For every major component answer:

WHY?

WHAT WORKLOAD DOES IT SOLVE?

WHAT WOULD WE USE INSTEAD AT SMALLER SCALE?

WHAT PROBLEM DOES IT INTRODUCE?

If a simpler architecture works, choose it.

==================================================
22. ARCHITECTURE DOCUMENT MUST BE IMPLEMENTABLE
==================================================

The Problem 2 document should contain enough detail that another engineer could begin implementation.

Include:

- data schemas
- event flow
- storage layout
- retention policy
- point-in-time query logic
- derived metric computation
- caching strategy
- API boundaries
- failure handling
- scaling strategy

Avoid vague statements such as:

"Use a scalable distributed architecture."

Instead:

"Store raw ticks in X because..."

==================================================
23. ARCHITECTURE DIAGRAMS
==================================================

Use Mermaid.

At minimum create:

docs/trade-execution-architecture.md
docs/data-platform-architecture.md

Diagrams should be understandable without reading the entire codebase.

==================================================
24. FRONTEND IS OPTIONAL
==================================================

Do not start frontend work until:

- backend works
- tests pass
- Docker works
- README is substantially complete
- Problem 2 document is complete

If there is insufficient time, skip frontend.

A working backend beats a beautiful frontend.

==================================================
25. README MUST MATCH REALITY
==================================================

Every command in README.md must actually work.

Do not write:

"Run docker-compose up"

unless it has actually been tested.

Do not claim:

"All tests pass"

unless the tests were actually run.

Do not claim:

"Supports five brokers"

if two are only mocked.

README must distinguish:

IMPLEMENTED
MOCKED
PARTIAL
NOT IMPLEMENTED

==================================================
26. FINAL AUTOMATED CHECK
==================================================

Before declaring completion, run a final checklist.

Check:

[ ] Fresh clone works
[ ] Docker build works
[ ] Docker Compose works
[ ] API starts
[ ] OpenAPI loads
[ ] Database starts
[ ] Tests pass
[ ] Mock execution works
[ ] First-time portfolio works
[ ] Rebalance works
[ ] Partial failure works
[ ] Rate-limit behavior tested
[ ] Timeout behavior tested
[ ] Unknown order state handled
[ ] Idempotency tested
[ ] Notification tested
[ ] Five broker adapters accounted for
[ ] No secrets committed
[ ] .env.example exists
[ ] README commands tested
[ ] Architecture diagrams exist
[ ] Problem 2 document is 1000–1500 words
[ ] Point-in-time correctness explicitly explained
[ ] Historical look-ahead bias addressed
[ ] Live vs historical API paths addressed
[ ] Retention/downsampling addressed
[ ] Git diff reviewed

==================================================
27. GIT DISCIPLINE
==================================================

Keep commits logical.

Suggested commits:

1. project bootstrap
2. domain + broker abstraction
3. execution engine
4. persistence + idempotency
5. broker adapters
6. resilience + notifications
7. tests
8. Docker + documentation
9. architecture/design document
10. optional frontend

Do not commit generated files, secrets, caches, virtual environments, or node_modules.

==================================================
28. FINAL REVIEW FROM THE PERSPECTIVE OF KALPI
==================================================

Before finishing, pretend you are the Kalpi reviewer.

Ask:

"Can I understand this engineer's architecture in 5 minutes?"

"Can I see that they understand financial execution risk?"

"Can I see that they understand distributed-system failure modes?"

"Can I see that they understand point-in-time financial data?"

"Can I add another broker without rewriting the system?"

"Can I run this locally?"

"Can I trust the test results?"

"Did they choose technologies because they fit the workload?"

"Did they avoid unnecessary infrastructure?"

"Is there anything in this repository that looks fabricated?"

Fix issues you find.

==================================================
29. STOP CONDITIONS
==================================================

Do not move to the next major phase if:

- tests are failing
- architecture contradicts the assignment
- broker implementation is based on unverified API behavior
- Docker is broken
- secrets are present
- README instructions are wrong
- core execution behavior is untested

Fix the problem first.

==================================================
30. FINAL RESPONSE TO ME
==================================================

At the end, provide:

A. What was implemented.
B. What was tested.
C. Exact test commands and actual results.
D. What is mocked.
E. What uses real broker APIs.
F. Known limitations.
G. Remaining risks.
H. Files I should inspect before submission.
I. Things I should be ready to explain during the interview.
J. A final assignment requirement checklist.

Do not hide limitations to make the project appear more complete.
Technical honesty is more valuable than pretending everything is production-ready.