# Broker Integration Research

Last verified: **2 October 2026**

This document records the research gate that must pass before a real broker
adapter is implemented. Sources are broker-owned documentation, support pages,
developer forums maintained by the broker, and official broker repositories.
No endpoint or behavior in this document has been tested with a funded account.

## Decision

The five proposed integrations are:

1. Zerodha Kite Connect
2. DhanHQ API v2
3. Angel One SmartAPI
4. Groww Trading API
5. Upstox Developer API

FYERS is not selected. A final search of its official support site and
`myapi.fyers.in/docsv3` did not expose a complete, readable current v3 REST
contract. Broker-owned support material confirms app activation and compliance
requirements, but does not independently establish every endpoint, payload,
status mapping, and rate limit needed for a safe implementation. It would be
misleading to infer those details from samples, older SDK behavior, or
community code.

Indiabulls is also not selected. It advertises XTS/Open API access, but a
complete, current, broker-specific public contract for authentication,
endpoints, token lifecycle, rate limits, and sandbox provisioning could not be
verified. Generic Symphony XTS documentation is not sufficient evidence of
Indiabulls' deployed contract.

“Implemented” will mean a real adapter using a documented broker API, with
request/response contract tests. It will not mean “live-certified.” Live
certification requires an approved broker app, credentials, a configured
redirect, a compliant static egress IP where required, and controlled
minimum-quantity testing by the account owner.

## Cross-broker conclusions

- A ticker alone is not a safe instrument identity. Exchange and series can be
  ambiguous, while Angel One and Upstox require broker instrument tokens.
  Resolution must return exactly one current equity instrument or fail closed.
- Access tokens are short-lived and generally require daily user interaction.
  The service must handle expiry and must never store account PINs, passwords,
  OTPs, or TOTP seeds.
- An HTTP-successful place-order response is an acknowledgement, not proof of
  execution. The engine must query order status/trades.
- Broker tags and reference IDs assist reconciliation but are not documented as
  exactly-once idempotency guarantees.
- A timeout after submission is `UNKNOWN`. The engine must query by broker order
  ID or correlation tag and must not blindly submit again.
- Delivery sales may require DDPI/POA or a human CDSL TPIN/OTP flow. The system
  must surface `AUTHORIZATION_REQUIRED`; it must not automate or bypass TPIN.
- Static-IP and algo-order requirements changed materially in 2026. Deployment
  from an ordinary laptop or dynamic cloud egress may be unable to place orders.
- The local demonstration must use `MockBrokerAdapter`. Real adapters remain
  credential-gated and live trading disabled by default.

## Zerodha Kite Connect

### Access and authentication

- Requires a Zerodha account and an app created in the Kite developer console.
- Redirect the user to
  `https://kite.zerodha.com/connect/login?v=3&api_key=...`.
- The registered callback receives a short-lived `request_token`.
- Exchange it server-side with `POST /session/token`, passing `api_key`,
  `request_token`, and
  `checksum = SHA256(api_key + request_token + api_secret)`.
- Subsequent requests use
  `Authorization: token <api_key>:<access_token>` and
  `X-Kite-Version: 3`.
- The access token expires at 06:00 the following day or earlier on
  logout/session invalidation. A refresh token is only available to certain
  approved platforms; daily login must be assumed for a normal retail app.
- From 1 April 2026, order placement/modification/cancellation must originate
  from a whitelisted static IP. Zerodha's official forum also states that market
  and SL-M orders require non-zero market protection under the updated rules.

### Trading contract

- Holdings: `GET /portfolio/holdings`.
- Place: `POST /orders/:variety`, normally `/orders/regular`.
- Status/reconciliation: `GET /orders`, `GET /orders/:order_id`,
  `GET /trades`, and `GET /orders/:order_id/trades`.
- Cancel: `DELETE /orders/:variety/:order_id`.
- Required order context includes `tradingsymbol`, `exchange`,
  `transaction_type`, `quantity`, `product`, and `order_type`.
