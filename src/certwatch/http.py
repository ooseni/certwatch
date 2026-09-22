"""Helpers for building API Gateway (HTTP API, payload v2) responses."""

import json
from typing import Any


def json_response(status: int, body: Any, headers: dict | None = None) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", **(headers or {})},
        "body": json.dumps(body),
    }


def error_response(status: int, code: str, message: str) -> dict:
    """Every error has the same shape: {"error": {"code": "...", "message": "..."}}."""
    return json_response(status, {"error": {"code": code, "message": message}})


def no_content() -> dict:
    return {"statusCode": 204}
