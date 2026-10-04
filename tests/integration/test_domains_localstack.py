"""End-to-end tests against the stack deployed to LocalStack.

    make ls-up ls-deploy ls-test

Requests go through the real HTTP API, Lambda and DynamoDB emulated by LocalStack; the table is
also read directly, so the tests check what was stored rather than trusting the API's echo.
Fixtures (api, table, domain_name) live in conftest.py.
"""

import uuid

import pytest

pytestmark = pytest.mark.integration


def test_health(api):
    status, body, _ = api("GET", "/health")

    assert status == 200
    assert body["status"] == "ok"


def test_domain_lifecycle(api, table, domain_name):
    status, created, headers = api("POST", "/domains", {"domain": domain_name.upper()})
    assert status == 201
    assert created["domain"] == domain_name
    assert (created["port"], created["alert_days"]) == (443, 30)
    assert headers.get("Location", headers.get("location")) == f"/domains/{domain_name}"

    stored = table.get_item(Key={"domain": domain_name})["Item"]
    assert stored["port"] == 443
    assert stored["created_at"] == created["created_at"]

    status, fetched, _ = api("GET", f"/domains/{domain_name}")
    assert status == 200
    assert fetched == created

    status, updated, _ = api("PATCH", f"/domains/{domain_name}", {"alert_days": 14})
    assert status == 200
    assert updated["alert_days"] == 14
    assert updated["port"] == 443
    assert table.get_item(Key={"domain": domain_name})["Item"]["alert_days"] == 14

    status, _, _ = api("DELETE", f"/domains/{domain_name}")
    assert status == 204
    assert "Item" not in table.get_item(Key={"domain": domain_name})

    assert api("GET", f"/domains/{domain_name}")[0] == 404
    assert api("DELETE", f"/domains/{domain_name}")[0] == 404


def test_registering_the_same_domain_twice_conflicts(api, domain_name):
    assert api("POST", "/domains", {"domain": domain_name})[0] == 201

    status, body, _ = api("POST", "/domains", {"domain": f"{domain_name}."})

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
def test_invalid_input_is_rejected_before_it_reaches_the_table(api, body):
    status, resp, _ = api("POST", "/domains", body)

    assert status == 400
    assert resp["error"]["code"] == "validation_error"


def test_listing_pages_through_every_domain(api, table):
    names = sorted(f"it-{uuid.uuid4().hex[:10]}.example.com" for _ in range(3))
    try:
        for name in names:
            assert api("POST", "/domains", {"domain": name})[0] == 201

        seen, token, pages = [], None, 0
        while True:
            path = "/domains?limit=2" + (f"&next_token={token}" if token else "")
            status, page, _ = api("GET", path)
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
            api("DELETE", f"/domains/{name}")


def test_a_forged_page_token_is_rejected(api):
    status, body, _ = api("GET", "/domains?next_token=not-a-real-token")

    assert status == 400
    assert body["error"]["code"] == "validation_error"
