"""Config flow: RUT + e-mail + name form, OTP verification, reauth.

The flow lets server codes decide the path (PAT-002): ``loginWithDevice``
success creates the entry, ``0603`` detours through registration,
``0630`` through device pairing. There is no resend button — the backend
resend endpoints are dead (findings.md §7), so restarting a step re-issues
the code and the UI says so.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import auth
from .api import UniredClient
from .const import (
    CONF_DEVICE,
    CONF_DEVICE_UUID,
    CONF_EMAIL,
    CONF_NAME,
    CONF_RUT,
    CONF_TOKENS,
    CONF_USER_ID,
    DOMAIN,
    normalize_rut,
)
from .exceptions import UniredError
from .models import DeviceFingerprint, Tokens

OTP_CODES = frozenset({"0407", "0408", "0500", "0604"})

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_RUT): str,
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_NAME): str,
        vol.Required("accept_terms", default=False): bool,
    }
)
STEP_OTP_SCHEMA = vol.Schema({vol.Required("code"): str})


def _tokens_data(tokens: Tokens) -> dict[str, Any]:
    return tokens.to_dict()


def _error_key(failed: auth.Failed) -> str:
    if failed.code in OTP_CODES:
        return "invalid_otp"
    if failed.code is None:
        return "cannot_connect"
    return "unknown"


class UniredConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle Unired user-driven pairing and reauthentication."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow (link/unlink services, poll interval)."""
        from .options_flow import UniredOptionsFlow

        return UniredOptionsFlow(config_entry)

    def __init__(self) -> None:
        """Initialize per-flow pairing state."""
        self._rut = ""
        self._email = ""
        self._name = ""
        self._device = DeviceFingerprint.generate()
        self._pending: auth.NeedRegistration | auth.NeedDevicePairing | None = None
        self._reauth_entry: ConfigEntry | None = None
        self._reauth_error: str | None = None

    def _client(self) -> UniredClient:
        return UniredClient(async_get_clientsession(self.hass))

    async def _unique(self) -> None:
        await self.async_set_unique_id(f"{self._rut}:{self._email.lower()}")
        self._abort_if_unique_id_configured()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect RUT + e-mail + name, then try login to branch the flow."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA)
        if not user_input.get("accept_terms", False):
            return self.async_show_form(
                step_id="user",
                data_schema=STEP_USER_SCHEMA,
                errors={"base": "terms_not_accepted"},
            )
        self._rut = normalize_rut(user_input[CONF_RUT])
        self._email = user_input[CONF_EMAIL].strip()
        self._name = user_input[CONF_NAME].strip()
        self._device = DeviceFingerprint.generate()
        await self._unique()
        result = await auth.start_login(
            self._client(), self._rut, self._email, self._device
        )
        if isinstance(result, auth.Authenticated):
            return await self._finish(result)
        if isinstance(result, (auth.NeedRegistration, auth.NeedDevicePairing)):
            self._pending = result
            return self.async_show_form(
                step_id="otp",
                data_schema=STEP_OTP_SCHEMA,
                description_placeholders={"email": self._email},
            )
        assert isinstance(result, auth.Failed)
        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors={"base": _error_key(result)},
        )

    async def async_step_otp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Verify the 4-digit e-mail code for the pending branch."""
        if self._pending is None:
            return self.async_abort(reason="unknown")
        if user_input is None:
            return self.async_show_form(
                step_id="otp",
                data_schema=STEP_OTP_SCHEMA,
                description_placeholders={"email": self._email},
            )
        code = user_input["code"].strip()
        if len(code) != 4:
            return self.async_show_form(
                step_id="otp",
                data_schema=STEP_OTP_SCHEMA,
                errors={"base": "invalid_otp"},
                description_placeholders={"email": self._email},
            )
        pending = self._pending
        if isinstance(pending, auth.NeedRegistration):
            try:
                terms = await self._client().get_tyc()
            except UniredError as err:
                return self.async_show_form(
                    step_id="otp",
                    data_schema=STEP_OTP_SCHEMA,
                    errors={"base": _error_key(auth.Failed(err.code, str(err)))},
                    description_placeholders={"email": self._email},
                )
            result = await auth.submit_registration_otp(
                self._client(),
                user_identifier=pending.user_identifier,
                code=code,
                device=self._device,
                email=self._email,
                rut=self._rut,
                name=self._name,
                uuid_tyc=terms.uuid,
            )
            if isinstance(result, auth.NeedDevicePairing):
                self._pending = result
                return self.async_show_form(
                    step_id="otp",
                    data_schema=STEP_OTP_SCHEMA,
                    description_placeholders={"email": self._email},
                )
        else:
            result = await auth.submit_device_otp(
                self._client(),
                device=self._device,
                email=self._email,
                rut=self._rut,
                otp=code,
            )
        if isinstance(result, auth.Authenticated):
            return await self._finish(result)
        assert isinstance(result, auth.Failed)
        return self.async_show_form(
            step_id="otp",
            data_schema=STEP_OTP_SCHEMA,
            errors={"base": _error_key(result)},
            description_placeholders={"email": self._email},
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-pair after 0509/0605: send a fresh device code, then verify it."""
        entry_id = self.context.get("entry_id")
        self._reauth_entry = (
            self.hass.config_entries.async_get_entry(entry_id) if entry_id else None
        )
        source = dict(entry_data or {})
        self._rut = str(source.get(CONF_RUT, ""))
        self._email = str(source.get(CONF_EMAIL, ""))
        self._name = str(source.get(CONF_NAME, ""))
        stored_device = source.get(CONF_DEVICE, {})
        self._device = (
            DeviceFingerprint.from_dict(stored_device)
            if stored_device
            else DeviceFingerprint.generate()
        )
        return await self._async_reauth_send()

    async def _async_reauth_send(self) -> ConfigFlowResult:
        """Send a fresh pairing code, or show the retry form on failure."""
        try:
            reg = await self._client().register_device(
                self._email, self._rut, self._device
            )
        except UniredError as err:
            self._reauth_error = _error_key(auth.Failed(err.code, str(err)))
            return await self.async_step_reauth_confirm()
        self._reauth_error = None
        self._pending = auth.NeedDevicePairing(
            reg.device_uuid, reg.user_identifier, reg.cooldown
        )
        return await self.async_step_otp()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Retry sending the pairing code after a failure."""
        if user_input is None:
            errors = {"base": self._reauth_error} if self._reauth_error else None
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({}),
                errors=errors,
            )
        return await self._async_reauth_send()

    async def _finish(self, result: auth.Authenticated) -> ConfigFlowResult:
        data = {
            CONF_RUT: self._rut,
            CONF_EMAIL: self._email,
            CONF_NAME: self._name or result.name,
            CONF_DEVICE: self._device.to_dict(),
            CONF_TOKENS: _tokens_data(result.tokens),
        }
        if isinstance(self._pending, auth.NeedDevicePairing):
            if self._pending.user_identifier:
                data[CONF_USER_ID] = self._pending.user_identifier
            if self._pending.device_uuid:
                data[CONF_DEVICE_UUID] = self._pending.device_uuid
        if self._reauth_entry is not None:
            self.hass.config_entries.async_update_entry(
                self._reauth_entry, data={**self._reauth_entry.data, **data}
            )
            return self.async_abort(reason="reauth_successful")
        await self._unique()
        return self.async_create_entry(title=self._name or self._email, data=data)
