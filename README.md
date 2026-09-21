# CertWatch

A serverless SSL/TLS certificate expiry monitor on AWS. Register the domains you care about; CertWatch checks their certificates every day and emails you before one expires.

Built with **AWS SAM**, **Python 3.14**, **API Gateway (HTTP API)**, **Lambda**, **DynamoDB**, **EventBridge Scheduler** and **SNS**, tested locally against **LocalStack** and deployed through **GitHub Actions**.

## Architecture (target)

```
Client ──► API Gateway (HTTP API) ──► Lambda ──► DynamoDB
                                                    ▲
EventBridge Scheduler (daily) ──► Checker Lambda ───┘
                                       └──► SNS ──► email alerts
```

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
