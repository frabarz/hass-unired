"""Options flow: link/unlink utility services and tune polling.

Linking is server-side (``inscription/account``); unlinking too
(``account/delete``). After either mutation the entry reloads so sensors
follow the account list. The link identifier is RUT-like (dots/dashes
stripped, like the app); it defaults to the entry owner's RUT.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import auth
from .api import UniredClient
from .const import (
    CONF_COMPANY_UUID,
    CONF_IDENTIFIER,
    CONF_NICKNAME,
    CONF_RUT,
    CONF_SCAN_INTERVAL_S,
    CONF_TOKENS,
    DEFAULT_SCAN_INTERVAL_S,
    MAX_SCAN_INTERVAL_S,
    MIN_SCAN_INTERVAL_S,
)
from .models import Account, LinkableCompany, Tokens


class UniredOptionsFlow(OptionsFlow):
    """Handle options for a paired Unired user."""

    def __init__(self, entry: ConfigEntry) -> None:
        """Store the entry being configured."""
        self._entry = entry
        self._company_uuid = ""
        self._catalog: list[LinkableCompany] = []

    async def _authed_client(self) -> tuple[UniredClient, str]:
        client = UniredClient(async_get_clientsession(self.hass))
        tokens = Tokens.from_dict(self._entry.data[CONF_TOKENS])

        def _save(fresh: Tokens) -> None:
            self.hass.config_entries.async_update_entry(
                self._entry,
                data={**self._entry.data, CONF_TOKENS: fresh.to_dict()},
            )

        fresh = await auth.refresh_if_needed(client, tokens, on_refreshed=_save)
        return client, fresh.access_token

    async def _reload(self) -> None:
        self.hass.config_entries.async_schedule_reload(self._entry.entry_id)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "add_service",
                "add_service_manual",
                "remove_service",
                "settings",
            ],
        )

    async def async_step_add_service(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a company from the live catalog."""
        if user_input is not None:
            self._company_uuid = str(user_input[CONF_COMPANY_UUID])
            return await self.async_step_add_details()
        try:
            client = UniredClient(async_get_clientsession(self.hass))
            self._catalog = await client.inscription_items()
        except Exception:  # noqa: BLE001 - catalog is best effort; manual fallback
            return await self.async_step_add_service_manual()
        options = {
            company.company_uuid: f"{company.group} — {company.company_name}"
            for company in self._catalog
        }
        return self.async_show_form(
            step_id="add_service",
            data_schema=vol.Schema({vol.Required(CONF_COMPANY_UUID): vol.In(options)}),
        )

    async def async_step_add_service_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Enter a company UUID by hand (catalog unreachable or custom)."""
        if user_input is not None:
            company_uuid = str(user_input[CONF_COMPANY_UUID]).strip()
            if not company_uuid:
                return self.async_show_form(
                    step_id="add_service_manual",
                    data_schema=vol.Schema({vol.Required(CONF_COMPANY_UUID): str}),
                    errors={"base": "invalid_input"},
                )
            self._company_uuid = company_uuid
            return await self.async_step_add_details()
        return self.async_show_form(
            step_id="add_service_manual",
            data_schema=vol.Schema({vol.Required(CONF_COMPANY_UUID): str}),
        )

    async def async_step_add_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the service identifier + nickname, then link it."""
        if user_input is not None:
            identifier = str(user_input[CONF_IDENTIFIER]).strip()
            nickname = str(user_input[CONF_NICKNAME]).strip()
            if not identifier or not nickname:
                return self.async_show_form(
                    step_id="add_details",
                    data_schema=self._details_schema(),
                    errors={"base": "invalid_input"},
                )
            try:
                client, access_token = await self._authed_client()
                await client.link_account(
                    access_token,
                    nickname=nickname,
                    identifier=identifier,
                    company_uuid=self._company_uuid,
                )
            except Exception:  # noqa: BLE001 - surfaced below via form error
                return self.async_show_form(
                    step_id="add_details",
                    data_schema=self._details_schema(),
                    errors={"base": "unknown"},
                )
            await self._reload()
            return await self.async_step_init()
        return self.async_show_form(
            step_id="add_details", data_schema=self._details_schema()
        )

    def _company_name(self) -> str:
        """Name of the picked company (empty when linking by raw UUID)."""
        return next(
            (
                company.company_name
                for company in self._catalog
                if company.company_uuid == self._company_uuid
            ),
            "",
        )

    def _details_schema(self) -> vol.Schema:
        own_rut = str(self._entry.data.get(CONF_RUT, ""))
        # The nickname becomes the device name / entity id and is stored on
        # Unired, so default it to the company, never to the holder's RUT.
        return vol.Schema(
            {
                vol.Required(CONF_IDENTIFIER, default=own_rut): str,
                vol.Required(CONF_NICKNAME, default=self._company_name()): str,
            }
        )

    async def async_step_remove_service(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Unlink selected accounts server-side."""
        accounts = await self._known_accounts()
        options = {
            account.uuid: f"{account.nickname or account.company_name} "
            f"({account.identifier})"
            for account in accounts
        }
        if user_input is not None:
            selected = [str(uuid) for uuid in user_input.get("accounts", [])]
            if not selected:
                return self.async_show_form(
                    step_id="remove_service",
                    data_schema=vol.Schema(
                        {vol.Required("accounts"): cv.multi_select(options)}
                    ),
                    errors={"base": "invalid_input"},
                )
            try:
                client, access_token = await self._authed_client()
                await client.delete_accounts(access_token, selected)
            except Exception:  # noqa: BLE001 - surfaced below via form error
                return self.async_show_form(
                    step_id="remove_service",
                    data_schema=vol.Schema(
                        {vol.Required("accounts"): cv.multi_select(options)}
                    ),
                    errors={"base": "unknown"},
                )
            await self._reload()
            return await self.async_step_init()
        return self.async_show_form(
            step_id="remove_service",
            data_schema=vol.Schema(
                {vol.Required("accounts"): cv.multi_select(options)}
            ),
        )

    async def _known_accounts(self) -> list[Account]:
        coordinator = getattr(
            getattr(self._entry, "runtime_data", None), "coordinator", None
        )
        if coordinator is None or coordinator.data is None:
            return []
        return list(coordinator.data.accounts)

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Tune the poll interval."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = self._entry.options.get(
            CONF_SCAN_INTERVAL_S,
            self._entry.data.get(CONF_SCAN_INTERVAL_S, DEFAULT_SCAN_INTERVAL_S),
        )
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL_S, default=current): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL_S, max=MAX_SCAN_INTERVAL_S),
                    )
                }
            ),
        )
