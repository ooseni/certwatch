"""The /domains handler against an in-memory store; DynamoDB itself is covered by the LocalStack tests."""

import json

import pytest

from certwatch.api import domains
from certwatch.store import (
    DomainExists,
    DomainNotFound,
    InvalidPageToken,
    decode_page_token,
    encode_page_token,
)


class FakeStore:
    def __init__(self):
        self.items: dict[str, dict] = {}

    def create(self, item):
        if item["domain"] in self.items:
            raise DomainExists(item["domain"])
        record = {
            **item,
            "created_at": "2026-09-22T00:00:00+00:00",
            "updated_at": "2026-09-22T00:00:00+00:00",
        }
        self.items[item["domain"]] = record
        return record

    def get(self, domain):
        return self.items.get(domain)

    def list(self, limit, page_token=None):
        names = sorted(self.items)
        start = names.index(decode_page_token(page_token)["domain"]) + 1 if page_token else 0
        page = names[start : start + limit]
        more = start + limit < len(names)
        return [self.items[n] for n in page], encode_page_token({"domain": page[-1]}) if more else None

    def update(self, domain, changes):
        if domain not in self.items:
            raise DomainNotFound(domain)
        self.items[domain] |= changes
        return self.items[domain]

    def delete(self, domain):
        if self.items.pop(domain, None) is None:
            raise DomainNotFound(domain)


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(domains, "_store", fake)
    return fake


def call(route, body=None, path=None, query=None):
    event = {"routeKey": route, "pathParameters": path, "queryStringParameters": query}
    if body is not None:
        event["body"] = body if isinstance(body, str) else json.dumps(body)
    resp = domains.handler(event, None)
    return resp["statusCode"], json.loads(resp["body"]) if resp.get("body") else None, resp.get("headers", {})


def test_create_returns_201_with_location_and_defaults(store):
    status, body, headers = call("POST /domains", {"domain": "Example.COM"})

    assert status == 201
    assert headers["Location"] == "/domains/example.com"
    assert body["domain"] == "example.com"
    assert body["port"] == 443
    assert body["alert_days"] == 30
    assert "example.com" in store.items


def test_create_duplicate_returns_409(store):
    call("POST /domains", {"domain": "example.com"})

    status, body, _ = call("POST /domains", {"domain": "EXAMPLE.com."})

    assert status == 409
    assert body["error"]["code"] == "already_exists"


@pytest.mark.parametrize(
    "body",
    ["{not json", [], {"domain": "http://example.com"}, {"domain": "10.0.0.1"}, {"domain": "a.com", "x": 1}],
)
def test_create_rejects_invalid_input_with_400(store, body):
    status, resp, _ = call("POST /domains", body)

    assert status == 400
    assert resp["error"]["code"] == "validation_error"
    assert store.items == {}


def test_create_without_body_returns_400(store):
    status, _, _ = call("POST /domains")
    assert status == 400


def test_get_normalises_the_path_parameter(store):
    call("POST /domains", {"domain": "example.com"})

    status, body, _ = call("GET /domains/{domain}", path={"domain": "Example.com"})

    assert status == 200
    assert body["domain"] == "example.com"


def test_get_unknown_domain_returns_404(store):
    status, body, _ = call("GET /domains/{domain}", path={"domain": "missing.example.com"})

    assert status == 404
    assert body["error"]["code"] == "not_found"


def test_list_pages_through_every_domain(store):
    for name in ("a.example.com", "b.example.com", "c.example.com"):
        call("POST /domains", {"domain": name})

    status, first, _ = call("GET /domains", query={"limit": "2"})
    _, second, _ = call("GET /domains", query={"limit": "2", "next_token": first["next_token"]})

    assert status == 200
    assert [i["domain"] for i in first["items"]] == ["a.example.com", "b.example.com"]
    assert [i["domain"] for i in second["items"]] == ["c.example.com"]
    assert second["next_token"] is None


def test_list_of_an_empty_table(store):
    status, body, _ = call("GET /domains")

    assert status == 200
    assert body == {"items": [], "next_token": None}


@pytest.mark.parametrize(
    "query", [{"limit": "0"}, {"limit": "500"}, {"limit": "many"}, {"next_token": "!!!"}]
)
def test_list_rejects_bad_query_parameters(store, query):
    status, body, _ = call("GET /domains", query=query)

    assert status == 400
    assert body["error"]["code"] == "validation_error"


def test_update_changes_only_the_sent_fields(store):
    call("POST /domains", {"domain": "example.com", "port": 8443})

    status, body, _ = call("PATCH /domains/{domain}", {"alert_days": 7}, path={"domain": "example.com"})

    assert status == 200
    assert body["alert_days"] == 7
    assert body["port"] == 8443


@pytest.mark.parametrize("body", [{}, {"domain": "other.example.com"}, {"port": 0}])
def test_update_rejects_invalid_changes(store, body):
    call("POST /domains", {"domain": "example.com"})

    status, _, _ = call("PATCH /domains/{domain}", body, path={"domain": "example.com"})

    assert status == 400


def test_update_unknown_domain_returns_404(store):
    status, _, _ = call("PATCH /domains/{domain}", {"alert_days": 7}, path={"domain": "missing.example.com"})
    assert status == 404


def test_delete_returns_204_then_404(store):
    call("POST /domains", {"domain": "example.com"})

    first = domains.handler(
        {"routeKey": "DELETE /domains/{domain}", "pathParameters": {"domain": "example.com"}}, None
    )
    second, _, _ = call("DELETE /domains/{domain}", path={"domain": "example.com"})

    assert first == {"statusCode": 204}
    assert second == 404


def test_unknown_route_returns_404(store):
    status, body, _ = call("PUT /domains")

    assert status == 404
    assert body["error"]["code"] == "not_found"


def test_unexpected_errors_return_500_without_details(store, monkeypatch, caplog):
    def explode(*_args, **_kwargs):
        raise RuntimeError("table on fire")

    monkeypatch.setattr(store, "get", explode)

    status, body, _ = call("GET /domains/{domain}", path={"domain": "example.com"})

    assert status == 500
    assert body == {"error": {"code": "internal_error", "message": "something went wrong"}}
    assert "table on fire" in caplog.text


def test_invalid_page_token_from_store_maps_to_400(store, monkeypatch):
    def bad_token(*_args, **_kwargs):
        raise InvalidPageToken("x")

    monkeypatch.setattr(store, "list", bad_token)

    status, _, _ = call("GET /domains", query={"next_token": "x"})

    assert status == 400
