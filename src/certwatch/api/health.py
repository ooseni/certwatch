"""GET /health: liveness check."""

import os
from datetime import UTC, datetime

from certwatch.http import json_response


def handler(event, context):
    return json_response(
        200,
        {
            "status": "ok",
            "service": os.environ.get("SERVICE_NAME", "certwatch"),
            "stage": os.environ.get("STAGE", "local"),
            "time": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    )
