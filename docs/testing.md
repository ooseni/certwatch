# Testing

How CertWatch is tested, what each suite proves, and the results of every phase.

## Strategy

| Layer | Runs on | Proves | Command |
|---|---|---|---|
| **Static checks** | local (CI from phase 5) | Python style and common bugs, including bandit security rules (ruff); the SAM template is valid CloudFormation (cfn-lint, `sam validate`) | `make lint validate` |
| **Secret scanning** | every commit and push (git hooks; CI from phase 5) | no credentials, private keys, oversized files or conflict markers get committed (gitleaks, pre-commit-hooks) | `pre-commit run --all-files` |
| **Unit** | local, no Docker, no network | request validation, every route's status codes and error shapes, pagination tokens, response formatting; the SSRF guard, real TLS handshakes against a local server, and the whole check run | `make test` |
| **Integration** | LocalStack in Docker | the deployed stack end to end: HTTP API → Lambda → DynamoDB and the scheduled checker → SNS, with the real template, IAM policy and routing | `make ls-up ls-deploy ls-test` |
| **Smoke** (phase 4) | real AWS, `dev` stage | the same stack on AWS behaves as it does on LocalStack | planned |

Unit tests run in under a second and gate every change. Integration tests take about 12 seconds once the
stack is deployed, and cover what unit tests can't: CloudFormation, IAM, API Gateway routing and real
DynamoDB semantics such as conditional writes and scan pagination.

## Suites

### Unit: `tests/unit` (174 tests)

| File | Tests | Covers |
|---|---|---|
| `test_validation.py` | 66 | Hostname normalisation (case, trailing dot, internationalised names to punycode). Rejection of schemes, paths, ports, credentials, IPv4 and IPv6 addresses (including the metadata address `169.254.169.254`), single-label and special-use names (`localhost`, `.local`, `.internal`, `.test`), malformed labels and names over 253 characters. Body rules: field types and ranges (JSON `true` is not a port), unknown fields, PATCH restrictions, `limit` parsing, plain and base64 bodies. |
| `test_domains_api.py` | 25 | Every route against an in-memory store: `201` with `Location`, `409` for duplicates (including case and trailing-dot variants), `400` for invalid input, `404` for unknown domains, pagination across pages, partial PATCH, `204` delete then `404`, unknown routes, and a `500` that logs the cause but returns only a generic message. |
| `test_store.py` | 7 | Page tokens round-trip; forged or corrupt tokens are rejected; DynamoDB `Decimal` numbers become JSON numbers. |
| `test_health.py` | 2 | Health response fields and the default stage. |
| `test_certs.py` | 54 | The SSRF guard against 23 non-public addresses (private, loopback, link-local, carrier-grade NAT, multicast, reserved, IPv4-mapped, 6to4, Teredo) and 5 public ones; a name resolving to both a public and a private address blocks entirely; DNS failures and empty answers. Real TLS handshakes against a server started per test: a valid certificate is described (subject, issuer, serial, key type), **an expired one is still read**, RSA and EC keys, a closed port, a handshake that never completes, a port serving plain text, unparseable DER, and falling back to a second address. Status and days-remaining arithmetic, including the inclusive window edge and part of a day counting as zero. |
| `test_checker.py` | 20 | A run against a fake store: a healthy domain is recorded and not alerted; a domain inside its window is; every failure kind is stored and alerted; a failed check keeps the expiry it last knew; an unexpected exception costs only that domain; a domain deleted mid-run is not recreated; `Decimal` ports and windows from DynamoDB; the digest's ordering, its one-line-per-domain layout and the SNS subject limit; and the handler's environment defaults. |

### Integration: `tests/integration` (14 tests, LocalStack)

| Test | Verifies |
|---|---|
| `test_health` | `GET /health` through API Gateway and Lambda |
| `test_domain_lifecycle` | `POST` (normalised name, defaults, `Location`) → the item exists in DynamoDB, read directly → `GET` → `PATCH` persisted → `DELETE` removes the item → `404` on read and on a second delete |
| `test_registering_the_same_domain_twice_conflicts` | the conditional write returns `409` |
| `test_invalid_input_is_rejected_before_it_reaches_the_table` (4 cases) | invalid JSON, a URL, the metadata IP and an unknown field all return `400` |
| `test_listing_pages_through_every_domain` | `limit=2` pagination over a real DynamoDB scan, with no domain appearing twice |
| `test_a_forged_page_token_is_rejected` | an invalid `next_token` returns `400` |
| `test_a_domain_that_resolves_inward_is_blocked_not_connected_to` | the SSRF guard inside the deployed Lambda: `localhost.localstack.cloud` is a public DNS name that resolves to loopback, and is refused with that reason rather than dialled |
| `test_every_domain_gets_a_result_the_api_can_show` | the checker's write-back, through its own IAM policy, read back through `GET /domains/{domain}` |
| `test_one_run_publishes_exactly_one_digest` | one SNS publish per run, read from a temporary SQS queue subscribed to the real topic, with each domain on one line |
| `test_an_expired_certificate_is_read_and_reported` | `expired.badssl.com` is stored as `expired` with its real expiry date — the case a verifying handshake would refuse |
| `test_a_valid_certificate_outside_its_window_is_recorded_but_not_alerted` | a healthy certificate is recorded with its issuer and days remaining, and kept out of the digest |

