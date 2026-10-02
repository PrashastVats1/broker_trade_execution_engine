You are helping me complete a take-home engineering assignment for Kalpi, an Indian systematic quantitative investing platform.

You must approach this as a real engineering submission, not as a coding exercise or a generic demo.

The goal is to produce a public GitHub-ready repository containing:

1. A working Python + FastAPI Portfolio Trade Execution Engine.
2. Docker/Docker Compose setup.
3. Tests and mocks that allow the system to run without real broker credentials.
4. Integration adapters for at least 5 Indian brokers.
5. A small optional frontend if it can be implemented without compromising the backend.
6. A 1000–1500 word technical design document for Kalpi's multi-frequency financial data platform.
7. A comprehensive README explaining the architecture, setup, decisions, trade execution model, broker adapters, testing, and limitations.
8. Architecture diagrams.
9. Clean code that demonstrates a Founding Engineer / Backend Infra Engineer mindset.

IMPORTANT:
Do not rush into coding.
First understand the assignment, research the relevant broker APIs and technical constraints, design the system, then implement it incrementally.

Do not invent API behavior, endpoints, authentication flows, rate limits, or broker capabilities.
When broker behavior is uncertain, verify it from official documentation where possible and clearly document any assumptions.

==================================================
PART 1 — ASSIGNMENT REQUIREMENTS
==================================================

Build an end-to-end Portfolio Trade Execution Engine.

Input:

A desired portfolio state consisting of stocks and target quantities, or explicit rebalance instructions.

The system should:

1. Authenticate/connect to a user's stock broker.
2. Fetch current holdings where necessary.
3. Determine/execute the required trades.
4. Support at least 5 major Indian brokers.
5. Use a standardized broker adapter interface.
6. Make adding a sixth broker require minimal code changes.
7. Execute BUY/SELL/REBALANCE instructions.
8. Handle failed orders and partial failures robustly.
9. Handle API failures and rate limits.
10. Notify the consumer after execution.
11. Run entirely through Docker.
12. Provide tests without requiring real broker credentials.

Target brokers should include at least five from:

- Zerodha
- Fyers
- Angel One
- Groww
- Upstox
- Indiabulls

Research which five are currently practical to implement based on publicly available APIs/documentation.

Do NOT claim that a broker is supported if the implementation is only a stub.

If a broker cannot realistically be implemented within the assignment because of API/access restrictions, document the limitation clearly and choose another broker where appropriate.

==================================================
PART 2 — TECHNOLOGY
==================================================

Required:

- Python
- FastAPI
- Docker
- docker-compose.yml

Preferred:

- Python 3.12+
- Pydantic
- SQLAlchemy if persistence is required
- PostgreSQL where relational persistence is useful
- pytest
- httpx
- asyncio where appropriate

Use a modular architecture.

Suggested structure:

app/
    main.py

    api/
        routes/

    core/
        config.py
        exceptions.py
        logging.py

    domain/
        models/
        enums/
        services/

    brokers/
        base.py
        zerodha.py
        fyers.py
        angel_one.py
        groww.py
        upstox.py

    execution/
        engine.py
        order_manager.py
        retry.py

    notifications/
        base.py
        webhook.py
        console.py

    repositories/

    schemas/

tests/
    unit/
    integration/

frontend/
    ...

Do not blindly follow this structure if another structure is materially better.
Explain architectural choices in README.md.

==================================================
PART 3 — BROKER ADAPTER ARCHITECTURE
==================================================

Create a common broker interface.

For example, conceptually:

BrokerAdapter

Methods may include:

- authenticate()
- get_profile()
- get_holdings()
- get_positions()
- place_order()
- get_order_status()
- cancel_order()
- get_quote()

Use appropriate domain models rather than leaking broker-specific response formats throughout the application.

The execution engine must depend on the abstraction, NOT on individual broker implementations.

For example:

