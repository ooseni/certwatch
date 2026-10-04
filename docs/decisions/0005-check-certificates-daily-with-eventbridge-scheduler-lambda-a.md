---
status: "accepted"
date: 2026-09-24
decision-makers: Sakariyau Oseni (maintainer)
---

# Check certificates daily with EventBridge Scheduler, Lambda and SNS

> In the context of CertWatch, facing a phase 3 requirement to check every registered domain once a day and email a warning when a certificate is inside its alert window, at near-zero cost, we decided for EventBridge Scheduler and neglected EventBridge rule, Step Functions fan-out, to achieve alerting, cost, operability, accepting that a single run must finish inside Lambda's 15-minute limit; fan out with Step Functions if it grows.

## Context and Problem Statement

A phase 3 requirement to check every registered domain once a day and email a warning when a certificate is inside its alert window, at near-zero cost.

## Decision Drivers

* Alerting
* Cost
* Operability

## Considered Options

* EventBridge Scheduler
* EventBridge rule
* Step Functions fan-out

## Decision Outcome

Chosen option: "EventBridge Scheduler", because it best meets the decision drivers (alerting, cost, operability).

We will run a checker Lambda once a day from EventBridge Scheduler. It scans the domains table, opens a TLS connection to each domain with a short timeout, records the expiry date, and publishes certificates inside their alert window to an SNS topic that emails subscribers.

### Consequences

* Good, because alerts arrive without anyone checking a dashboard
* Good, because each result is stored for the next run
* Bad, because subscribers must confirm the SNS email subscription
* Bad, because a failed day waits for the next run

### Confirmation

An integration test registers a host with an expired certificate and asserts an SNS publish; a CloudWatch alarm fires if the checker errors or runs past 80% of its timeout.

## Pros and Cons of the Options

### EventBridge Scheduler

Daily schedule, one checker Lambda, SNS email

* Good, because retries and a dead-letter queue per schedule
* Good, because within the free tier
* Good, because few moving parts
* Bad, because one run is capped at 15 minutes
* Bad, because email only, to confirmed subscribers

### EventBridge rule

A cron rule on the default bus

* Good, because same result for a single daily trigger
* Good, because retries and dead-letter queue per target
* Bad, because cron in UTC only
* Bad, because AWS recommends Scheduler for new schedules

### Step Functions fan-out

A Map state checks each domain

* Good, because scales to any number of domains
* Good, because per-domain retries
* Bad, because more cost and moving parts than needed now

## More Information

Confidence: High.
Review by: End of phase 3, or when one run passes 5 minutes.
Trade-offs accepted: a single run must finish inside Lambda's 15-minute limit; fan out with Step Functions if it grows.
Components: Amazon EventBridge Scheduler, AWS Lambda, Amazon SNS.
Requirements addressed: REQ-01, REQ-05, REQ-06.
Part of the CertWatch architecture decision record.

### Review, 2026-10-04 (end of phase 3)

The decision stands; phase 3 shipped on it unchanged. Both confirmation criteria are met: an
integration test registers a host with an expired certificate and asserts the SNS publish
(`test_an_expired_certificate_is_read_and_reported`), and `CheckerDurationAlarm` fires at
720,000 ms against the function's 900 s timeout, which is the 80% the record asked for.
`CheckerErrorsAlarm` covers the failed-run case. The schedule carries two retries and a
dead-letter queue, as the option promised.

One clarification, recorded because the text above is narrower than what was built: the record
says certificates "inside their alert window" are published. The checker in fact alerts on every
result that is not `ok`, which also covers `check_failed`, `blocked`, `unresolvable`,
`unreachable` and `handshake_failed`. A domain that cannot be checked is worth the same email as
one about to expire, and a silent failure would defeat the service. Each run still sends at most
one digest. The statuses are documented in the README.

The alternative trigger, one run passing 5 minutes, has not occurred; the duration alarm is the
standing guard for it.
