# CertWatch

A serverless SSL/TLS certificate expiry monitor on AWS. Register the domains you care about; CertWatch checks their certificates every day and emails you before one expires.

Built with **AWS SAM**, **Python 3.14**, **API Gateway (HTTP API)**, **Lambda**, **DynamoDB**, **EventBridge Scheduler** and **SNS**, tested locally against **LocalStack** and deployed through **GitHub Actions**.

## Architecture (target)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/dark/certwatch-architecture.png">
  <img alt="CertWatch: HTTP API and Lambda over DynamoDB; a daily checker Lambda tests TLS and alerts via SNS" src="docs/diagrams/certwatch-architecture.drawio.svg">
</picture>

Requests flow through API Gateway to a Lambda function backed by a DynamoDB table (steps 1-3). Once a day
EventBridge Scheduler starts a checker function that reads the table, opens a TLS connection to every
domain and publishes expiring certificates to SNS, which emails the subscribers (steps 4-8). Everything runs
in one SAM stack per stage, with structured logs, X-Ray tracing and one least-privilege role per function.

Deployment (target, phase 5): GitHub Actions lints and tests, including against LocalStack, then deploys
with short-lived OIDC credentials instead of stored AWS keys:
[delivery pipeline diagram](docs/diagrams/certwatch-delivery-pipeline.drawio.svg).

The diagram source is [`docs/diagrams/certwatch.drawio`](docs/diagrams/certwatch.drawio); open it in
[draw.io](https://www.drawio.com) or the VS Code Draw.io Integration extension.

## Quick start

Requirements: Python 3.14, AWS SAM CLI, Docker.

```bash
make test      # unit tests
make lint      # ruff + cfn-lint
make local     # API on http://127.0.0.1:3000
curl http://127.0.0.1:3000/health
```

Run `make help` for every target.

## API

| Method | Path      | Description    |
|--------|-----------|----------------|
| GET    | `/health` | Liveness check |

## Roadmap

- [x] **Phase 1**: scaffold, `GET /health`, unit tests, linting
- [ ] **Phase 2**: domain CRUD API on DynamoDB, integration tests on LocalStack
- [ ] **Phase 3**: scheduled certificate checks and SNS email alerts
- [ ] **Phase 4**: deploy to AWS (`dev` stage), smoke tests
- [ ] **Phase 5**: CI/CD with GitHub Actions and OIDC (no stored AWS keys)
- [ ] **Phase 6**: auth, least-privilege IAM, tracing, alarms, security scanning
- [ ] **Phase 7**: docs, cost breakdown, design decisions
