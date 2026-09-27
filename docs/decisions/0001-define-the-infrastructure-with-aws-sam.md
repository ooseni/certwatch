---
status: "accepted"
date: 2026-09-21
decision-makers: Sakariyau Oseni (maintainer)
---

# Define the infrastructure with AWS SAM

> In the context of CertWatch, facing a small serverless system (HTTP API, Lambda, DynamoDB, EventBridge Scheduler, SNS) that must run locally, deploy as one stack per stage, and teach serverless infrastructure as code, we decided for AWS SAM and neglected Terraform, AWS CDK, to achieve delivery speed, local testing, learning goal, accepting that the infrastructure code is tied to AWS; stacks inherit CloudFormation's rollback and resource limits.

## Context and Problem Statement

A small serverless system (HTTP API, Lambda, DynamoDB, EventBridge Scheduler, SNS) that must run locally, deploy as one stack per stage, and teach serverless infrastructure as code. The next portfolio project uses Terraform, so this one exercises the AWS-native route.

## Decision Drivers

* Delivery speed
* Local testing
* Learning goal

## Considered Options

* AWS SAM
* Terraform
* AWS CDK

## Decision Outcome

Chosen option: "AWS SAM", because it best meets the decision drivers (delivery speed, local testing, learning goal).

We will define every resource in one SAM template (template.yaml), deployed as one CloudFormation stack per stage (certwatch-dev, certwatch-prod), with no console changes.

### Consequences

* Good, because one template drives local runs, LocalStack and AWS
* Good, because least-privilege policies sit next to each function
* Bad, because Terraform skills come from the next project, not this one
* Bad, because stack failures roll back slowly

### Confirmation

make lint validate runs cfn-lint and sam validate on every change; CloudFormation drift detection shows no out-of-band changes after phase 4.

## Pros and Cons of the Options

### AWS SAM

CloudFormation with serverless shorthand

* Good, because short definitions for functions, APIs and events
* Good, because sam local and LocalStack run the same template
* Good, because native to AWS, no state file
* Bad, because AWS only
* Bad, because CloudFormation limits and slow rollbacks

### Terraform

HashiCorp Terraform with the AWS provider

* Good, because multi-cloud skills
* Good, because plans show every change
* Bad, because state file to store and lock
* Bad, because more code for Lambda packaging

### AWS CDK

Infrastructure in Python

* Good, because real code and abstractions
* Good, because synthesises CloudFormation
* Bad, because another layer to debug
* Bad, because local emulation goes through SAM anyway

## More Information

Confidence: High.
Review by: Phase 7, or if CertWatch needs a non-AWS resource.
Trade-offs accepted: the infrastructure code is tied to AWS; stacks inherit CloudFormation's rollback and resource limits.
Components: AWS SAM, AWS CloudFormation.
Requirements addressed: REQ-04, REQ-05.
Part of the CertWatch architecture decision record.
