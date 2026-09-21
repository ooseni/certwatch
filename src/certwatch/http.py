"""Helpers for building API Gateway (HTTP API, payload v2) responses."""

import json
from typing import Any


def json_response(status: int, body: Any) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