ExecutionEngine
    -> BrokerAdapter
        -> ZerodhaAdapter
        -> FyersAdapter
        -> AngelOneAdapter
        -> GrowwAdapter
        -> UpstoxAdapter

Broker-specific authentication, request formats, response parsing, and errors must remain inside each adapter.

Explain exactly how adding a sixth broker would work.

==================================================
PART 4 — AUTHENTICATION
==================================================

Research each selected broker's current authentication mechanism.

Document:

- OAuth/token/API-key mechanism where applicable
- required credentials
- token lifecycle
- refresh behavior
- redirect requirements
- whether authentication is suitable for this assignment
- relevant security considerations

Do NOT put real credentials into the repository.

Use environment variables.

Provide:

.env.example

Never commit:

- API keys
- secrets
- access tokens
- refresh tokens
- client secrets

The README should explain how a real broker could be configured.

For local development, provide mocked broker implementations or mock transport so the entire execution flow can be demonstrated without a real brokerage account.

==================================================
PART 5 — TRADE EXECUTION ENGINE
==================================================

Implement the core execution engine carefully.

There are two major workflows.

-----------------------------------
A. FIRST-TIME PORTFOLIO
-----------------------------------

Example input:

{
    "broker": "zerodha",
    "portfolio": [
        {
            "symbol": "RELIANCE",
            "quantity": 10
        },
        {
            "symbol": "TCS",
            "quantity": 5
        }
    ]
}

If the user has no holdings:

BUY:

RELIANCE 10
TCS 5

-----------------------------------
B. REBALANCING
-----------------------------------

The assignment explicitly states that the backend does NOT need to calculate the delta.

Instead, the input can directly contain instructions such as:

SELL:
    10 RELIANCE

BUY:
    5 INFY

REBALANCE:
    RELIANCE +5
    TCS -2

Therefore implement an explicit execution instruction model.

Example:

{
    "broker": "zerodha",
    "orders": [
        {
            "symbol": "RELIANCE",
            "side": "SELL",
            "quantity": 10
        },
        {
            "symbol": "INFY",
            "side": "BUY",
            "quantity": 5
        }
    ]
}

Do not unnecessarily build portfolio optimization logic that the assignment explicitly says is out of scope.

==================================================
PART 6 — ORDER EXECUTION SAFETY
==================================================

Treat this as financial infrastructure.

Implement:

- unique execution ID
- unique client/order correlation ID where appropriate
- idempotency protection
- order state tracking
- validation before execution
- clear BUY/SELL semantics
- quantity validation
- symbol validation where possible
- broker error normalization
- timeout handling
- retry handling
- rate-limit handling
- partial failure handling
- execution summary
- structured logging

Think carefully about retry safety.

NEVER blindly retry a trade submission if the broker may have accepted the original order but the response was lost.

Explain how the implementation avoids duplicate trades.

A useful conceptual state machine may be:

PENDING
    ->
SUBMITTING
    ->
SUBMITTED
    ->
EXECUTED

with failure paths such as:

FAILED
CANCELLED
UNKNOWN

An UNKNOWN state is important when the client cannot determine whether a broker accepted an order.

Do not pretend that distributed exactly-once execution is trivial.

Explain the tradeoff.

==================================================
PART 7 — RATE LIMITS AND FAILURES
==================================================

Implement sensible resilience.

At minimum consider:

- HTTP timeout
- connection failure
- HTTP 429
- transient 5xx
- malformed broker responses
- authentication expiry
- rejected orders
- partial execution
- broker unavailable
- duplicate submission
- notification failure

Use bounded retries only where safe.

Use exponential backoff with jitter where appropriate.

Do not retry non-idempotent order submission blindly.

Normalize broker errors into application-level exceptions such as:

BrokerAuthenticationError
BrokerRateLimitError
BrokerUnavailableError
OrderRejectedError
OrderStatusUnknownError
ValidationError

Document the strategy.

==================================================
PART 8 — NOTIFICATIONS
==================================================

