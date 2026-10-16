"""Redaction rules (unit)."""

import pytest

from app.redaction import REDACTED, Redactor


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "apiKey",
        "X-Api-Key",
        "client_secret",
        "access_token",
        "Authorization",
        "set-cookie",
        "sessionId",
        "private_key",
        "credentials",
    ],
)
def test_sensitive_keys_are_redacted(key: str) -> None:
    assert Redactor()({key: "value"}) == {key: REDACTED}


@pytest.mark.parametrize("key", ["passed", "total_tokens", "tokens", "sku", "order_id", "keyword"])
def test_ordinary_keys_are_kept(key: str) -> None:
    assert Redactor()({key: "value"}) == {key: "value"}


def test_secret_shaped_values_are_masked_anywhere() -> None:
    r = Redactor()
    out = r(["Bearer abcdefgh12345678", "AKIAABCDEFGHIJKLMNOP", "hf_" + "a" * 34, "a@b.co", "ok"])
    assert out == [
        "[REDACTED:bearer]",
        "[REDACTED:aws_key]",
        "[REDACTED:hf_token]",
        "[REDACTED:email]",
        "ok",
    ]
    assert r.count == 4


def test_nul_characters_never_reach_postgres() -> None:
    from app.redaction import Redactor

    assert Redactor()({"raw": "ab\x00cd"}) == {"raw": "ab�cd"}
