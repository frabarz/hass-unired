"""Unired integration entry lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import UniredClient
from .coordinator import UniredCoordinator

PLATFORMS: list[str] = ["sensor"]


@dataclass
class UniredRuntimeData:
    """Shared objects for one paired Unired user."""

    client: UniredClient
    coordinator: UniredCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one user: client, coordinator, then platforms."""
    client = UniredClient(async_get_clientsession(hass))
    coordinator = UniredCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = UniredRuntimeData(client=client, coordinator=coordinator)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply a changed scan interval without re-creating the entry."""
    data: UniredRuntimeData = entry.runtime_data
    data.coordinator.refresh_options()
    await data.coordinator.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Close the server session on removal (best effort, never blocks)."""
    from .const import CONF_TOKENS
    from .models import Tokens

    raw_tokens = entry.data.get(CONF_TOKENS)
    if not raw_tokens:
        return
    try:
        client = UniredClient(async_get_clientsession(hass))
        await client.logout(Tokens.from_dict(raw_tokens))
    except Exception:  # noqa: BLE001 - removal must not fail on network issues
        return


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries; v1 has nothing to migrate yet."""
    return True
