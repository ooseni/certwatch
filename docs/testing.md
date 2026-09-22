# Testing

How CertWatch is tested, what each suite proves, and the results of every phase.

## Strategy

| Layer | Runs on | Proves | Command |
|---|---|---|---|
| **Static checks** | local (CI from phase 5) | Python style and common bugs, including bandit security rules (ruff); the SAM template is valid CloudFormation (cfn-lint, `sam validate`) | `make lint validate` |
| **Unit** | local, no Docker, no network | request validation, every route's status codes and error shapes, pagination tokens, response formatting | `make test` |
| **Integration** | LocalStack in Docker | the deployed stack end to end: HTTP API → Lambda → DynamoDB, with the real template, IAM policy and routing | `make ls-up ls-deploy ls-test` |
| **Smoke** (phase 4) | real AWS, `dev` stage | the same stack on AWS behaves as it does on LocalStack | planned |

Unit tests run in under a second and gate every change. Integration tests take about 12 seconds once the
stack is deployed, and cover what unit tests can't: CloudFormation, IAM, API Gateway routing and real
DynamoDB semantics such as conditional writes and scan pagination.

## Suites

### Unit: `tests/unit` (100 tests)

| File | Tests | Covers |
|---|---|---|
| `test_validation.py` | 66 | Hostname normalisation (case, trailing dot, internationalised names to punycode). Rejection of schemes, paths, ports, credentials, IPv4 and IPv6 addresses (including the metadata address `169.254.169.254`), single-label and special-use names (`localhost`, `.local`, `.internal`, `.test`), malformed labels and names over 253 characters. Body rules: field types and ranges (JSON `true` is not a port), unknown fields, PATCH restrictions, `limit` parsing, plain and base64 bodies. |
| `test_domains_api.py` | 25 | Every route against an in-memory store: `201` with `Location`, `409` for duplicates (including case and trailing-dot variants), `400` for invalid input, `404` for unknown domains, pagination across pages, partial PATCH, `204` delete then `404`, unknown routes, and a `500` that logs the cause but returns only a generic message. |
| `test_store.py` | 7 | Page tokens round-trip; forged or corrupt tokens are rejected; DynamoDB `Decimal` numbers become JSON numbers. |
| `test_health.py` | 2 | Health response fields and the default stage. |

### Integration: `tests/integration` (9 tests, LocalStack)

| Test | Verifies |
|---|---|
| `test_health` | `GET /health` through API Gateway and Lambda |
| `test_domain_lifecycle` | `POST` (normalised name, defaults, `Location`) → the item exists in DynamoDB, read directly → `GET` → `PATCH` persisted → `DELETE` removes the item → `404` on read and on a second delete |
| `test_registering_the_same_domain_twice_conflicts` | the conditional write returns `409` |
| `test_invalid_input_is_rejected_before_it_reaches_the_table` (4 cases) | invalid JSON, a URL, the metadata IP and an unknown field all return `400` |
| `test_listing_pages_through_every_domain` | `limit=2` pagination over a real DynamoDB scan, with no domain appearing twice |
| `test_a_forged_page_token_is_rejected` | an invalid `next_token` returns `400` |

The suite is safe to run repeatedly:
- Each test uses unique `it-<random>.example.com` names and deletes them afterwards, even when it fails.
- The table fixture refuses to run unless `AWS_ENDPOINT_URL` points at LocalStack.
- `make ls-test` supplies dummy credentials, so nothing can reach a real account.

## Coverage

Unit-test line coverage (`make test`, measured with pytest-cov):

| Module | Statements | Covered |
|---|---|---|
| `api/domains.py` | 60 | 98% |
| `api/health.py` | 5 | 100% |
| `http.py` | 8 | 100% |
| `validation.py` | 85 | 98% |
| `store.py` | 77 | 51% |
| **Total** | **235** | **83%** |

`store.py`'s DynamoDB calls are exercised only by the integration suite. That code runs inside
LocalStack's Lambda containers, where coverage can't instrument it, so this figure understates what is
actually tested.

## Results log

Newest first. Each phase records the environment and every check that was run, including failures.

### Phase 2: domain CRUD API (2026-09-22)

Environment: Ubuntu 26.04.1 LTS on WSL2, Python 3.14.4, pytest 9.1.1, pytest-cov 7.1.0, ruff 0.16.8,
cfn-lint 1.57.0, SAM CLI 1.166.2, LocalStack 2026.8.3 (paid plan, trial), Docker Engine 29.8.1.

| Check | Result |
|---|---|
| `make lint` (ruff check, ruff format --check, cfn-lint) | pass |
| `make validate` (sam validate --lint) | pass |
| `make test` (unit) | **100 passed** in 0.4 s, 83% coverage |
| `make ls-test` (integration, LocalStack) | **9 passed** in 12 s |
| `make local`, then `GET /health` | 200 |
| Manual `POST /domains` then `GET /domains` on LocalStack | 201, then 200 with the item listed |

Found along the way:
- **LocalStack's free Hobby plan doesn't emulate HTTP APIs** (API Gateway v2), X-Ray or Cognito. Its health
  endpoint still lists them as available, and CloudFormation creates non-working stand-ins, so the first
  deploy looked successful. Moved to a paid plan (trial), and now check coverage with a real API call.
- **LocalStack bug:** updating an HTTP API stage in place fails with `Stage already exists`, because it
  re-creates the stage. The first integration run failed 9/9 on the rolled-back stack. After recreating it
  (`make ls-destroy ls-deploy`), the run passed 9/9. Real CloudFormation is not affected.

### Phase 1: scaffold and health check (2026-09-21)

| Check | Result |
|---|---|
| `make lint` | pass |
| `make validate` | pass |
| `make test` (unit) | **2 passed** |
| `sam local start-api`, then `GET /health` | 200 |
