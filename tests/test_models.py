"""Unit tests for Unired models (RUT, tokens, fingerprint, debt rule)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.unired.const import DEVICE_FIELDS, normalize_rut
from custom_components.unired.models import (
    DeviceFingerprint,
    Tokens,
    debt_summary_from_dict,
)


def test_normalize_rut_strips_separators() -> None:
    """App behavior: dots/dashes removed, check digit uppercased."""
    assert normalize_rut("17.214.352-0") == "172143520"
    assert normalize_rut("17214352-0") == "172143520"
    assert normalize_rut(" 12.345.678-k ") == "12345678K"


def test_tokens_expiry() -> None:
    """Missing expiry counts as expired; future/past compare correctly."""
    future = datetime.now(UTC) + timedelta(hours=1)
    past = datetime.now(UTC) - timedelta(hours=1)
    assert Tokens("a", "r", None).is_expired()
    assert not Tokens("a", "r", future).is_expired()
    assert Tokens("a", "r", past).is_expired()


def test_tokens_parse_naive_datetime_as_utc() -> None:
    """Naive expirationDate values are assumed UTC, never crash."""
    tokens = Tokens.from_dict(
        {
            "accessToken": "a",
            "refreshToken": "r",
            "expirationDate": "2026-10-16T01:11:12",
        }
    )
    assert tokens.expires_at is not None
    assert tokens.expires_at.tzinfo is not None


def test_fingerprint_generate_unique_and_roundtrips() -> None:
    """Generated fingerprints are unique and survive a dict round-trip."""
    first = DeviceFingerprint.generate()
    second = DeviceFingerprint.generate()
    assert first.unique_id != second.unique_id
    assert set(first.to_dict()) == set(DEVICE_FIELDS)
    assert DeviceFingerprint.from_dict(first.to_dict()) == first


def test_debt_summary_ignores_non_positive_amounts() -> None:
    """Owed total sums only amount > 0; junk amounts coerce to 0."""
    summary = debt_summary_from_dict(
        "i-uuid",
        {
            "allowsCredit": "S",
            "acceptZeroDebt": "N",
            "billList": [
                {"amount": 5000},
                {"amount": 0},
                {"amount": -3},
                {"amount": "bogus"},
                {},
            ],
            "presentationRule": [{"code": "AUTODE"}, {}],
        },
    )
    assert summary.owed_total == 5000
    assert summary.has_debt
    assert summary.allows_credit
    assert not summary.accept_zero_debt
    assert summary.presentation_rule == ("AUTODE",)
