---
status: "accepted"
date: 2026-09-22
decision-makers: Sakariyau Oseni (maintainer)
---

# Test the deployed stack against LocalStack

> In the context of CertWatch, facing gaps that unit tests cannot close: the template, the IAM policies, API Gateway routing and real DynamoDB semantics, we decided for LocalStack and neglected moto only, a real AWS dev account, to achieve testability, credentials, cost, accepting that a paid LocalStack plan is needed once the trial ends, or integration tests move to AWS in CI.

## Context and Problem Statement

Gaps that unit tests cannot close: the template, the IAM policies, API Gateway routing and real DynamoDB semantics. Testing on AWS for every change costs money and needs credentials.

## Decision Drivers

* Testability
* Credentials
* Cost

## Considered Options

* LocalStack
* moto only
* A real AWS dev account

## Decision Outcome

Chosen option: "LocalStack", because it best meets the decision drivers (testability, credentials, cost).

We will deploy the real SAM template to LocalStack and run end-to-end tests there, with dummy credentials and an explicit endpoint, before any AWS deployment.

### Consequences

* Good, because 9 end-to-end tests pass against the real template
* Good, because dummy credentials cannot reach a real account
* Bad, because the trial ends around 22 October 2026
* Bad, because smoke tests on AWS are still needed (phase 4)

### Confirmation

make ls-up ls-deploy ls-test passes (9 of 9); phase 4 smoke tests on AWS dev match; the table fixture refuses to run unless AWS_ENDPOINT_URL is LocalStack.

## Pros and Cons of the Options

### LocalStack

The real template in Docker

* Good, because tests IAM, routing and DynamoDB semantics
* Good, because no AWS cost or credentials
* Good, because about 12 s per run
* Bad, because HTTP APIs need a paid plan (trial now)
* Bad, because emulation can differ from AWS

### moto only

Mocked AWS calls in unit tests

* Good, because free and fast
* Bad, because never deploys the template
* Bad, because no routing or IAM

### A real AWS dev account

Deploy and test on AWS

* Good, because real behaviour
* Bad, because needs credentials for every run
* Bad, because costs and slower feedback

## More Information

Confidence: Medium.
Review by: 22 October 2026, when the LocalStack trial ends.
Trade-offs accepted: a paid LocalStack plan is needed once the trial ends, or integration tests move to AWS in CI.
Components: LocalStack, AWS SAM CLI.
Requirements addressed: REQ-03, REQ-04.
Part of the CertWatch architecture decision record.
