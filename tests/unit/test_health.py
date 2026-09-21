import json
from datetime import datetime

from certwatch.api import health


def test_health_returns_ok(monkeypatch):
    monkeypatch.setenv("STAGE", "test")
    monkeypatch.setenv("SERVICE_NAME", "certwatch")

    resp = health.handler({}, None)

    assert resp["statusCode"] == 200
    assert resp["headers"]["Content-Type"] == "application/json"
    body = json.loads(resp["body"])
    assert body["status"] == "ok"
    assert body["service"] == "certwatch"
    assert body["stage"] == "test"
    assert datetime.fromisoformat(body["time"]).tzinfo is not None


def test_health_defaults_stage_to_local(monkeypatch):
    monkeypatch.delenv("STAGE", raising=False)

    body = json.loads(health.handler({}, None)["body"])

    assert body["stage"] == "local"
