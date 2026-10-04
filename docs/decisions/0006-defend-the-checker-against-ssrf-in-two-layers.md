---
status: "accepted"
date: 2026-09-24
decision-makers: Sakariyau Oseni (maintainer)
---

# Defend the checker against SSRF in two layers

> In the context of CertWatch, facing a checker that connects to hostnames anyone can register while the API is unauthenticated, we decided for validate, then guard at check time and neglected registration validation only, egress proxy or VPC firewall, to achieve security, integrity, accepting that hosts that resolve to private addresses are skipped and logged, never checked.

## Context and Problem Statement

A checker that connects to hostnames anyone can register while the API is unauthenticated. A name that resolves to an internal address would turn it into a probe of private networks.

## Decision Drivers

* Security
* Integrity

## Considered Options

* Validate, then guard at check time
* Registration validation only
* Egress proxy or VPC firewall

## Decision Outcome

Chosen option: "Validate, then guard at check time", because it best meets the decision drivers (security, integrity).

We will keep registration-time validation (public DNS names only) and add a check-time guard: the checker resolves each name, refuses to connect if any address is private, loopback, link-local, multicast or reserved, and connects to the vetted address with SNI set to the name.

### Consequences

* Good, because metadata and internal ranges are unreachable from the checker
* Good, because the guard is testable in unit tests
* Bad, because some legitimate internal-only domains cannot be monitored

### Confirmation

Unit tests prove names resolving to 127.0.0.1, 10.0.0.0/8, 169.254.169.254 and ::1 are refused, including a rebinding case; the 66 registration-validation tests keep passing.

## Pros and Cons of the Options

### Validate, then guard at check time

Two layers: registration and connection

* Good, because stops names that resolve inward later
* Good, because connecting to the vetted IP defeats DNS rebinding
* Bad, because split-horizon names cannot be monitored

### Registration validation only

Layer 1 alone (built today)

* Good, because nothing more to build
* Bad, because a public name can resolve to a private IP later

### Egress proxy or VPC firewall

Network controls on the checker's traffic

* Good, because enforced outside the code
* Bad, because NAT and firewall cost far above the budget

## More Information

Confidence: High.
Review by: End of phase 3.
Trade-offs accepted: hosts that resolve to private addresses are skipped and logged, never checked.
Components: AWS Lambda.
Requirements addressed: REQ-02.
Part of the CertWatch architecture decision record.
