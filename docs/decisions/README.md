# Architecture decision log

One record per decision, in the MADR format. Records are immutable once accepted: a changed decision gets a new record that supersedes the old one.

The same seven decisions, with the context, target architecture and risks, are also presented as a 19-slide deck: [`certwatch-adr-blueprint.pdf`](certwatch-adr-blueprint.pdf).

| ID | Decision | Status | Date |
|---|---|---|---|
| [ADR-0001](0001-define-the-infrastructure-with-aws-sam.md) | Define the infrastructure with AWS SAM | accepted | 2026-09-21 |
| [ADR-0002](0002-serve-the-api-through-an-api-gateway-http-api.md) | Serve the API through an API Gateway HTTP API | accepted | 2026-09-21 |
| [ADR-0003](0003-store-monitored-domains-in-dynamodb-on-demand.md) | Store monitored domains in DynamoDB on demand | accepted | 2026-09-22 |
| [ADR-0004](0004-test-the-deployed-stack-against-localstack.md) | Test the deployed stack against LocalStack | accepted | 2026-09-22 |
| [ADR-0005](0005-check-certificates-daily-with-eventbridge-scheduler-lambda-a.md) | Check certificates daily with EventBridge Scheduler, Lambda and SNS | proposed | 2026-09-24 |
| [ADR-0006](0006-defend-the-checker-against-ssrf-in-two-layers.md) | Defend the checker against SSRF in two layers | proposed | 2026-09-24 |
| [ADR-0007](0007-deploy-through-github-actions-with-oidc.md) | Deploy through GitHub Actions with OIDC | proposed | 2026-09-24 |
