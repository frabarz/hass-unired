"""Unit tests for the Unired config flow (mocked auth layer)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unired import auth
from custom_components.unired.api import UniredClient
from custom_components.unired.const import (
    CONF_DEVICE,
    CONF_EMAIL,
    CONF_NAME,
    CONF_RUT,
    CONF_TOKENS,
    DOMAIN,
)
from custom_components.unired.models import (
    DeviceFingerprint,
    DeviceRegistration,
    TermsInfo,
    Tokens,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

CL = ZoneInfo("America/Santiago")
USER_INPUT = {
    "rut": "17.214.352-0",
    "email": "User@Example.cl",
    "name": "Test User",
    "accept_terms": True,
}


def _tokens() -> Tokens:
    return Tokens(
        access_token="ACCESS",
        refresh_token="REFRESH",
        expires_at=datetime.now(CL) + timedelta(hours=1),
    )


def _tokens_data() -> dict[str, Any]:
    tokens = _tokens()
    assert tokens.expires_at is not None
    return {
        "accessToken": tokens.access_token,
        "refreshToken": tokens.refresh_token,
        "expirationDate": tokens.expires_at.isoformat(),
    }


async def _init(hass: HomeAssistant) -> dict[str, Any]:
    """Start a fresh user flow."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def _configure(hass: HomeAssistant, flow_id: str, data: dict) -> dict[str, Any]:
    """Submit a flow step."""
    return await hass.config_entries.flow.async_configure(flow_id, data)


def _patch(monkeypatch: pytest.MonkeyPatch, **fakes: Any) -> None:
    for target, fake in fakes.items():
        module, _, attr = target.rpartition(".")
        assert module == "auth"
        monkeypatch.setattr(f"custom_components.unired.config_flow.auth.{attr}", fake)