After execution completes, notify the consumer.

The assignment allows:

- mocked webhook
- WebSocket event
- email
- console log

Implement at least one clean notification interface.

Prefer:

NotificationService
    -> ConsoleNotifier
    -> WebhookNotifier

A completed execution should produce a summary similar to:

{
    "execution_id": "...",
    "status": "PARTIAL_SUCCESS",
    "broker": "zerodha",
    "orders": [
        {
            "symbol": "RELIANCE",
            "side": "BUY",
            "quantity": 10,
            "status": "EXECUTED"
        },
        {
            "symbol": "INFY",
            "side": "BUY",
            "quantity": 5,
            "status": "FAILED",
            "error": "Insufficient funds"
        }
    ]
}

Notification failures must not incorrectly mark a successful trade execution as failed.

==================================================
PART 9 — API DESIGN
==================================================

Design a clean REST API.

Potential endpoints:

POST /api/v1/executions
GET /api/v1/executions/{execution_id}
GET /api/v1/executions/{execution_id}/orders

POST /api/v1/brokers/{broker}/connect
GET /api/v1/brokers
GET /api/v1/brokers/{broker}/status

POST /api/v1/notifications/test

You may change this design if you have a better approach.

Provide OpenAPI documentation automatically through FastAPI.

Use Pydantic request/response models.

Validate inputs at the API boundary.

Do not expose internal broker-specific structures through the public API.

==================================================
PART 10 — PERSISTENCE
==================================================

Decide whether the assignment needs persistence.

If persistence is useful, use PostgreSQL.

Persist at least:

- execution
- order
- execution status
- broker
- timestamps
- error information
- idempotency key

Do not introduce a database purely because "production systems use databases."

Explain the decision.

The system should remain easy to run locally.

Docker Compose should bring up required infrastructure.

==================================================
PART 11 — TESTING
==================================================

Testing is extremely important.

Build a meaningful test suite.

At minimum test:

1. First-time portfolio execution.
2. Multiple BUY orders.
3. Multiple SELL orders.
4. Mixed BUY/SELL.
5. Rebalance instructions.
6. Invalid quantity.
7. Invalid symbol.
8. Broker authentication failure.
9. Broker timeout.
10. Broker rate limit.
11. Broker order rejection.
12. Partial execution.
13. Unknown order state.
14. Retry behavior.
15. Idempotency.
16. Notification success.
17. Notification failure.
18. Adapter selection.
19. Each supported broker adapter's request/response normalization.
20. API endpoint behavior.

Use mocked broker responses.

Do NOT require actual broker accounts for tests.

If real broker sandbox environments exist and are practical, document how integration tests could be added separately.

Run the tests and report the actual result.

Never claim tests pass unless they were actually run.

==================================================
PART 12 — FRONTEND BONUS
==================================================

If time permits, create a very small frontend.

It should support:

1. Select broker.
2. Connect/mock authentication.
3. Enter/upload target portfolio.
4. Review proposed orders.
5. Click Execute.
6. Display execution ID.
7. Display order statuses.
8. Display failures.

Do not spend excessive time making it visually beautiful.

The backend is the primary evaluation target.

A simple React/Vite frontend is sufficient.

If frontend implementation risks compromising backend quality, prioritize backend quality.

==================================================
PART 13 — SECURITY
==================================================

Treat this as financial infrastructure.

Document:

- secret management
- token storage
- authentication
- authorization
- HTTPS requirement in production
- logging without secrets
- PII considerations
- broker credential handling
- audit logging
- idempotency
- replay protection where applicable

Do not log:

- access tokens
- refresh tokens
- API secrets
- authorization headers
- unnecessary personal information

Do not pretend this system is production-ready for real money.

Clearly distinguish:

ASSIGNMENT DEMO
from
PRODUCTION HARDENING REQUIRED

==================================================
PART 14 — DO NOT OVERENGINEER
==================================================

