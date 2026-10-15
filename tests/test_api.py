"""Unit tests for the Unired async client (canned aiohttp session)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp import ClientConnectionError

from custom_components.unired.api import UniredClient
from custom_components.unired.exceptions import (
    UniredAuthError,
    UniredConnectionError,
    UniredDeviceError,
    UniredError,
    UniredNotFoundError,
    UniredRateLimitError,
)
from custom_components.unired.models import DeviceFingerprint

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    """Load a redacted live fixture payload."""
    return json.loads((FIXTURES / name).read_text())


class _FakeResponse:
    """Minimal async context manager mimicking an aiohttp response."""

    def __init__(self, status: int, payload: Any) -> None:
        """Store the canned status and JSON payload."""
        self.status = status
        self._payload = payload

    async def __aenter__(self) -> _FakeResponse:
        """Enter the response context."""
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        """Exit the response context without suppressing errors."""
        return False

    async def json(self) -> Any:
        """Return the canned JSON payload."""
        return self._payload


class _FakeSession:
    """Canned session serving scripted (status, payload) outcomes in order."""

    def __init__(self, script: list[tuple[int, Any] | Exception]) -> None:
        """Store the response script; every request consumes one entry."""
        self._script = list(script)
        self.calls: list[tuple[str, str, Any, dict[str, str]]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> _FakeResponse:
        """Record the call and serve the next scripted outcome."""
        self.calls.append((method, url, json, dict(headers or {})))
        outcome = self._script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        status, payload = outcome
        return _FakeResponse(status, payload)


def _client(*script: tuple[int, Any] | Exception) -> tuple[UniredClient, _FakeSession]:
    session = _FakeSession(list(script))
    return UniredClient(session), session  # type: ignore[arg-type]


def _device() -> DeviceFingerprint:
    return DeviceFingerprint.generate()


async def test_preregister_returns_uid_and_normalizes_rut() -> None:
    """RUT separators are stripped exactly like the app does."""
    client, session = _client(
        (
            201,
            {"result": "SUCCESS", "code": "0000", "data": {"userIdentifier": "uid-1"}},
        )
    )
    uid = await client.preregister("17.214.352-0", "  user@example.cl ")
    assert uid == "uid-1"
    method, url, body, _ = session.calls[0]
    assert method == "POST"
    assert url.endswith("registration")
    assert body == {"rut": "172143520", "email": "user@example.cl"}


async def test_login_success_returns_tokens() -> None:
    """Known device login yields the parsed token triple."""
    client, _ = _client((200, load("tokens.json")))
    tokens = await client.login("172143520", "user@example.cl", _device())
    assert tokens.access_token.startswith("RkFLRV9BQ0NFU1Nf")
    assert tokens.refresh_token.startswith("RkFLRV9SRUZSRVNI")
    assert tokens.expires_at is not None
    assert not tokens.is_expired()


async def test_login_unknown_user_raises_not_found() -> None:
    """0603 maps to UniredNotFoundError with the code preserved."""
    client, _ = _client((404, load("error_0603.json")))
    with pytest.raises(UniredNotFoundError) as excinfo:
        await client.login("000000000", "nobody@example.cl", _device())
    assert excinfo.value.code == "0603"


async def test_login_unknown_device_raises_device_error() -> None:
    """0630 maps to UniredDeviceError."""
    client, _ = _client((400, load("error_0630.json")))
    with pytest.raises(UniredDeviceError) as excinfo:
        await client.login("172143520", "user@example.cl", _device())
    assert excinfo.value.code == "0630"


async def test_register_device_returns_identifiers() -> None:
    """POST device 201 yields deviceUuid/userIdentifier/cooldown."""
    client, _ = _client((201, load("device_register.json")))
    reg = await client.register_device("user@example.cl", "172143520", _device())
    assert reg.device_uuid.startswith("ddddddd4")
    assert reg.user_identifier.startswith("eeeeeee5")
    assert reg.cooldown == "60"


async def test_authorize_device_returns_tokens_and_name() -> None:
    """device/authorize 200 yields tokens plus the holder name."""
    client, _ = _client((200, load("tokens.json")))
    auth = await client.authorize_device(
        _device(), "user@example.cl", "172143520", "1234"
    )
    assert auth.name == "Test User"
    assert auth.tokens.access_token.startswith("RkFLRV9BQ0NFU1Nf")


async def test_refresh_rotates_triple_and_sends_old_tokens() -> None:
    """Refresh posts {} with both old tokens and returns the new triple."""
    from custom_components.unired.models import Tokens

    old = Tokens.from_dict(load("tokens.json")["data"])
    fresh = {
        "result": "SUCCESS",
        "code": "0000",
        "data": {
            "accessToken": "TkVX",
            "refreshToken": "TkVXLVJFRlJFU0g=",
            "expirationDate": "2026-10-17T00:00:00+00:00",
            "name": "Test User",
        },
    }
    client, session = _client((200, fresh))
    new = await client.refresh(old)
    assert new.access_token == "TkVX"
    assert new.access_token != old.access_token
    _, _, body, headers = session.calls[0]
    assert body == {}
    assert headers["access_token"] == old.access_token
    assert headers["refresh_token"] == old.refresh_token


async def test_auth_requests_carry_access_token() -> None:
    """Protected GETs send the access_token header."""
    client, session = _client((200, load("accounts.json")))
    await client.get_accounts("ACCESS-123")
    _, _, _, headers = session.calls[0]
    assert headers["access_token"] == "ACCESS-123"


async def test_get_accounts_parses_three_utilities() -> None:
    """Account list maps uuid/nickname/identifier/company."""
    client, _ = _client((200, load("accounts.json")))
    accounts = await client.get_accounts("ACCESS-123")
    assert [a.company_name for a in accounts] == [
        "Mundo Pacífico",
        "Essbio",
        "CGE S.A.",
    ]
    assert all(a.uuid and a.identifier and a.nickname for a in accounts)


async def test_get_instruments_binds_account() -> None:
    """Instrument carries its own uuid plus the parent account context."""
    client, _ = _client((200, load("instruments_luz.json")))
    instruments = await client.get_instruments("ACCESS-123", "account-uuid")
    assert len(instruments) == 1
    inst = instruments[0]
    assert inst.account_uuid == "account-uuid"
    assert inst.account_identifier == "8899001"
    assert inst.name == "CGE S.A."


async def test_get_debt_accepts_201_and_sums_owed() -> None:
    """Debt endpoint answers 201; only amount > 0 counts as owed."""
    client, _ = _client((201, load("debt_owed.json")))
    summary = await client.get_debt("ACCESS-123", "a-uuid", "i-uuid")
    assert summary.owed_total == 10600
    assert summary.has_debt
    assert len(summary.bills) == 1
    bill = summary.bills[0]
    assert bill.contract == "001122334455"
    assert bill.due_date is None  # FECVEN "" means unknown
    assert bill.debt_type == "Deuda Total"


async def test_get_debt_empty_and_zero_mean_nothing_owed() -> None:
    """Empty billList and all-zero bills both report no debt."""
    client, _ = _client((201, load("debt_empty.json")), (201, load("debt_zero.json")))
    empty = await client.get_debt("ACCESS-123", "a", "i")
    assert empty.owed_total == 0
    assert empty.bills == ()
    assert not empty.has_debt
    zero = await client.get_debt("ACCESS-123", "a", "i")
    assert zero.owed_total == 0
    assert len(zero.bills) == 1
    assert not zero.has_debt


async def test_error_code_mapping() -> None:
    """0700/0509 become UniredAuthError; 429 rate-limit; others generic."""
    client, _ = _client(
        (401, load("error_0700.json")),
        (400, load("error_0509.json")),
        (429, {"result": "ERROR"}),
        (500, {"result": "ERROR", "message": "boom"}),
    )
    with pytest.raises(UniredAuthError) as e1:
        await client.get_accounts("ACCESS-123")
    assert e1.value.code == "0700"
    with pytest.raises(UniredAuthError) as e2:
        await client.get_accounts("ACCESS-123")
    assert e2.value.code == "0509"
    with pytest.raises(UniredRateLimitError):
        await client.get_accounts("ACCESS-123")
    with pytest.raises(UniredError):
        await client.get_accounts("ACCESS-123")


async def test_connection_error_wraps_transport() -> None:
    """Transport failures surface as UniredConnectionError."""
    client, _ = _client(ClientConnectionError("down"))
    with pytest.raises(UniredConnectionError):
        await client.get_accounts("ACCESS-123")


async def test_get_tyc_returns_uuid() -> None:
    """publicInfo/tyc yields the uuidTyc used to complete registration."""
    client, _ = _client((200, load("tyc.json")))
    terms = await client.get_tyc()
    assert terms.uuid == "12345678-1234-1234-1234-1234567890ab"


async def test_activation_and_complete_return_data() -> None:
    """Registration steps pass through until live shapes lock (TASK-011)."""
    payload = {"result": "SUCCESS", "code": "0000", "data": {"ok": True}}
    client, session = _client((200, payload), (200, payload))
    assert await client.activate_registration("uid", "1234", _device()) == {"ok": True}
    assert await client.complete_registration("uid", "Test User", "tyc-uuid") == {
        "ok": True
    }
    _, url, body, _ = session.calls[0]
    assert url.endswith("registration/uid/activation")
    assert body["codeVerification"] == "1234"
    assert "device" in body
    _, url2, body2, _ = session.calls[1]
    assert url2.endswith("registration/uid")
    assert body2 == {"name": "Test User", "uuidTyc": "tyc-uuid"}


async def test_logout_posts_without_error() -> None:
    """Logout is a bare POST with the access token."""
    from custom_components.unired.models import Tokens

    client, session = _client((200, {"result": "SUCCESS", "code": "0000", "data": {}}))
    await client.logout(Tokens.from_dict(load("tokens.json")["data"]))
    method, url, _, headers = session.calls[0]
    assert method == "POST"
    assert url.endswith("session/logout")
    assert headers["access_token"].startswith("RkFLRV9BQ0NFU1Nf")


async def test_inscription_items_flattens_companies() -> None:
    """Public item catalog flattens to pickable company rows with groups."""
    client, session = _client((200, load("inscription_items.json")))
    companies = await client.inscription_items()
    assert [c.company_name for c in companies] == ["Essbio", "CGE S.A."]
    assert all(c.group == "Pago Servicios / Agua Potable" for c in companies)
    assert companies[1].multiple_identifier
    assert not companies[0].multiple_identifier
    _, _, _, headers = session.calls[0]
    assert "access_token" not in headers  # works unauthenticated


async def test_lookup_instrument_accepts_list_or_dict_shapes() -> None:
    """Lookup shape still unverified live; both plausible envelopes parse."""
    client, _ = _client(
        (200, {"result": "SUCCESS", "code": "0000", "data": [{"uuid": "x"}]}),
        (
            200,
            {
                "result": "SUCCESS",
                "code": "0000",
                "data": {"instrumentList": [{"uuid": "y"}]},
            },
        ),
    )
    assert await client.lookup_instrument("600", access_token="ACCESS-123") == [
        {"uuid": "x"}
    ]
    assert await client.lookup_instrument("600", access_token="ACCESS-123") == [
        {"uuid": "y"}
    ]


async def test_link_and_delete_pass_bodies_through() -> None:
    """Link/unlink request shapes lock in TASK-020; passthrough asserted."""
    ok = {"result": "SUCCESS", "code": "0000", "data": {"ok": True}}
    client, session = _client((200, ok), (200, ok))
    assert await client.link_account(
        "ACCESS-123", nickname="Casa", identifier="17.214.352-0", company_uuid="c-uuid"
    ) == {"ok": True}
    assert await client.delete_accounts("ACCESS-123", ["a-uuid"]) == {"ok": True}
    _, link_url, link_body, _ = session.calls[0]
    assert link_url.endswith("inscription/account")
    assert link_body == {
        "nickname": "Casa",
        "identifier": "172143520",
        "companyUuid": "c-uuid",
    }
    _, del_url, del_body, _ = session.calls[1]
    assert del_url.endswith("account/delete")
    assert del_body == {"accounts": [{"accountUuid": "a-uuid"}]}
