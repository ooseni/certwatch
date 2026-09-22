import base64

import pytest

from certwatch.validation import (
    ValidationError,
    normalise_domain,
    parse_changes,
    parse_limit,
    parse_new_domain,
    read_json_body,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("example.com", "example.com"),
        ("  Example.COM.  ", "example.com"),
        ("sub.domain.example.co.uk", "sub.domain.example.co.uk"),
        ("münchen.de", "xn--mnchen-3ya.de"),
        ("xn--mnchen-3ya.de", "xn--mnchen-3ya.de"),
        ("a-b.example.org", "a-b.example.org"),
    ],
)
def test_normalise_domain_accepts_public_hostnames(raw, expected):
    assert normalise_domain(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        42,
        "",
        "   ",
        "https://example.com",
        "example.com/path",
        "example.com:443",
        "user@example.com",
        "exa mple.com",
        "1.2.3.4",
        "::1",
        "[::1]",
        "169.254.169.254",
        "localhost",
        "example",
        "host.local",
        "db.internal",
        "service.test",
        "-bad.example.com",
        "bad-.example.com",
        "exa_mple.com",
        "*.example.com",
        "a..example.com",
        "example.123",
        ("a" * 64) + ".com",
        ".".join(["abcdefghi"] * 26) + ".com",
    ],
)
def test_normalise_domain_rejects_everything_else(raw):
    with pytest.raises(ValidationError):
        normalise_domain(raw)


def test_parse_new_domain_fills_defaults():
    assert parse_new_domain({"domain": "Example.com"}) == {
        "domain": "example.com",
        "port": 443,
        "alert_days": 30,
    }


def test_parse_new_domain_keeps_explicit_values():
    assert parse_new_domain({"domain": "example.com", "port": 8443, "alert_days": 7}) == {
        "domain": "example.com",
        "port": 8443,
        "alert_days": 7,
    }


@pytest.mark.parametrize(
    "body",
    [
        [],
        "example.com",
        {},
        {"domain": "example.com", "owner": "me"},
        {"domain": "example.com", "port": 0},
        {"domain": "example.com", "port": 65536},
        {"domain": "example.com", "port": "443"},
        {"domain": "example.com", "port": True},
        {"domain": "example.com", "port": 443.0},
        {"domain": "example.com", "alert_days": 0},
        {"domain": "example.com", "alert_days": 366},
    ],
)
def test_parse_new_domain_rejects_bad_bodies(body):
    with pytest.raises(ValidationError):
        parse_new_domain(body)


def test_parse_changes_returns_only_sent_fields():
    assert parse_changes({"alert_days": 14}) == {"alert_days": 14}
    assert parse_changes({"port": 8443, "alert_days": 60}) == {"port": 8443, "alert_days": 60}


@pytest.mark.parametrize(
    "body",
    [{}, [], {"domain": "other.com"}, {"colour": "blue"}, {"port": -1}, {"alert_days": None}],
)
def test_parse_changes_rejects_bad_bodies(body):
    with pytest.raises(ValidationError):
        parse_changes(body)


@pytest.mark.parametrize(("raw", "expected"), [(None, 50), ("1", 1), ("100", 100)])
def test_parse_limit(raw, expected):
    assert parse_limit(raw, default=50, maximum=100) == expected


@pytest.mark.parametrize("raw", ["0", "101", "-1", "ten", "", "1.5"])
def test_parse_limit_rejects_out_of_range(raw):
    with pytest.raises(ValidationError):
        parse_limit(raw, default=50, maximum=100)


def test_read_json_body_decodes_plain_and_base64_bodies():
    assert read_json_body({"body": '{"a": 1}'}) == {"a": 1}
    encoded = base64.b64encode(b'{"a": 1}').decode()
    assert read_json_body({"body": encoded, "isBase64Encoded": True}) == {"a": 1}


@pytest.mark.parametrize(
    "event",
    [{}, {"body": ""}, {"body": "{not json"}, {"body": "%%%", "isBase64Encoded": True}],
)
def test_read_json_body_rejects_missing_or_malformed_bodies(event):
    with pytest.raises(ValidationError):
        read_json_body(event)
