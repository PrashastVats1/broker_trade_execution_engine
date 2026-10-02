# Security

## Assignment boundary

This repository is an educational assignment and is not approved for
unattended or production real-money trading.

## Secrets

Use environment variables only. Never commit `.env`, access/refresh tokens,
broker API secrets, account PINs, OTPs, TOTP seeds, authorization headers, or
private broker responses. Callback-generated tokens are held in process memory
for this demonstration.

Production deployment requires a KMS-backed encrypted credential store,
authenticated users, authorization policy, TLS, audit retention, static egress
IP controls, token rotation, and log redaction enforcement.

## Execution safety

Live execution is disabled unless the server sets `ALLOW_LIVE_TRADING=true` and
the request includes `confirm_live=true`. These controls reduce accidental use;
they are not an authorization system.

A timed-out broker submission must remain `UNKNOWN`. Do not manually change it
to failed or submit a replacement until broker reconciliation or human review
establishes the original outcome.

## Reporting

Do not include real credentials, account identifiers, holdings, or order data
in a public issue. Report vulnerabilities privately to the repository owner.
