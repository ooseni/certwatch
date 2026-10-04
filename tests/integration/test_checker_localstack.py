"""The daily check, end to end on the stack deployed to LocalStack.

    make ls-up ls-deploy ls-test

The checker Lambda is invoked the way EventBridge Scheduler invokes it, and the alert is read back
from a temporary SQS queue subscribed to the real SNS topic -- so the IAM policy, the environment
variables, the topic and the write-back are all exercised, not just the Python.

Two tests need the Lambda container to reach the public internet, and are skipped when this host
cannot. The rest use `localhost.localstack.cloud`, a public DNS name that resolves to 127.0.0.1,
which is also the clearest possible test of the SSRF guard: a name anyone could register that
points straight back inside.
"""

import json
import socket
import time
import uuid

import boto3
import pytest

pytestmark = pytest.mark.integration

LOOPBACK_DOMAIN = "localhost.localstack.cloud"
EXPIRED_DOMAIN = "expired.badssl.com"
VALID_DOMAIN = "badssl.com"


@pytest.fixture(scope="session")
def internet():
    """Skips a test when this host cannot reach badssl.com, which those tests depend on."""
    try:
        with socket.create_connection((VALID_DOMAIN, 443), timeout=5):
            return True
    except OSError as exc:
        pytest.skip(f"no route to {VALID_DOMAIN}:443 ({exc}); skipping the tests that need it")


class AlertQueue:
    """Reads what the checker published to SNS."""

    def __init__(self, sqs, url):
        self._sqs = sqs
        self._url = url

    def drain(self):
        while self._sqs.receive_message(QueueUrl=self._url, MaxNumberOfMessages=10).get("Messages"):
            pass

    def next(self, timeout=60) -> tuple[str, str]:
        """The next alert as (subject, body). Fails the test if none arrives in time."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            messages = self._sqs.receive_message(
                QueueUrl=self._url, MaxNumberOfMessages=1, WaitTimeSeconds=5
            ).get("Messages", [])
            for message in messages:
                self._sqs.delete_message(QueueUrl=self._url, ReceiptHandle=message["ReceiptHandle"])
                envelope = json.loads(message["Body"])
                return envelope["Subject"], envelope["Message"]
        raise AssertionError(f"no alert was published within {timeout}s")

    def is_empty(self, settle=3) -> bool:
        time.sleep(settle)
        return not self._sqs.receive_message(QueueUrl=self._url, MaxNumberOfMessages=1).get("Messages")


@pytest.fixture
def alerts(topic_arn):
    """A temporary SQS queue subscribed to the alert topic, removed afterwards."""
    sqs, sns = boto3.client("sqs"), boto3.client("sns")
    url = sqs.create_queue(QueueName=f"certwatch-it-alerts-{uuid.uuid4().hex[:8]}")["QueueUrl"]
    arn = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    sqs.set_queue_attributes(
        QueueUrl=url,
        Attributes={
            "Policy": json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "sns.amazonaws.com"},
                            "Action": "sqs:SendMessage",
                            "Resource": arn,
                            "Condition": {"ArnEquals": {"aws:SourceArn": topic_arn}},
                        }
                    ],
                }
            )
        },
    )
    subscription = sns.subscribe(TopicArn=topic_arn, Protocol="sqs", Endpoint=arn)["SubscriptionArn"]
    yield AlertQueue(sqs, url)
    sns.unsubscribe(SubscriptionArn=subscription)
    sqs.delete_queue(QueueUrl=url)


@pytest.fixture
def run_check(checker_name):
    """Invokes the checker the way the schedule does, and returns its summary."""
    client = boto3.client("lambda")

    def run() -> dict:
        response = client.invoke(FunctionName=checker_name, Payload=b"{}")
        payload = json.loads(response["Payload"].read())
        assert "FunctionError" not in response, f"the checker failed: {payload}"
        assert response["StatusCode"] == 200
        return payload

    return run


def test_a_domain_that_resolves_inward_is_blocked_not_connected_to(registered, table, run_check, alerts):
    """The SSRF guard, end to end: a public name that resolves to 127.0.0.1 is never dialled."""
    registered(LOOPBACK_DOMAIN)
    alerts.drain()

    summary = run_check()

    assert summary["checked"] >= 1
    item = table.get_item(Key={"domain": LOOPBACK_DOMAIN})["Item"]
    assert item["last_status"] == "blocked"
    # the container may answer with either loopback address; both must be refused
    assert "loopback address" in item["last_error"]
    assert "127.0.0.1" in item["last_error"] or "::1" in item["last_error"]
    assert "expires_at" not in item, "a blocked domain was never read, so it has no expiry"

    subject, body = alerts.next()
    assert "need attention" in subject
    line = next(line for line in body.splitlines() if f"{LOOPBACK_DOMAIN}:443" in line)
    assert line.split()[0] == "BLOCKED"


def test_every_domain_gets_a_result_the_api_can_show(api, registered, run_check, alerts):
    registered(LOOPBACK_DOMAIN)
    other = f"it-{uuid.uuid4().hex[:10]}.{LOOPBACK_DOMAIN}"
    registered(other, port=8443)
    alerts.drain()

    summary = run_check()

    assert summary["checked"] >= 2
    assert summary["alerted"] >= 2
    assert summary["by_status"]["blocked"] >= 2
    for domain in (LOOPBACK_DOMAIN, other):
        status, item, _headers = api("GET", f"/domains/{domain}")
        assert status == 200
        assert item["last_status"] == "blocked"
        assert item["last_checked_at"].endswith("+00:00")


def test_one_run_publishes_exactly_one_digest(registered, run_check, alerts):
    registered(LOOPBACK_DOMAIN)
    alerts.drain()

    summary = run_check()

    subject, body = alerts.next()
    noun = "certificate" if summary["alerted"] == 1 else "certificates"
    assert subject == f"CertWatch dev: {summary['alerted']} {noun} need attention"
    assert alerts.is_empty(), "a run must send one digest, not one email per domain"
    reported = [line for line in body.splitlines() if line.startswith("  ") and LOOPBACK_DOMAIN in line]
    assert len(reported) == 1, f"the domain should appear on one line, not {len(reported)}"


def test_an_expired_certificate_is_read_and_reported(internet, registered, table, run_check, alerts):
    """A verifying handshake would fail here; the checker must still report the expiry date."""
    registered(EXPIRED_DOMAIN)
    alerts.drain()

    run_check()

    item = table.get_item(Key={"domain": EXPIRED_DOMAIN})["Item"]
    assert item["last_status"] == "expired"
    assert item["expires_at"] < item["last_checked_at"]
    assert item["days_remaining"] < 0
    assert "last_error" not in item

    _subject, body = alerts.next()
    assert "EXPIRED" in body
    assert f"{EXPIRED_DOMAIN}:443" in body


def test_a_valid_certificate_outside_its_window_is_recorded_but_not_alerted(
    internet, registered, table, run_check, alerts
):
    registered(VALID_DOMAIN, alert_days=1)
    alerts.drain()

    summary = run_check()

    item = table.get_item(Key={"domain": VALID_DOMAIN})["Item"]
    assert item["last_status"] == "ok"
    assert item["days_remaining"] > 1
    assert item["issuer"]
    assert summary["by_status"]["ok"] >= 1
    if summary["alerted"]:  # other domains in the table may still be alerting
        _subject, body = alerts.next()
        assert VALID_DOMAIN not in body
