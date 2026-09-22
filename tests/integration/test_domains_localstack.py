"""End-to-end tests against the stack deployed to LocalStack.

    make ls-up ls-deploy ls-test

Requests go through the real HTTP API, Lambda and DynamoDB emulated by LocalStack; the table is
also read directly, so the tests check what was stored rather than trusting the API's echo.
"""

import json
import os
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlparse

import boto3
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def api_url() -> str:
    url = os.environ.get("CERTWATCH_API_URL")
    if not url:
        pytest.skip("CERTWATCH_API_URL is not set; run `make ls-test`")
    return url.rstrip("/")


@pytest.fixture(scope="session")
def table():
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "")
    host = urlparse(endpoint).hostname or ""
    # never read a real AWS table by accident: these tests only run against LocalStack
    if host not in {"localhost", "127.0.0.1", "localhost.localstack.cloud"}:
        pytest.skip("AWS_ENDPOINT_URL does not point at LocalStack")
    return boto3.resource("dynamodb").Table(os.environ["CERTWATCH_TABLE_NAME"])


@pytest.fixture
def domain_name(api_url):
    """A unique domain per test, removed afterwards even if the test fails."""
    name = f"it-{uuid.uuid4().hex[:10]}.example.com"
    yield name
    request(api_url, "DELETE", f"/domains/{name}")


def request(api_url: str, method: str, path: str, body: object = None) -> tuple[int, dict | None, dict]:
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    req = urllib.request.Request(api_url + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status, raw, headers = resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as err:
        status, raw, headers = err.code, err.read(), dict(err.headers)
    return status, json.loads(raw) if raw else None, headers


def test_health(api_url):
    status, body, _ = request(api_url, "GET", "/health")

    assert status == 200
    assert body["status"] == "ok"


def test_domain_lifecycle(api_url, table, domain_name):
    status, created, headers = request(api_url, "POST", "/domains", {"domain": domain_name.upper()})
    assert status == 201
    assert created["domain"] == domain_name
    assert (created["port"], created["alert_days"]) == (443, 30)
    assert headers.get("Location", headers.get("location")) == f"/domains/{domain_name}"

    stored = table.get_item(Key={"domain": domain_name})["Item"]
    assert stored["port"] == 443
    assert stored["created_at"] == created["created_at"]

    status, fetched, _ = request(api_url, "GET", f"/domains/{domain_name}")
    assert status == 200
    assert fetched == created

    status, updated, _ = request(api_url, "PATCH", f"/domains/{domain_name}", {"alert_days": 14})
    assert status == 200
    assert updated["alert_days"] == 14
    assert updated["port"] == 443
    assert table.get_item(Key={"domain": domain_name})["Item"]["alert_days"] == 14

    status, _, _ = request(api_url, "DELETE", f"/domains/{domain_name}")
    assert status == 204
    assert "Item" not in table.get_item(Key={"domain": domain_name})

    assert request(api_url, "GET", f"/domains/{domain_name}")[0] == 404
    assert request(api_url, "DELETE", f"/domains/{domain_name}")[0] == 404


def test_registering_the_same_domain_twice_conflicts(api_url, domain_name):
    assert request(api_url, "POST", "/domains", {"domain": domain_name})[0] == 201

    status, body, _ = request(api_url, "POST", "/domains", {"domain": f"{domain_name}."})

    assert status == 409
    assert body["error"]["code"] == "already_exists"


@pytest.mark.parametrize(
    "body",
    [
        b"{not json",
        {"domain": "http://example.com"},
        {"domain": "169.254.169.254"},
        {"domain": "a.com", "x": 1},
    ],
)
def test_invalid_input_is_rejected_before_it_reaches_the_table(api_url, body):
    status, resp, _ = request(api_url, "POST", "/domains", body)

    assert status == 400
    assert resp["error"]["code"] == "validation_error"


def test_listing_pages_through_every_domain(api_url, table):
    names = sorted(f"it-{uuid.uuid4().hex[:10]}.example.com" for _ in range(3))
    try:
        for name in names:
            assert request(api_url, "POST", "/domains", {"domain": name})[0] == 201

        seen, token, pages = [], None, 0
        while True:
            path = "/domains?limit=2" + (f"&next_token={token}" if token else "")
            status, page, _ = request(api_url, "GET", path)
            assert status == 200
            assert len(page["items"]) <= 2
            seen += [item["domain"] for item in page["items"]]
            token, pages = page["next_token"], pages + 1
            if token is None or pages > 50:
                break

        assert set(names) <= set(seen)
        assert len(seen) == len(set(seen)), "a domain appeared on two pages"
    finally:
        for name in names:
            request(api_url, "DELETE", f"/domains/{name}")


def test_a_forged_page_token_is_rejected(api_url):
    status, body, _ = request(api_url, "GET", "/domains?next_token=not-a-real-token")

    assert status == 400
    assert body["error"]["code"] == "validation_error"
