"""Unit tests for the pairing decision tree (scripted client stub)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from custom_components.unired import auth
from custom_components.unired.auth import (
    Authenticated,
    Failed,
    NeedDevicePairing,
    NeedRegistration,
)
from custom_components.unired.exceptions import (
    UniredAuthError,
    UniredConnectionError,
    UniredDeviceError,
    UniredError,
    UniredNotFoundError,
)
from custom_components.unired.models import (
    Authorization,
    DeviceFingerprint,
    DeviceRegistration,
    TermsInfo,
    Tokens,
)

CL = ZoneInfo("America/Santiago")


def _tokens() -> Tokens:
    return Tokens(
        access_token="ACCESS",
        refresh_token="REFRESH",
        expires_at=datetime.now(CL) + timedelta(hours=1),
    )


class ScriptedClient:
    """Stub UniredClient serving scripted returns/raises per method."""

    def __init__(self, script: dict[str, list[Any]]) -> None:
        """Store per-method outcome queues."""
        self._script = {key: list(value) for key, value in script.items()}
        self.calls: list[tuple[str, tuple, dict]] = []

    def _next(self, name: str) -> Any:
        outcome = self._script[name].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def login(self, *args: Any, **kwargs: Any) -> Any:
        """Scripted login."""
        self.calls.append(("login", args, kwargs))
        return self._next("login")

    async def preregister(self, *args: Any, **kwargs: Any) -> Any:
        """Scripted preregister."""
        self.calls.append(("preregister", args, kwargs))
        return self._next("preregister")

    async def get_tyc(self) -> Any:
        """Scripted terms fetch."""
        self.calls.append(("get_tyc", (), {}))
        return self._next("get_tyc")

    async def activate_registration(self, *args: Any, **kwargs: Any) -> Any:
        """Scripted activation."""
        self.calls.append(("activate_registration", args, kwargs))
        return self._next("activate_registration")

    async def complete_registration(self, *args: Any, **kwargs: Any) -> Any:
        """Scripted completion."""
        self.calls.append(("complete_registration", args, kwargs))
        return self._next("complete_registration")

    async def register_device(self, *args: Any, **kwargs: Any) -> Any:
        """Scripted device pairing start."""
        self.calls.append(("register_device", args, kwargs))
        return self._next("register_device")

    async def authorize_device(self, *args: Any, **kwargs: Any) -> Any:
        """Scripted device OTP verify."""
        self.calls.append(("authorize_device", args, kwargs))
        return self._next("authorize_device")

    async def refresh(self, *args: Any, **kwargs: Any) -> Any:
        """Scripted token rotation."""
        self.calls.append(("refresh", args, kwargs))
        return self._next("refresh")


def _device() -> DeviceFingerprint:
    return DeviceFingerprint.generate()


def _reg() -> DeviceRegistration:
    return DeviceRegistration(
        device_uuid="dev-uuid", user_identifier="uid-1", cooldown="60"
    )


def _provider(codes: list[str]) -> tuple[list[str], Any]:
    seen: list[str] = []

    async def _provide(reason: str) -> str:
        seen.append(reason)
        return codes.pop(0)

    return seen, _provide


async def test_start_login_known_device_authenticates() -> None:
    """Tokens straight from login mean done, no OTP involved."""
    client = ScriptedClient({"login": [_tokens()]})
    result = await auth.start_login(client, "172143520", "u@e.cl", _device())  # type: ignore[arg-type]
    assert isinstance(result, Authenticated)
    assert result.tokens.access_token == "ACCESS"


async def test_start_login_unknown_user_starts_registration() -> None:
    """0603 issues preregister and reports the pending identifier."""
    client = ScriptedClient(
        {"login": [UniredNotFoundError("nope", "0603")], "preregister": ["uid-9"]}
    )
    result = await auth.start_login(client, "1", "u@e.cl", _device())  # type: ignore[arg-type]
    assert result == NeedRegistration("uid-9")


async def test_start_login_unknown_device_pairs_and_sends_code() -> None:
    """0630 issues POST device so NeedDevicePairing means 'OTP sent'."""
    client = ScriptedClient(
        {"login": [UniredDeviceError("dev?", "0630")], "register_device": [_reg()]}
    )
    result = await auth.start_login(client, "1", "u@e.cl", _device())  # type: ignore[arg-type]
    assert result == NeedDevicePairing("dev-uuid", "uid-1", "60")


async def test_start_login_other_error_fails() -> None:
    """Unexpected codes surface as Failed with the code preserved."""
    client = ScriptedClient({"login": [UniredError("ext", "0801")]})
    result = await auth.start_login(client, "1", "u@e.cl", _device())  # type: ignore[arg-type]
    assert result == Failed("0801", "ext")


async def test_submit_registration_otp_chains_into_pairing() -> None:
    """Activation + completion converge into a fresh device-pairing state."""
    client = ScriptedClient(
        {
            "activate_registration": [{"ok": True}],
            "complete_registration": [{"ok": True}],
            "register_device": [_reg()],
        }
    )
    result = await auth.submit_registration_otp(
        client,  # type: ignore[arg-type]
        user_identifier="uid-9",
        code="1111",
        device=_device(),
        email="u@e.cl",
        rut="1",
        name="Test User",
        uuid_tyc="tyc-uuid",
    )
    assert result == NeedDevicePairing("dev-uuid", "uid-1", "60")


async def test_submit_device_otp_bad_code_fails_once() -> None:
    """Wrong OTP is terminal; no retry loop, no guessing (SEC-002)."""
    seen, provider = _provider(["0000"])
    client = ScriptedClient(
        {
            "login": [UniredDeviceError("dev?", "0630")],
            "register_device": [_reg()],
            "authorize_device": [UniredAuthError("bad code", "0407")],
        }
    )
    result = await auth.ensure_tokens(
        client,  # type: ignore[arg-type]
        "1",
        "u@e.cl",
        _device(),
        provider,
        name="Test User",
    )
    assert seen == ["device"]  # exactly one attempt
    assert result == Failed("0407", "bad code")


async def test_ensure_tokens_existing_user_new_device() -> None:
    """Full existing-user path: 0630 → OTP(device) → tokens, one code."""
    seen, provider = _provider(["7998"])
    client = ScriptedClient(
        {
            "login": [UniredDeviceError("dev?", "0630")],
            "register_device": [_reg()],
            "authorize_device": [Authorization(_tokens(), "Test User")],
        }
    )
    result = await auth.ensure_tokens(
        client,  # type: ignore[arg-type]
        "1",
        "u@e.cl",
        _device(),
        provider,
        name="Test User",
    )
    assert seen == ["device"]
    assert isinstance(result, Authenticated)
    assert result.name == "Test User"


async def test_ensure_tokens_new_user_registration_path() -> None:
    """Full new-user path: 0603 → OTP(registration) → OTP(device) → tokens."""
    seen, provider = _provider(["1111", "2222"])
    client = ScriptedClient(
        {
            "login": [UniredNotFoundError("nope", "0603")],
            "preregister": ["uid-9"],
            "get_tyc": [TermsInfo(uuid="tyc-uuid", version="v")],
            "activate_registration": [{"ok": True}],
            "complete_registration": [{"ok": True}],
            "register_device": [_reg()],
            "authorize_device": [Authorization(_tokens(), "Test User")],
        }
    )
    result = await auth.ensure_tokens(
        client,  # type: ignore[arg-type]
        "1",
        "u@e.cl",
        _device(),
        provider,
        name="Test User",
    )
    assert seen == ["registration", "device"]
    assert isinstance(result, Authenticated)


async def test_ensure_tokens_transport_failure() -> None:
    """Connection loss aborts the tree as Failed without OTP prompts."""
    seen, provider = _provider(["1111"])
    client = ScriptedClient({"login": [UniredConnectionError("down")]})
    result = await auth.ensure_tokens(
        client,  # type: ignore[arg-type]
        "1",
        "u@e.cl",
        _device(),
        provider,
        name="Test User",
    )
    assert isinstance(result, Failed)
    assert seen == []


async def test_refresh_if_needed_skips_fresh_tokens() -> None:
    """Fresh triple passes through untouched, no client call."""
    client = ScriptedClient({})
    tokens = _tokens()
    assert await auth.refresh_if_needed(client, tokens) is tokens  # type: ignore[arg-type]
    assert client.calls == []


async def test_refresh_if_needed_rotates_and_persists() -> None:
    """Expired or forced rotation calls refresh once and sinks the result."""
    fresh = _tokens()
    expired = Tokens(
        access_token="OLD",
        refresh_token="OLD-R",
        expires_at=datetime.now(CL) - timedelta(hours=1),
    )
    client = ScriptedClient({"refresh": [fresh]})
    saved: list[Tokens] = []
    result = await auth.refresh_if_needed(
        client,  # type: ignore[arg-type]
        expired,
        on_refreshed=saved.append,
    )
    assert result is fresh
    assert saved == [fresh]