The assignment has a 24-hour deadline.

Prioritize:

1. Correctness
2. Clear architecture
3. Working core execution flow
4. Broker adapter abstraction
5. Testing
6. Failure handling
7. Docker
8. README
9. Design document
10. Frontend polish

Do NOT introduce:

- Kubernetes
- Kafka
- microservices
- event sourcing
- CQRS
- distributed consensus
- unnecessary cloud infrastructure

unless there is a concrete requirement that justifies it.

A modular monolith is completely acceptable.

The architecture should demonstrate that you know when NOT to introduce infrastructure.

==================================================
PART 15 — PROBLEM STATEMENT 2
==================================================

Create a technical design document of approximately 1000–1500 words.

Title:

"Multi-Frequency Financial Data Platform"

The platform must handle:

- NSE + BSE
- 5,000+ symbols
- Live tick data
- Daily EOD data
- Quarterly fundamentals
- Annual balance-sheet data

The central problem is point-in-time correctness.

Example:

A company releases Q3 results at 7 PM on Tuesday.

Historical calculations must not use that information for calculations performed before 7 PM Tuesday.

A 2022 P/E calculation must use the EPS information that was actually known to the market at that point in time.

==================================================
Q1 — STORAGE
==================================================

Design the storage stack.

Discuss specific technologies for:

- tick data
- EOD data
- fundamentals
- metadata
- point-in-time versions
- historical queries
- archival

Do not simply say "use a time-series database."

Explain WHY.

Consider appropriate technologies such as:

- PostgreSQL
- TimescaleDB
- ClickHouse
- object storage
- Parquet
- Redis
- data lake
- columnar formats

Choose a practical architecture.

Explain the tradeoffs.

==================================================
POINT-IN-TIME CORRECTNESS
==================================================

This is one of the most important parts of the assignment.

Design the schema/versioning approach so that fundamentals contain information such as:

- effective period
- announcement timestamp
- ingestion timestamp
- version
- valid-from
- valid-to

The historical query must be able to answer:

"What fundamental value was known to the system/market at timestamp T?"

Do NOT simply store:

company -> EPS

because that creates look-ahead bias.

Explain how late corrections/restatements would be represented.

Explain the distinction between:

economic period
announcement time
availability time
ingestion time

where relevant.

==================================================
ARCHIVAL
==================================================

The prompt states that 5,000 symbols producing ticks for years can become extremely large.

Design:

- hot storage
- warm storage
- cold/archive storage
- retention periods
- downsampling
- OHLC aggregation
- raw tick retention

Explain what data remains queryable and where.

Avoid simply saying "store everything forever."

==================================================
Q2 — COMPUTE ENGINE
==================================================

When a new tick arrives:

P/E may change.

When a new EPS arrives:

P/E may change.

Discuss:

- on-write
- on-read
- scheduled computation
- event-driven computation
- materialized views
- cached derived metrics

Choose a hybrid strategy if appropriate.

The user-facing live UI allows second-level latency.

Therefore do not design a sub-millisecond architecture unless there is a real reason.

Explain exactly what happens when:

A. a new price tick arrives.

B. a new fundamental is published.

==================================================
Q3 — APIs AND SERVING
==================================================

Design two API paths.

-----------------------------------
LIVE
-----------------------------------

Requirement:

Current metrics in <200ms.

Metrics:

- P/E
- Momentum
- Yield
- etc.

Explain:

- cache
- invalidation
- precomputation
- hot data
- API structure
- WebSocket/SSE if useful

-----------------------------------
HISTORICAL
-----------------------------------

Requirement:

3-year P/E chart.

Approximately 750 points.

Explain:

- historical query
- point-in-time join
- aggregation
- caching
- pagination if needed
- response format

Do not make the live API and historical API identical if their workload characteristics are different.

==================================================
Q4 — FULL ARCHITECTURE
==================================================

Create a high-level architecture diagram.

Show:

