---
status: "accepted"
date: 2026-09-21
decision-makers: Sakariyau Oseni (maintainer)
---

# Serve the API through an API Gateway HTTP API

> In the context of CertWatch, facing a small JSON API (/health, /domains) that is unauthenticated until phase 6 and must stay cheap, we decided for HTTP API and neglected REST API, Lambda function URLs, to achieve cost, auth path, simplicity, accepting that the API has no WAF in front of it, so throttling and input validation carry the load until phase 6.

## Context and Problem Statement

A small JSON API (/health, /domains) that is unauthenticated until phase 6 and must stay cheap. Phase 6 will add authentication, most likely with JWTs.

## Decision Drivers

* Cost
* Auth path
* Simplicity

## Considered Options

* HTTP API
* REST API
* Lambda function URLs

## Decision Outcome

Chosen option: "HTTP API", because it best meets the decision drivers (cost, auth path, simplicity).

We will expose the API through an API Gateway HTTP API with Lambda proxy integrations, and throttle every route to 10 requests/s (burst 20) until authentication arrives in phase 6.

### Consequences

* Good, because per-request cost is the lowest of the gateway options
* Good, because JWT authorisers fit the phase 6 plan
* Bad, because no WAF rate-based rules or managed rule sets
* Bad, because abuse protection is throttling only until phase 6

### Confirmation

Integration tests call every route through the HTTP API on LocalStack; the template pins ThrottlingRateLimit 10 and ThrottlingBurstLimit 20.

## Pros and Cons of the Options

### HTTP API

API Gateway v2

* Good, because about 70% cheaper per request than REST APIs
* Good, because native JWT authorisers for phase 6
* Good, because lower latency
* Bad, because no AWS WAF association
* Bad, because no usage plans or API keys

### REST API

API Gateway v1

* Good, because AWS WAF, usage plans, request validation
* Bad, because higher cost per request
* Bad, because more configuration

### Lambda function URLs

HTTPS endpoint per function

* Good, because no gateway to pay for
* Bad, because no routing across functions
* Bad, because IAM auth or none; no request throttling

## More Information

Confidence: High.
Review by: Phase 6, when the authentication ADR is written.
Trade-offs accepted: the API has no WAF in front of it, so throttling and input validation carry the load until phase 6.
Components: Amazon API Gateway (HTTP API), AWS Lambda.
Requirements addressed: REQ-06.
Part of the CertWatch architecture decision record.
