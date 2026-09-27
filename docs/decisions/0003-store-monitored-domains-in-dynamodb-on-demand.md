---
status: "accepted"
date: 2026-09-22
decision-makers: Sakariyau Oseni (maintainer)
---

# Store monitored domains in DynamoDB on demand

> In the context of CertWatch, facing one record per monitored domain, read by key from the API and read in full once a day by the checker, we decided for DynamoDB on demand and neglected Aurora Serverless v2, Amazon RDS, to achieve cost, operability, integrity, accepting that listing and the daily check Scan the whole table, which is fine at this size.

## Context and Problem Statement

One record per monitored domain, read by key from the API and read in full once a day by the checker. Hundreds to a few thousand domains (assumption), and idle most of the time.

## Decision Drivers

* Cost
* Operability
* Integrity

## Considered Options

* DynamoDB on demand
* Aurora Serverless v2
* Amazon RDS

## Decision Outcome

Chosen option: "DynamoDB on demand", because it best meets the decision drivers (cost, operability, integrity).

We will keep domains in a DynamoDB table in on-demand mode, keyed by the normalised domain name, with conditional writes for create, update and delete, and point-in-time recovery.

### Consequences

* Good, because duplicates are rejected atomically by a conditional write
* Good, because no servers, patching or connections
* Bad, because a Scan's cost grows with the table
* Bad, because reporting queries need an export

### Confirmation

LocalStack tests prove the conditional write (409) and Scan pagination; the template enables point-in-time recovery; review the Scan if the table passes 10,000 items.

## Pros and Cons of the Options

### DynamoDB on demand

Key-value table keyed by domain

* Good, because pay per request, near zero when idle
* Good, because conditional writes give 409 on duplicates
* Good, because point-in-time recovery
* Bad, because listing is a full Scan
* Bad, because no ad-hoc queries

### Aurora Serverless v2

PostgreSQL that can pause at zero capacity

* Good, because SQL and ad-hoc queries
* Bad, because Lambda needs VPC access or the Data API
* Bad, because resume delay after a pause

### Amazon RDS

Provisioned PostgreSQL instance

* Good, because familiar relational model
* Bad, because pays for an instance around the clock
* Bad, because patching and connection limits

## More Information

Confidence: High.
Review by: Past 10,000 domains, or if a query pattern appears.
Trade-offs accepted: listing and the daily check Scan the whole table, which is fine at this size.
Components: Amazon DynamoDB.
Requirements addressed: REQ-05, REQ-06.
Part of the CertWatch architecture decision record.