async def test_user_step_shows_form(hass: HomeAssistant) -> None:
    """First screen is the RUT/e-mail/name form."""
    result = await _init(hass)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_direct_login_creates_entry(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Known device: tokens straight from login create the entry."""

    async def fake_start_login(*args: Any, **kwargs: Any) -> auth.AuthResult:
        return auth.Authenticated(_tokens(), "Test User")

    _patch(monkeypatch, **{"auth.start_login": fake_start_login})
    result = await _init(hass)
    assert result["type"] == FlowResultType.FORM
    result = await _configure(hass, result["flow_id"], dict(USER_INPUT))
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test User"
    assert result["data"][CONF_RUT] == "172143520"
    assert result["data"][CONF_EMAIL] == "User@Example.cl"
    assert result["data"][CONF_TOKENS]["accessToken"] == "ACCESS"


async def test_device_pairing_flow(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0630 path: OTP screen appears, code verifies, entry stores ids."""

    async def fake_start_login(*args: Any, **kwargs: Any) -> auth.AuthResult:
        return auth.NeedDevicePairing("dev-uuid", "uid-1", "60")

    async def fake_submit_device_otp(*args: Any, **kwargs: Any) -> auth.AuthResult:
        return auth.Authenticated(_tokens(), "Test User")

    _patch(
        monkeypatch,
        **{
            "auth.start_login": fake_start_login,
            "auth.submit_device_otp": fake_submit_device_otp,
        },
    )
    result = await _init(hass)
    result = await _configure(hass, result["flow_id"], dict(USER_INPUT))
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "otp"
    result = await _configure(hass, result["flow_id"], {"code": "7998"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["device_uuid"] == "dev-uuid"
    assert result["data"]["user_identifier"] == "uid-1"


async def test_registration_flow_converges_into_pairing(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0603 path: registration OTP, then device OTP, then entry."""

    async def fake_start_login(*args: Any, **kwargs: Any) -> auth.AuthResult:
        return auth.NeedRegistration("uid-9")

    async def fake_reg_otp(*args: Any, **kwargs: Any) -> auth.AuthResult:
        return auth.NeedDevicePairing("dev-uuid", "uid-9", "60")

    async def fake_submit_device_otp(*args: Any, **kwargs: Any) -> auth.AuthResult:
        return auth.Authenticated(_tokens(), "Test User")

    async def fake_get_tyc(self: UniredClient) -> TermsInfo:
        return TermsInfo(uuid="tyc-uuid", version="v")

    _patch(
        monkeypatch,
        **{
            "auth.start_login": fake_start_login,
            "auth.submit_registration_otp": fake_reg_otp,
            "auth.submit_device_otp": fake_submit_device_otp,
        },
    )
    monkeypatch.setattr(UniredClient, "get_tyc", fake_get_tyc)
    result = await _init(hass)
    result = await _configure(hass, result["flow_id"], dict(USER_INPUT))
    assert result["step_id"] == "otp"
    result = await _configure(hass, result["flow_id"], {"code": "1111"})
    assert result["step_id"] == "otp"  # now the device code screen
    result = await _configure(hass, result["flow_id"], {"code": "2222"})
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_bad_otp_shows_error_and_stays(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0407 surfaces as invalid_otp on the same OTP screen."""

    async def fake_start_login(*args: Any, **kwargs: Any) -> auth.AuthResult:
        return auth.NeedDevicePairing("dev-uuid", "uid-1", "60")

    async def fake_submit_device_otp(*args: Any, **kwargs: Any) -> auth.AuthResult:
        return auth.Failed("0407", "bad code")

    _patch(
        monkeypatch,
        **{
            "auth.start_login": fake_start_login,
            "auth.submit_device_otp": fake_submit_device_otp,
        },
    )
    result = await _init(hass)
    result = await _configure(hass, result["flow_id"], dict(USER_INPUT))
    result = await _configure(hass, result["flow_id"], {"code": "0000"})
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_otp"}


async def test_short_code_rejected_without_backend_call(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-4-digit codes never reach the server."""
    called = False

    async def fake_start_login(*args: Any, **kwargs: Any) -> auth.AuthResult:
        return auth.NeedDevicePairing("dev-uuid", "uid-1", "60")

    async def fake_submit_device_otp(*args: Any, **kwargs: Any) -> auth.AuthResult:
        nonlocal called
        called = True
        return auth.Authenticated(_tokens())

    _patch(
        monkeypatch,
        **{
            "auth.start_login": fake_start_login,
            "auth.submit_device_otp": fake_submit_device_otp,
        },
    )
    result = await _init(hass)
    result = await _configure(hass, result["flow_id"], dict(USER_INPUT))
    result = await _configure(hass, result["flow_id"], {"code": "12"})
    assert result["errors"] == {"base": "invalid_otp"}
    assert not called


async def test_terms_must_be_accepted(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unchecked terms block setup before any backend call."""

    async def fail_start_login(*args: Any, **kwargs: Any) -> auth.AuthResult:
        raise AssertionError("backend must not be contacted")

    _patch(monkeypatch, **{"auth.start_login": fail_start_login})
    result = await _init(hass)
    declined = dict(USER_INPUT, accept_terms=False)
    result = await _configure(hass, result["flow_id"], declined)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "terms_not_accepted"}


async def test_login_failure_shows_form_error(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backend outage on the user step reports cannot_connect."""

    async def fake_start_login(*args: Any, **kwargs: Any) -> auth.AuthResult:
        return auth.Failed(None, "down")

    _patch(monkeypatch, **{"auth.start_login": fake_start_login})
    result = await _init(hass)
    result = await _configure(hass, result["flow_id"], dict(USER_INPUT))
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_duplicate_account_aborts(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same normalized RUT+e-mail cannot create a second entry."""

    async def fake_start_login(*args: Any, **kwargs: Any) -> auth.AuthResult:
        return auth.Authenticated(_tokens(), "Test User")

    _patch(monkeypatch, **{"auth.start_login": fake_start_login})
    result = await _init(hass)
    result = await _configure(hass, result["flow_id"], dict(USER_INPUT))
    assert result["type"] == FlowResultType.CREATE_ENTRY
    result = await _init(hass)
    result = await _configure(hass, result["flow_id"], dict(USER_INPUT))
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


def _reauth_entry() -> MockConfigEntry:
    device = DeviceFingerprint.generate()
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="172143520:user@example.cl",
        title="Test User",
        data={
            CONF_RUT: "172143520",
            CONF_EMAIL: "user@example.cl",
            CONF_NAME: "Test User",
            CONF_DEVICE: device.to_dict(),
            CONF_TOKENS: _tokens_data(),
        },
    )


async def test_reauth_replaces_tokens(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reauth sends a fresh code, verifies it, updates the entry, aborts ok."""

    async def fake_register_device(*args: Any, **kwargs: Any) -> DeviceRegistration:
        return DeviceRegistration("dev-uuid", "uid-1", "60")

    async def fake_submit_device_otp(*args: Any, **kwargs: Any) -> auth.AuthResult:
        return auth.Authenticated(
            Tokens("ROTATED", "ROTATED-R", _tokens().expires_at), "Test User"
        )

    _patch(
        monkeypatch,
        **{"auth.submit_device_otp": fake_submit_device_otp},
    )
    monkeypatch.setattr(UniredClient, "register_device", fake_register_device)
    entry = _reauth_entry()
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
        },
        data=dict(entry.data),
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "otp"
    result = await _configure(hass, result["flow_id"], {"code": "7998"})
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKENS]["accessToken"] == "ROTATED"


async def test_reauth_send_failure_shows_retry(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the code cannot be sent, the reauth form reports the error."""
    from custom_components.unired.exceptions import UniredConnectionError

    async def fake_register_device(*args: Any, **kwargs: Any) -> DeviceRegistration:
        raise UniredConnectionError("down")

    monkeypatch.setattr(UniredClient, "register_device", fake_register_device)
    entry = _reauth_entry()
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
        },
        data=dict(entry.data),
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "cannot_connect"}
    result = await _configure(hass, result["flow_id"], {})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
