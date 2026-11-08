"""Shared polling coordinator: accounts → instruments → debts per entry."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import UniredClient
from .const import (
    CONF_EMAIL,
    CONF_SCAN_INTERVAL_S,
    CONF_TOKENS,
    DEFAULT_SCAN_INTERVAL_S,
    DOMAIN,
    REFRESH_CODES,
)
from .exceptions import (
    UniredAuthError,
    UniredConnectionError,
    UniredError,
    UniredRateLimitError,
)
from .models import (
    Account,
    DebtSummary,
    Instrument,
    Tokens,
    UniredData,
)

_LOGGER = logging.getLogger(__name__)

_RATE_LIMIT_RETRY_AFTER_S = 3600


def _option[T](entry: ConfigEntry, key: str, default: T) -> T:
    """Prefer options over setup data, falling back to a default."""
    if key in entry.options:
        return entry.options[key]
    return entry.data.get(key, default)


class UniredCoordinator(DataUpdateCoordinator[UniredData]):
    """Poll all accounts/instruments/debts of one Unired user."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: UniredClient,
    ) -> None:
        """Create the coordinator; tokens live in the entry data."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}-{entry.entry_id}",
            update_interval=timedelta(
                seconds=_option(entry, CONF_SCAN_INTERVAL_S, DEFAULT_SCAN_INTERVAL_S),
            ),
            always_update=False,
        )
        self._entry = entry
        self._client = client
        self._refresh_lock = asyncio.Lock()
        self.refresh_options()

    def refresh_options(self) -> None:
        """Re-read the poll interval after an options change."""
        self.update_interval = timedelta(
            seconds=_option(self._entry, CONF_SCAN_INTERVAL_S, DEFAULT_SCAN_INTERVAL_S),
        )

    def _tokens(self) -> Tokens:
        return Tokens.from_dict(self._entry.data[CONF_TOKENS])

    async def _save_tokens(self, tokens: Tokens) -> None:
        self.hass.config_entries.async_update_entry(
            self._entry,
            data={**self._entry.data, CONF_TOKENS: tokens.to_dict()},
        )

    async def _refresh_tokens(self, force: bool = False) -> Tokens:
        """Rotate tokens once, serialized against concurrent polls."""
        async with self._refresh_lock:
            current = self._tokens()
            if not force and not current.is_expired():
                return current
            fresh = await self._client.refresh(current)
            await self._save_tokens(fresh)
            return fresh

    async def _fetch(self, access_token: str) -> UniredData:
        accounts: list[Account] = await self._client.get_accounts(access_token)
        instruments: dict[str, tuple[Instrument, ...]] = {}
        debts: dict[tuple[str, str], DebtSummary] = {}
        for account in accounts:
            try:
                items = await self._client.get_instruments(access_token, account.uuid)
            except (UniredAuthError, UniredRateLimitError):
                raise
            except UniredError as err:
                _LOGGER.warning("Skipping instruments of %s: %s", account.uuid, err)
                continue
            instruments[account.uuid] = tuple(items)
            for instrument in items:
                try:
                    summary = await self._client.get_debt(
                        access_token,
                        account.uuid,
                        instrument.uuid,
                    )
                except (UniredAuthError, UniredRateLimitError):
                    raise
                except UniredError as err:
                    _LOGGER.warning(
                        "Skipping debt of %s/%s: %s",
                        account.uuid,
                        instrument.uuid,
                        err,
                    )
                    continue
                debts[(account.uuid, instrument.uuid)] = summary
        return UniredData(
            accounts=tuple(accounts),
            instruments=instruments,
            debts=debts,
        )

    async def _async_update_data(self) -> UniredData:
        """Poll everything; refresh once on 0700/0701, reauth otherwise."""
        try:
            tokens = await self._refresh_tokens()
            try:
                return await self._fetch(tokens.access_token)
            except UniredAuthError as err:
                if err.code not in REFRESH_CODES:
                    msg = f"Unired rejected the session ({err.code}); re-pair required"
                    raise ConfigEntryAuthFailed(msg) from err
                tokens = await self._refresh_tokens(force=True)
                try:
                    return await self._fetch(tokens.access_token)
                except UniredAuthError as retry_err:
                    msg = "Unired rejected the refreshed session; re-pair required"
                    raise ConfigEntryAuthFailed(msg) from retry_err
        except ConfigEntryAuthFailed:
            raise
        except UniredAuthError as err:
            msg = f"Unired session invalid ({err.code}); re-pair required"
            raise ConfigEntryAuthFailed(msg) from err
        except UniredRateLimitError as err:
            msg = f"Unired rate limit: {err}"
            raise UpdateFailed(msg, retry_after=_RATE_LIMIT_RETRY_AFTER_S) from err
        except (UniredConnectionError, UniredError) as err:
            msg = f"Unired request failed: {err}"
            raise UpdateFailed(msg) from err

    async def async_add_account(
        self,
        company_uuid: str,
        identifier: str,
        nickname: str,
    ) -> None:
        """Link a service server-side, then reload so sensors appear."""
        tokens = await self._refresh_tokens()
        await self._client.link_account(
            tokens.access_token,
            nickname=nickname,
            identifier=identifier,
            company_uuid=company_uuid,
        )
        self._reload()

    async def async_remove_accounts(self, account_uuids: list[str]) -> None:
        """Unlink services server-side, then reload so sensors vanish."""
        tokens = await self._refresh_tokens()
        await self._client.delete_accounts(tokens.access_token, account_uuids)
        self._reload()

    def _reload(self) -> None:
        self.hass.config_entries.async_schedule_reload(self._entry.entry_id)

    @property
    def current_email(self) -> str:
        """E-mail of the paired user (for options-flow prompts)."""
        return str(self._entry.data.get(CONF_EMAIL, ""))
