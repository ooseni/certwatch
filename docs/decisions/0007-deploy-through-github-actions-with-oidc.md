---
status: "proposed"
date: 2026-09-24
decision-makers: Sakariyau Oseni (maintainer)
---

# Deploy through GitHub Actions with OIDC

> In the context of CertWatch, facing phase 5 automation of lint, tests and deployment, where stored AWS access keys in CI are a common way for a small project's account to be compromised, we decided for GitHub Actions + OIDC and neglected access keys in GitHub secrets, AWS CodePipeline, to achieve credentials, delivery speed, accepting that the deploy role's trust policy must pin the repository and branch exactly.

## Context and Problem Statement

Phase 5 automation of lint, tests and deployment, where stored AWS access keys in CI are a common way for a small project's account to be compromised.

## Decision Drivers

* Credentials
* Delivery speed

## Considered Options

* GitHub Actions + OIDC
* Access keys in GitHub secrets
* AWS CodePipeline

## Decision Outcome

Chosen option: "GitHub Actions + OIDC", because it best meets the decision drivers (credentials, delivery speed).

We will deploy from GitHub Actions by exchanging the workflow's OIDC token for a deploy role whose trust policy is pinned to the ooseni/certwatch repository; prod deploys only after a manual approval on the GitHub environment.

### Consequences

* Good, because no AWS keys exist to leak
* Good, because every deploy is traceable to a commit
* Bad, because the deploy role needs broad CloudFormation rights

### Confirmation

The IAM credential report shows no access keys; the trust policy's sub condition names repo:ooseni/certwatch; gitleaks keeps finding no secrets in history.

## Pros and Cons of the Options

### GitHub Actions + OIDC

Short-lived role credentials per run

* Good, because no stored AWS keys
* Good, because trust scoped to one repository and branch
* Bad, because a loose trust policy would let other repos deploy

### Access keys in GitHub secrets

An IAM user for CI

* Good, because simplest to set up
* Bad, because long-lived keys to leak and rotate

### AWS CodePipeline

AWS-native pipeline

* Good, because no external CI trust
* Bad, because cost and setup for a solo project

## More Information

Confidence: High.
Review by: End of phase 5.
Trade-offs accepted: the deploy role's trust policy must pin the repository and branch exactly.
Components: GitHub Actions, AWS IAM (OIDC provider), AWS CloudFormation.
Requirements addressed: REQ-03, REQ-04.
Part of the CertWatch architecture decision record.