- Optional `tag` is at most 20 characters. It is a correlation aid, not a
  broker idempotency promise.
- Order history is transient and retained for the trading day; local durable
  records are required.

### Instruments, limits, and delivery authorization

- Download `GET /instruments` or `/instruments/:exchange`; this is a daily
  gzipped CSV. Zerodha recommends refreshing around 08:30 IST.
- Orders use exact `exchange + tradingsymbol`. The numeric instrument token is
  primarily for market data.
- Published limits: quote 1 request/second, historical candles 3/second, order
  placement 10/second, other endpoints 10/second; additionally 400 orders/minute,
  5,000/day, and no more than 25 modifications per order.
- A delivery sell without DDPI/POA may return HTTP 428. Zerodha documents
  `POST /portfolio/holdings/authorise` followed by a user redirect to its CDSL
  authorization page. The application cannot enter TPIN/OTP for the user.
- No API sandbox is documented.
- Official Python SDK: `kiteconnect`,
  [zerodha/pykiteconnect](https://github.com/zerodha/pykiteconnect).

### Official sources

- [Authentication](https://kite.trade/docs/connect/v3/user/)
- [Orders](https://kite.trade/docs/connect/v3/orders/)
- [Portfolio and holdings authorization](https://kite.trade/docs/connect/v3/portfolio/)
- [Errors and rate limits](https://kite.trade/docs/connect/v3/exceptions/)
- [Instruments](https://kite.trade/docs/connect/v3/market-data-and-instruments/)
- [2026 static-IP and order-rule announcement](https://kite.trade/forum/discussion/15912/preparing-to-comply-with-sebis-retail-algo-rules-static-ip-ratelimits-order-types)

### Implementation gate

The public contract is sufficient. Implement only after the core engine tests
pass. Contract-test authentication signing, exact instrument matching,
holdings normalization, placement, status history, 428 delivery authorization,
429 handling, and ambiguous submission timeout. Live verification requires an
account, app subscription, daily login, and whitelisted egress IP.

## DhanHQ API v2

### Access and authentication

- Requires a Dhan account. Trading APIs are documented as free; market-data
  APIs may require a paid data subscription.
- Individual users can generate a 24-hour access token in Dhan Web.
- Dhan also documents a three-step API-key flow: generate a consent session
  with app key/secret, redirect the user to Dhan's browser login, then consume
  the returned `tokenId` server-side to obtain the access token.
- API keys/secrets are documented as valid for 12 months. Access tokens are
  valid for 24 hours. An active web-generated token can be renewed for another
  24 hours; renewal invalidates the prior token.
- Calls use the `access-token` header. Order requests require the Dhan client ID
  in the payload.
- Static IP whitelisting is mandatory for order placement. Primary and
  secondary IPv4/IPv6 addresses are supported and cannot be changed again for
  seven days after modification.
- The assignment must use the browser consent flow or a manually supplied
  token. It must not collect or retain the user's PIN or TOTP seed.

### Trading contract

- Base URL: `https://api.dhan.co/v2`.
- Holdings: `GET /holdings`.
- Place: `POST /orders`.
- Status/reconciliation: `GET /orders/{order-id}`,
  `GET /orders/external/{correlation-id}`, `GET /orders`, `GET /trades`, and
  `GET /trades/{order-id}`.
- Cancel: `DELETE /orders/{order-id}` for pending orders.
- The placement contract requires `dhanClientId`, `transactionType`,
  `exchangeSegment`, `productType`, `orderType`, `validity`, `securityId`,
  quantity, and conditional price/trigger fields.
- `correlationId` supports up to 30 characters and has an official lookup
  endpoint specifically intended for recovery when the placement response or
  order ID is missed. It is still a reconciliation key, not an exactly-once
  guarantee.
- Documented statuses include `TRANSIT`, `PENDING`, `REJECTED`, `CANCELLED`,
  `PART_TRADED`, and `TRADED`.

### Instruments, limits, and delivery authorization

- Official compact and detailed instrument masters are published at
  `https://images.dhan.co/api-data/api-scrip-master.csv` and
  `api-scrip-master-detailed.csv`. A segment-specific instrument endpoint is
  also documented.
- Orders use `securityId` with a matching `exchangeSegment`, for example
  `NSE_EQ`. Resolve an exact equity row by exchange, symbol/series, and ISIN
  where available; reject zero or multiple matches.
- Published order limits: 10/second, 250/minute, 1,000/hour, and 7,000/day.
  Order modifications are capped at 25 per order. Published non-trading APIs
  allow 20/second. Rate-limit errors use `DH-904`.
- No official order sandbox is documented. Contract tests must use mocked HTTP
  responses and live tests must remain credential-gated.
- Authentication/profile responses expose DDPI status. Delivery sells without
  DDPI remain subject to depository authorization; no API behavior may be
  invented beyond the documented profile flag.
- Official Python package: `dhanhq`. The adapter can use direct documented HTTP
  contracts to keep normalization and tests explicit.

### Official sources

- [API introduction and rate limits](https://dhanhq.co/docs/v2/)
- [Authentication, consent flow, token lifecycle, and static IP](https://dhanhq.co/docs/v2/authentication/)
- [Orders and reconciliation](https://dhanhq.co/docs/v2/orders/)
- [Holdings and positions](https://dhanhq.co/docs/v2/portfolio/)
- [Instrument master](https://dhanhq.co/docs/v2/instruments/)
- [Statuses and errors](https://dhanhq.co/docs/v2/annexure/)

### Implementation gate

The current official public contract satisfies all ten selection gates.
Contract tests must cover consent/token mapping, client ID headers/payloads,
exact security ID resolution, status and correlation lookup, `PART_TRADED`,
`DH-904`, cancellation, token expiry, and timeout reconciliation. Live
certification remains impossible without the account owner's token and
whitelisted egress IP.

## Angel One SmartAPI

### Access and authentication

- Requires an Angel One account, SmartAPI app, API key, client code, account
  PIN, and current TOTP for the documented direct login endpoint.
- `POST /rest/auth/angelbroking/user/v1/loginByPassword` returns JWT, refresh,
  and feed tokens. Protected calls use the JWT.
- SmartAPI also documents a publisher redirect flow. Which flow is appropriate
  depends on app type and must be confirmed during app registration.
- The session remains active only until midnight unless logged out earlier.
- Static-IP API keys validate the source IPv4 for place/modify/cancel calls.
  Angel One's official 2026 announcement asks users to migrate and caps order
  requests at 9/second.
- The application must not retain the user's PIN or TOTP seed.

### Trading contract

- Holdings:
  `GET /rest/secure/angelbroking/portfolio/v1/getHolding` (and the documented
  all-holdings variant).
- Place:
  `POST /rest/secure/angelbroking/order/v1/placeOrder`.
- Status:
  `GET /rest/secure/angelbroking/order/v1/details/{UniqueOrderID}`, plus order
  and trade books.
- Cancel:
  `POST /rest/secure/angelbroking/order/v1/cancelOrder`.
- Orders require both exact `tradingsymbol` and `symboltoken`, as well as
  exchange, side, type, product, duration, and quantity.
- `ordertag` must be shorter than 20 characters. Persist both `orderid` and
  `uniqueorderid` when returned.

### Instruments, limits, and delivery authorization

- Angel One references
  `OpenAPI_File/files/OpenAPIScripMaster.json`, normally refreshed daily around
  08:30 IST. During research the official master URL was unreliable, and the
  broker forum contains reports of truncation/timeouts. Download atomically,
  validate the complete JSON, and retain the prior valid snapshot.
- Search can return multiple series/tokens. Require one exact exchange, equity
  series, trading-symbol, and token match.
- Current official material conflicts: an older endpoint table lists 20 order
  operations/second while the 2026 official announcement sets a combined
  9 orders/second cap. Enforce the lower current cap. Order book is documented
  at 1 request/second; prefer the individual-order endpoint or postbacks.
- No current official sandbox was found.
- Angel documents E-DIS APIs, but some detailed pages still use the old host.
  Confirm current routes before implementation. TPIN/OTP remains a human flow.
- Official Python SDK:
  [angel-one/smartapi-python](https://github.com/angel-one/smartapi-python).

### Official sources

- [User/authentication](https://smartapi.angelone.in/docs/User)
- [Orders](https://smartapi.angelone.in/docs/Orders)
- [Rate limits](https://smartapi.angelone.in/docs/RateLimit)
- [Static-IP keys and 9-order/second announcement](https://smartapi.angelone.in/smartapi/forum/topic/5352/static-ip-based-api-keys-now-live-old-flow-still-supported-temporarily)
- [E-DIS announcement](https://smartapi.angelone.in/smartapi/forum/topic/4154/announcing-edis-api-for-smartapi-users)

### Implementation gate

The order and holdings contract is sufficient, but instrument-master and E-DIS
hosts must be checked immediately before implementation. Tests must cover token
and trading-symbol mismatch, malformed/truncated instrument downloads,
conservative rate limiting, auth expiry, and post-submit unknown state.

## Groww Trading API

### Access and authentication

- Requires a Groww account and active Trading API subscription. The broker's
  public product page currently advertises a paid monthly subscription.
- Supported token paths are manual access token, API key/secret with daily
  approval, and TOTP-based token generation.
- API-key token generation signs `secret + epoch_timestamp` with SHA-256 and
  sends the API key as the bearer credential. TOTP generation uses the
  registered API/TOTP key and current TOTP.
- Calls use `Authorization: Bearer <access_token>`,
  `Accept: application/json`, and `X-API-VERSION: 1.0`.
- The access token expires daily at 06:00. No refresh-token grant is documented.

### Trading contract

- Holdings: `GET https://api.groww.in/v1/holdings/user`.
- Place: `POST https://api.groww.in/v1/order/create`.
- Status:
  `GET /v1/order/status/{groww_order_id}` or
  `GET /v1/order/status/reference/{order_reference_id}`.
- Details/list/trades endpoints provide reconciliation and fill information.
- Cancel: `POST /v1/order/cancel`.
- Always supply `order_reference_id`: the REST schema marks it required and
  constrains it to 8–20 alphanumeric characters with at most two hyphens.
- A single order can produce multiple trades; filled quantity and trade data
  must be normalized rather than assuming one fill.

### Instruments, limits, and delivery authorization

- Official instrument CSV:
  `https://growwapi-assets.groww.in/instruments/instrument.csv`.
- Resolve exact exchange, segment, equity type, series, and preferably ISIN;
  validate `buy_allowed`/`sell_allowed` when present.
- Published shared category limits: authentication 5/second and 30/minute
  (token endpoint also 150/day), create/modify/cancel 10/second and 250/minute,
  and non-trading calls 20/second and 500/minute.
- No official trading sandbox is documented.
- User details expose whether DDPI is enabled. Without DDPI, delivery sells
  require the human CDSL TPIN process; no public E-DIS API flow was verified.
- Official Python package: `growwapi`. No official public source repository was
  linked from the broker documentation.

### Official sources

- [API and authentication](https://groww.in/trade-api/docs/curl)
- [Orders](https://groww.in/trade-api/docs/curl/orders)
- [Portfolio](https://groww.in/trade-api/docs/curl/portfolio)
- [Instruments](https://groww.in/trade-api/docs/curl/instruments)
- [Python SDK](https://groww.in/trade-api/docs/python-sdk)

### Implementation gate

The public contract is sufficient. Contract tests must cover both status lookup
paths, split trades/partial fills, reference-ID constraints, token expiry,
instrument permissions, rate-limit categories, and ambiguous placement timeout.

## Upstox Developer API

### Access and authentication

- Requires an Upstox account and Developer App with API key, API secret, and
  exact registered redirect URI.
- Uses OAuth 2.0 authorization code:
  `GET /v2/login/authorization/dialog`, callback with a single-use code, then
  server-side `POST /v2/login/authorization/token`.
- The standard access token expires at 03:30 the following day. No conventional
  refresh token is documented. Manual and approval/notifier alternatives still
  require user approval.
- Bearer access tokens must remain server-side and be redacted from logs.

### Trading contract

- Holdings: `GET /v2/portfolio/long-term-holdings`.
- Place V3: `POST https://api-hft.upstox.com/v3/order/place`.
- Status: `GET /v2/order/details?order_id=...` (the documentation also supports
  tag-based lookup).
- Cancel V3:
  `DELETE https://api-hft.upstox.com/v3/order/cancel?order_id=...`.
- Orders require quantity, product, validity, price, `instrument_token`,
  order type, side, disclosed quantity, and trigger price.
- V3 may return `order_ids[]` when slicing; the adapter must preserve every
  resulting broker order ID rather than silently taking the first.
- `tag` is a correlation aid, not a documented idempotency guarantee.

### Instruments, limits, sandbox, and delivery authorization

- Official BOD files include
  `https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz`
  and exchange-specific JSON. Upstox recommends `instrument_key`, not the
  reusable `exchange_token`.
- `GET /v2/instruments/search` can resolve current instruments. Exact ticker
  matches still return both NSE and BSE, so exchange must be explicit.
- Regular-algo combined order operations: 10/second, 500/minute, and 2,000 per
  30 minutes. Standard APIs: 50/second, 500/minute, and 2,000 per 30 minutes.
- Official sandbox supports place/modify/cancel APIs. One sandbox app is
  permitted per user; sandbox tokens are valid for 30 days and cannot trade
  live. Holdings/status coverage must be checked per endpoint's sandbox flag.
- Profile data exposes POA/DDPI state. No standalone retail E-DIS endpoint was
  verified; users without authorization must complete Upstox/CDSL's human flow.
- Official Python SDK:
  [upstox/upstox-python](https://github.com/upstox/upstox-python).

### Official sources

- [Authentication](https://upstox.com/developer/api-documentation/authentication)
- [Holdings](https://upstox.com/developer/api-documentation/get-holdings)
- [Place Order V3](https://upstox.com/developer/api-documentation/v3/place-order)
- [Order details](https://upstox.com/developer/api-documentation/get-order-details)
- [Cancel Order V3](https://upstox.com/developer/api-documentation/v3/cancel-order)
- [Rate limits](https://upstox.com/developer/api-documentation/rate-limiting)
- [Instruments](https://upstox.com/developer/api-documentation/instruments)
- [Sandbox](https://upstox.com/developer/api-documentation/sandbox)

### Implementation gate

The public contract and order sandbox provide the strongest implementation
path. Implement Upstox first after the mock engine milestone. Tests must model
multiple `order_ids`, exact instrument keys, OAuth state/code handling, daily
expiry, rate limits, sandbox/live separation, and unknown-state reconciliation.

## Recommended adapter order

After the mock execution engine is complete and tested:

1. **Upstox** — complete documentation and an official order sandbox.
2. **Zerodha** — mature complete contract, but no sandbox and static-IP/live
   constraints.
3. **Groww** — complete public REST contract, but paid access and no sandbox.
4. **Angel One** — usable contract with instrument-host and rate-limit caveats.
5. **DhanHQ** — complete public v2 contract and strong correlation lookup, but
   no documented order sandbox.

Each adapter is a separate gated milestone: re-verify its sources, add its
contract tests, run the full core suite, and update this document with any
observed divergence before moving to the next broker.
