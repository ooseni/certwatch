"""DynamoDB access for the domains table."""

import base64
import binascii
import json
import os
from datetime import UTC, datetime
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError


class DomainExists(Exception):
    """The domain is already registered."""


class DomainNotFound(Exception):
    """The domain is not registered."""


class InvalidPageToken(ValueError):
    """A next_token that this API did not issue, or that has been tampered with."""


class DomainStore:
    """Items are keyed by the normalised domain name; see certwatch.validation."""

    def __init__(self, table):
        self._table = table

    @classmethod
    def from_env(cls) -> DomainStore:
        # boto3 honours AWS_ENDPOINT_URL, which LocalStack sets inside its Lambda containers
        return cls(boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]))

    def create(self, item: dict) -> dict:
        now = _now()
        record = {**item, "created_at": now, "updated_at": now}
        try:
            self._table.put_item(
                Item=record,
                ConditionExpression="attribute_not_exists(#d)",
                ExpressionAttributeNames={"#d": "domain"},
            )
        except ClientError as exc:
            if _is_condition_failure(exc):
                raise DomainExists(item["domain"]) from exc
            raise
        return record

    def get(self, domain: str) -> dict | None:
        item = self._table.get_item(Key={"domain": domain}).get("Item")
        return _plain(item) if item else None

    def list(self, limit: int, page_token: str | None = None) -> tuple[list[dict], str | None]:
        """One page of domains, unordered (a table scan), and the token for the next page."""
        kwargs = {"Limit": limit}
        if page_token:
            kwargs["ExclusiveStartKey"] = decode_page_token(page_token)
        resp = self._table.scan(**kwargs)
        items = [_plain(item) for item in resp.get("Items", [])]
        last = resp.get("LastEvaluatedKey")
        return items, encode_page_token(last) if last else None

    def update(self, domain: str, changes: dict) -> dict:
        # field names come from certwatch.validation.parse_changes, never from the client directly
        names = {"#d": "domain", "#updated_at": "updated_at"} | {f"#{k}": k for k in changes}
        values = {":updated_at": _now()} | {f":{k}": v for k, v in changes.items()}
        assignments = ", ".join(f"#{k} = :{k}" for k in [*changes, "updated_at"])
        try:
            resp = self._table.update_item(
                Key={"domain": domain},
                UpdateExpression=f"SET {assignments}",
                ConditionExpression="attribute_exists(#d)",
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ReturnValues="ALL_NEW",
            )
        except ClientError as exc:
            if _is_condition_failure(exc):
                raise DomainNotFound(domain) from exc
            raise
        return _plain(resp["Attributes"])

    def delete(self, domain: str) -> None:
        try:
            self._table.delete_item(
                Key={"domain": domain},
                ConditionExpression="attribute_exists(#d)",
                ExpressionAttributeNames={"#d": "domain"},
            )
        except ClientError as exc:
            if _is_condition_failure(exc):
                raise DomainNotFound(domain) from exc
            raise


def encode_page_token(last_evaluated_key: dict) -> str:
    raw = json.dumps(last_evaluated_key, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_page_token(token: str) -> dict:
    try:
        key = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    except (binascii.Error, ValueError) as exc:
        raise InvalidPageToken(token) from exc
    # the table has a single string hash key, so a genuine token is exactly {"domain": "<name>"}
    if not isinstance(key, dict) or set(key) != {"domain"} or not isinstance(key["domain"], str):
        raise InvalidPageToken(token)
    return key


def _plain(item: dict) -> dict:
    """DynamoDB returns numbers as Decimal; the API speaks JSON."""

    def convert(value):
        if isinstance(value, Decimal):
            return int(value) if value == value.to_integral_value() else float(value)
        return value

    return {key: convert(value) for key, value in item.items()}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _is_condition_failure(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"