BROKER WEBSOCKETS
        |
        v
TICK INGESTION
        |
        v
STREAM PROCESSING
        |
        +------> HOT METRICS / CACHE
        |
        +------> RAW TICK STORAGE
        |
        v
DERIVED METRICS

Separately:

EOD MARKET DATA
        |
        v
HISTORICAL STORAGE

FUNDAMENTAL DATA
        |
        v
POINT-IN-TIME VERSIONED STORE
        |
        v
HISTORICAL METRIC ENGINE

Then connect both paths to:

API
 |
 +---- LIVE STOCK PAGE
 |
 +---- HISTORICAL CHART

The diagram should explicitly show the difference between the live P/E path and historical point-in-time P/E path.

Use Mermaid where appropriate so the diagram can live directly in README.md.

==================================================
PART 16 — FOUNDING ENGINEER MINDSET
==================================================

Throughout the design, explicitly demonstrate:

1. Systems thinking.
2. Failure-mode awareness.
3. Financial-data correctness.
4. Practical technology selection.
5. Operational simplicity.
6. Scalability.
7. Security.
8. Observability.
9. Developer ergonomics.
10. Ability to extend the system.

For every major technology choice, answer:

"Why this?"

and preferably:

"Why not the obvious alternative?"

For example:

Why PostgreSQL?

Why ClickHouse?

Why Redis?

Why object storage?

Why a queue?

Why not Kafka?

Why not calculate everything on read?

Do not write generic statements like:

"Kafka is scalable."

Instead explain the actual workload and whether Kafka is justified.

==================================================
PART 17 — README
==================================================

Create a comprehensive README.md containing:

1. Project overview.
2. Architecture.
3. Component responsibilities.
4. Broker adapter architecture.
5. Trade execution flow.
6. Failure handling.
7. Idempotency strategy.
8. Notification architecture.
9. Data persistence.
10. Local development.
11. Docker setup.
12. Environment variables.
13. Running tests.
14. API examples.
15. Example execution request.
16. Example response.
17. Supported brokers.
18. Broker authentication explanation.
19. Third-party libraries.
20. Why each important dependency was chosen.
21. Limitations.
22. Production-hardening roadmap.
23. Problem 2 architecture/design.
24. Architecture diagrams.

==================================================
PART 18 — GITHUB QUALITY
==================================================

The repository should look like a serious public engineering project.

Include:

README.md
LICENSE
.gitignore
.env.example
Dockerfile
docker-compose.yml
pyproject.toml or requirements.txt
tests/
docs/

Potentially:

SECURITY.md
CONTRIBUTING.md

Do not add unnecessary files just for appearance.

Ensure:

- no secrets
- no personal credentials
- no broken links
- no dead code
- no unexplained TODOs
- no fake integrations
- no fake test results

==================================================
PART 19 — RESEARCH REQUIREMENTS
==================================================

Before implementing broker adapters, research official broker documentation.

Prefer official sources for:

- authentication
- order APIs
- holdings APIs
- rate limits
- WebSocket APIs
- token lifecycle

If official documentation is unavailable, use reputable technical sources and explicitly label the source.

Do not rely on random blog posts when official documentation exists.

Record the important sources in the README.

If an API has changed recently, use the current documentation.

==================================================
PART 20 — WORKING METHOD
==================================================

Work in phases.

PHASE 1 — REQUIREMENT ANALYSIS

First produce:

- requirements checklist
- functional requirements
- non-functional requirements
- assumptions
- explicit out-of-scope items
- risks
- questions that do NOT need clarification because reasonable assumptions can be made

Then propose the architecture.

Do NOT start coding yet.

PHASE 2 — BROKER RESEARCH

Research the candidate brokers.

Create an internal comparison containing:

Broker
Authentication
Order API
Holdings API
Rate limits
Python SDK/API
Sandbox availability
Implementation complexity
Relevant official documentation

Select the five brokers that provide the strongest practical implementation path.

