"""Shared fixtures for the integration tests, which run only against LocalStack.

    make ls-up ls-deploy ls-test

Every fixture that reaches AWS checks first that the endpoint is LocalStack's, so a stray profile
or a forgotten environment variable cannot point these tests at a real account.
"""

import json
import os
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlparse

import boto3
import pytest

LOCALSTACK_HOSTS = {"localhost", "127.0.0.1", "localhost.localstack.cloud"}


@pytest.fixture(scope="session")
def localstack() -> str:
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "")
    if (urlparse(endpoint).hostname or "") not in LOCALSTACK_HOSTS:
        pytest.skip("AWS_ENDPOINT_URL does not point at LocalStack")
    return endpoint


def _from_stack(name: str) -> str:
    value = os.environ.get(name)
    if not value or value == "None":
        pytest.skip(f"{name} is not set; run `make ls-test`")
    return value


@pytest.fixture(scope="session")
def api_url() -> str:
    return _from_stack("CERTWATCH_API_URL").rstrip("/")


@pytest.fixture(scope="session")
def api(api_url):
    """Calls the deployed HTTP API: api("POST", "/domains", {...}) -> (status, body, headers)."""

    def call(method: str, path: str, body: object = None) -> tuple[int, dict | None, dict]:
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        request = urllib.request.Request(api_url + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status, raw, headers = response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            status, raw, headers = error.code, error.read(), dict(error.headers)
        return status, json.loads(raw) if raw else None, headers

    return call


@pytest.fixture(scope="session")
def table(localstack):
    """The domains table, read directly, so tests check what was stored and not the API's echo."""
    return boto3.resource("dynamodb").Table(_from_stack("CERTWATCH_TABLE_NAME"))


@pytest.fixture(scope="session")
def topic_arn(localstack) -> str:
    return _from_stack("CERTWATCH_TOPIC_ARN")


@pytest.fixture(scope="session")
def checker_name(localstack) -> str:
    return _from_stack("CERTWATCH_CHECKER_NAME")


@pytest.fixture
def domain_name(api):
    """A unique domain per test, removed afterwards even if the test fails."""
    name = f"it-{uuid.uuid4().hex[:10]}.example.com"
    yield name
    api("DELETE", f"/domains/{name}")


@pytest.fixture
def registered(api):
    """Registers domains and removes them afterwards: registered("host.example.com", alert_days=30)."""
    names = []

    def register(domain: str, **attributes) -> dict:
        status, body, _headers = api("POST", "/domains", {"domain": domain, **attributes})
        assert status == 201, f"could not register {domain}: {body}"
        names.append(domain)
        return body

    yield register
    for name in names:
        api("DELETE", f"/domains/{name}")
