"""Pure parts of the store; the DynamoDB calls are exercised against LocalStack."""

import base64
from decimal import Decimal

import pytest

from certwatch.store import InvalidPageToken, _plain, decode_page_token, encode_page_token


def test_page_tokens_round_trip():
    key = {"domain": "example.com"}
    token = encode_page_token(key)

    assert "=" not in token
    assert decode_page_token(token) == key


@pytest.mark.parametrize(
    "token",
    [
        "!!!",
        "bm90IGpzb24",  # "not json"
        base64.urlsafe_b64encode(b'["domain"]').decode(),
        base64.urlsafe_b64encode(b'{"domain": 1}').decode(),
        base64.urlsafe_b64encode(b'{"domain": "a.com", "extra": "x"}').decode(),
    ],
)
def test_forged_or_corrupt_tokens_are_rejected(token):
    with pytest.raises(InvalidPageToken):
        decode_page_token(token)


def test_plain_turns_dynamodb_numbers_into_json_numbers():
    assert _plain({"port": Decimal("443"), "ratio": Decimal("0.5"), "domain": "a.com"}) == {
        "port": 443,
        "ratio": 0.5,
        "domain": "a.com",
    }