Do not simply choose based on popularity.

PHASE 3 — ARCHITECTURE

Produce:

- component architecture
- domain model
- broker interface
- execution state machine
- API design
- persistence model
- notification design
- failure model

Then sanity-check the architecture against the assignment.

PHASE 4 — IMPLEMENTATION

Implement incrementally.

Suggested order:

1. Project setup.
2. Domain models.
3. Broker abstraction.
4. Mock broker.
5. Execution engine.
6. Order state management.
7. Error handling.
8. Idempotency.
9. Notifications.
10. Persistence.
11. Real broker adapters.
12. API.
13. Docker.
14. Tests.
15. Frontend if time permits.

After each meaningful stage, run tests.

PHASE 5 — PROBLEM 2

Write the 1000–1500 word technical design document.

Include Mermaid architecture diagrams.

PHASE 6 — FINAL QA

Before considering the assignment complete:

Run:

- unit tests
- integration tests
- linting/type checks if configured
- Docker build
- Docker Compose startup
- API smoke test

Verify:

- README commands actually work
- Docker setup works
- tests actually pass
- no secrets exist
- .env.example is complete
- broker adapters are correctly isolated
- API documentation loads
- notification flow works
- failed orders are represented correctly
- partial execution works
- idempotency works
- assignment requirements are all covered

Then create a final REQUIREMENTS.md or FINAL_CHECKLIST.md mapping every assignment requirement to its implementation.

==================================================
PART 21 — FINAL OUTPUT TO ME
==================================================

At the end, provide:

1. Final repository structure.
2. Summary of architecture.
3. List of supported brokers.
4. Explanation of adapter pattern.
5. Explanation of execution engine.
6. Explanation of failure handling.
7. Explanation of idempotency.
8. Explanation of notification flow.
9. Test results with actual commands/results.
10. Docker commands.
11. API examples.
12. Problem 2 architecture summary.
13. Major design decisions.
14. Known limitations.
15. What I should be prepared to explain in an interview.
16. A list of likely interviewer questions and strong technical talking points.

Most importantly:

Do not optimize this for producing the largest amount of code.

Optimize it for producing a submission that makes a reviewer think:

"This engineer understands backend systems, financial execution risk, APIs, failure modes, data correctness, and can make pragmatic architecture decisions."

Be technically honest.

If something is mocked, say it is mocked.

If something is an assumption, say it is an assumption.

If something could not be verified, say so.

If a production implementation would require additional work, explicitly identify that work.

Never fabricate successful execution against a real broker.
Never fabricate benchmark numbers.
Never fabricate test results.
Never claim production readiness.

==================================================
IMPORTANT PERSONAL CONTEXT
==================================================

I am applying for the Backend/Infra Engineer / Founding Engineer role at Kalpi.

My relevant experience includes:

- Python
- FastAPI
- C#/.NET
- REST APIs
- PostgreSQL
- SQL Server
- MariaDB
- SQLAlchemy
- Docker
- CI/CD
- OAuth 2.0/OIDC
- JWT
- RFC 8693-style token exchange concepts
- delegated authorization
- policy middleware
- audit logging
- React/TypeScript
- AI/agent infrastructure

I also have a public backend project involving AI-agent authentication/delegation using FastAPI and PostgreSQL.

Do not falsely claim that I have production brokerage/trading infrastructure experience.

Instead, make the assignment itself demonstrate transferable backend/infrastructure skills.

Where useful, structure the code and documentation so that I can explain the architectural decisions naturally in an interview.

==================================================
FINAL RULE
==================================================

Do not ask me unnecessary questions.

If a reasonable engineering assumption can be made, make it, document it, and continue.

Only stop and ask me if proceeding would require making a materially consequential assumption that cannot reasonably be resolved through research.

Start with PHASE 1: REQUIREMENT ANALYSIS.
Do not begin implementation until the requirements and architecture have been clearly established.