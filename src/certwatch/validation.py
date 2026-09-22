"""Validate and normalise what API clients send."""

import base64
import binascii
import ipaddress
import json
import re

DEFAULT_PORT = 443
DEFAULT_ALERT_DAYS = 30
PORT_RANGE = (1, 65535)
ALERT_DAYS_RANGE = (1, 365)

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
# Special-use and private-network TLDs (RFC 2606, RFC 6761, RFC 8375 and common intranet names).
# Certificates there are not publicly verifiable, and the checker must never be pointed inward.
_RESERVED_TLDS = {
    "localhost",
    "local",
    "internal",
    "invalid",
    "test",
    "arpa",
    "lan",
    "home",
    "corp",
    "intranet",
}


class ValidationError(ValueError):
    """The request is well-formed but its content is not acceptable."""


def read_json_body(event: dict) -> object:
    """The decoded JSON body of an API Gateway (payload v2) event."""
    raw = event.get("body")
    if raw is None or raw == "":
        raise ValidationError("request body is required")
    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValidationError("request body is not valid UTF-8") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("request body is not valid JSON") from exc


def normalise_domain(value: object) -> str:
    """The canonical form of a hostname: lower case, IDNA (punycode), no trailing dot.

    Only public DNS names are accepted: no scheme, path, port, credentials, IP address,
    single-label or special-use name. The certificate checker connects to these hosts, so
    this is also the first defence against pointing it at internal addresses.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("domain must be a non-empty string")
    name = value.strip().rstrip(".").lower()
    if any(ch in name for ch in "/:@?#[] \\"):
        raise ValidationError(
            "domain must be a bare hostname such as example.com, without scheme, port or path"
        )
    try:
        ipaddress.ip_address(name)
    except ValueError:
        pass
    else:
        raise ValidationError("domain must be a DNS name, not an IP address")
    try:
        name = name.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValidationError("domain is not a valid internationalised name") from exc

    labels = name.split(".")
    if len(name) > 253 or len(labels) < 2 or not all(_LABEL.match(label) for label in labels):
        raise ValidationError("domain is not a valid hostname")
    if labels[-1].isdigit() or labels[-1] in _RESERVED_TLDS:
        raise ValidationError("domain must end in a public top-level domain")
    return name


def parse_new_domain(body: object) -> dict:
    """Validate a POST /domains body; fills in defaults."""
    body = _object(body)
    _reject_unknown(body, {"domain", "port", "alert_days"})
    return {
        "domain": normalise_domain(body.get("domain")),
        "port": _int_field(body, "port", DEFAULT_PORT, PORT_RANGE),
        "alert_days": _int_field(body, "alert_days", DEFAULT_ALERT_DAYS, ALERT_DAYS_RANGE),
    }


def parse_changes(body: object) -> dict:
    """Validate a PATCH /domains/{domain} body: only the fields present are changed."""
    body = _object(body)
    if "domain" in body:
        raise ValidationError("domain cannot be changed; delete it and register the new name")
    _reject_unknown(body, {"port", "alert_days"})
    if not body:
        raise ValidationError("nothing to update: send port and/or alert_days")
    changes = {}
    if "port" in body:
        changes["port"] = _int_field(body, "port", None, PORT_RANGE)
    if "alert_days" in body:
        changes["alert_days"] = _int_field(body, "alert_days", None, ALERT_DAYS_RANGE)
    return changes


def parse_limit(value: str | None, default: int, maximum: int) -> int:
    """The ?limit= query parameter of a list request."""
    if value is None:
        return default
    if not value.isdigit() or not 1 <= int(value) <= maximum:
        raise ValidationError(f"limit must be an integer from 1 to {maximum}")
    return int(value)


def _object(body: object) -> dict:
    if not isinstance(body, dict):
        raise ValidationError("request body must be a JSON object")
    return body


def _reject_unknown(body: dict, allowed: set[str]) -> None:
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise ValidationError(f"unknown field(s): {', '.join(unknown)}")


def _int_field(body: dict, name: str, default: int | None, bounds: tuple[int, int]) -> int | None:
    if name not in body:
        return default
    value = body[name]
    low, high = bounds
    # bool is a subclass of int in Python, and JSON true must not be read as 1
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValidationError(f"{name} must be an integer from {low} to {high}")
    return value