The suite is safe to run repeatedly:
- Each test uses unique `it-<random>.example.com` names and deletes them afterwards, even when it fails.
- The table fixture refuses to run unless `AWS_ENDPOINT_URL` points at LocalStack.
- `make ls-test` supplies dummy credentials, so nothing can reach a real account.
- The two tests that need `badssl.com` skip themselves, with a reason, when this host cannot reach it.
- The checker tests create their own SQS queue per test and unsubscribe it afterwards.

## Coverage

Unit-test line coverage (`make test`, measured with pytest-cov):

| Module | Statements | Covered |
|---|---|---|
| `api/domains.py` | 60 | 98% |
| `api/health.py` | 5 | 100% |
| `certs.py` | 102 | 98% |
| `checker.py` | 84 | 93% |
| `http.py` | 8 | 100% |
| `validation.py` | 85 | 98% |
| `store.py` | 104 | 39% |
| **Total** | **448** | **83%** |

`store.py`'s DynamoDB calls are exercised only by the integration suite, and `checker.py`'s uncovered
lines are the two lazy clients (`store()` and `publish()`) that only exist inside Lambda. That code runs
in LocalStack's Lambda containers, where coverage can't instrument it, so this figure understates what is
actually tested.

## Results log

Newest first. Each phase records the environment and every check that was run, including failures.

### Phase 3: scheduled checks and SNS alerts (2026-10-04)

Environment: Ubuntu 26.04.1 LTS on WSL2, Python 3.14.4, cryptography 50.0.2, pytest 9.1.1, pytest-cov
7.1.0, ruff 0.16.8, cfn-lint 1.57.0, SAM CLI 1.166.2, LocalStack 2026.8.3 (Ultimate plan), Docker Engine
29.8.1.

| Check | Result |
|---|---|
| `make lint` (ruff check, ruff format --check, cfn-lint) | pass |
| `make validate` (sam validate --lint) | pass |
| `make test` (unit) | **174 passed** in 9 s, 83% coverage |
| `make ls-test` (integration, LocalStack) | **14 passed** in 18 s |
| `make ls-check` against four deliberately varied domains | one digest, 4 checked, statuses `expired`, `expiring`, `blocked`, `unreachable` |
| `validate_adr.py --md docs/decisions` | 0 errors, 0 warnings |

The manual run is the clearest evidence the checker works, so it is recorded in full. `expired.badssl.com`
came back `expired` with `notAfter` 2015-04-12 and issuer "COMODO RSA Domain Validation Secure Server CA",
4193 days ago; `badssl.com` with a 365-day window came back `expiring`, 85 days left;
`localhost.localstack.cloud` was refused as `blocked` — "resolves to ::1, a loopback address" — without a
connection being made.

Found along the way:
- **A 16 MB package made CloudFormation give up on the function.** Adding `cryptography` to
  `src/requirements.txt` put it in all three functions, because they share one `CodeUri`. The stack then
  failed to deploy: `Resource deployment for resource CheckerFunction timed out`. Measured directly, a
  16 MB function takes about 65 s to leave `Pending` on LocalStack against under 3 s for a 44 KB one, and
  CloudFormation's per-resource ceiling is 120 s. Moving the library into a layer attached only to the
  checker took every function package back to 68 KB and fixed the deploy — and is the better shape on
  real AWS too, since the API functions never parse a certificate ([ADR-0008](decisions/0008-parse-certificates-with-cryptography-in-a-lambda-layer.md)).
- **The guard answers on IPv6 first.** Inside the Lambda container `localhost.localstack.cloud` resolves
  to `::1` before `127.0.0.1`, which a first version of the integration test had not allowed for. The
  guard was right; the assertion was too narrow. Worth knowing: an IPv4-only blocklist would have let
  this through, which is why the guard tests `is_global` rather than listing private ranges.
- **Carrier-grade NAT is neither private nor global.** `ipaddress` reports `100.64.0.1` as
  `is_private == False` *and* `is_global == False`, while multicast addresses report `is_global == True`.
  A guard written as "reject if private" would allow CGNAT; one written as "allow if global" would allow
  multicast. The guard requires `is_global and not is_multicast`, and a test covers both traps.
- **The digest stuttered.** `BLOCKED  example.com:443  example.com resolves to ...` repeated the name,
  because the exception message began with the host that the line already named. The messages now start
  at the reason.

### Tooling: secret-scanning git hooks (2026-09-23)

Added `.pre-commit-config.yaml`: gitleaks v8.30.1 plus detect-private-key, check-added-large-files (1 MB)
and check-merge-conflict from pre-commit-hooks v6.0.0, installed for pre-commit and pre-push.
Environment: pre-commit 4.6.2, gitleaks 8.30.1, Ubuntu 26.04.1 LTS on WSL2.

| Check | Result |
|---|---|
| `pre-commit run --all-files` (all four hooks, every tracked file) | pass |
| `gitleaks git --redact` (full history, 15 commits) | no leaks found |
| A fake GitHub token staged in a scratch repository | commit blocked, value redacted |

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
