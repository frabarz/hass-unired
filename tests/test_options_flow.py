"""Unit tests for the Unired options flow (menu/add/remove/settings)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unired.api import UniredClient
from custom_components.unired.const import CONF_DEVICE, CONF_EMAIL, DOMAIN
from custom_components.unired.models import (
    DeviceFingerprint,
    LinkableCompany,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

CL = ZoneInfo("America/Santiago")


def _entry() -> MockConfigEntry:
    expires = datetime.now(CL) + timedelta(hours=6)
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            "rut": "172143520",
            CONF_EMAIL: "user@example.cl",
            "name": "Test User",
            CONF_DEVICE: DeviceFingerprint.generate().to_dict(),
            "tokens": {
                "accessToken": "ACCESS",
                "refreshToken": "REFRESH",
                "expirationDate": expires.isoformat(),
            },
        },
    )


async def _open(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.MENU
    return result["flow_id"]


async def _goto(hass: HomeAssistant, flow_id: str, step: str) -> dict[str, Any]:
    return await hass.config_entries.options.async_configure(
        flow_id, {"next_step_id": step}
    )


async def test_add_service_links_and_reloads(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catalog pick → details → link body → reload → back to menu."""
    linked: list[tuple] = []
    reloaded: list[str] = []

    async def fake_items(self: UniredClient) -> list[LinkableCompany]:
        return [
            LinkableCompany(
                company_uuid="c-uuid",
                company_name="CGE S.A.",
                group="Pago Servicios / Luz",
                multiple_identifier=False,
                allows_bill_scan=False,
            )
        ]

    async def fake_link(
        self: UniredClient, access_token: str, **kwargs: Any
    ) -> dict[str, Any]:
        linked.append((access_token, kwargs))
        return {"ok": True}

    monkeypatch.setattr(UniredClient, "inscription_items", fake_items)
    monkeypatch.setattr(UniredClient, "link_account", fake_link)
    monkeypatch.setattr(
        hass.config_entries,
        "async_schedule_reload",
        lambda entry_id: reloaded.append(entry_id),
    )
    entry = _entry()
    entry.add_to_hass(hass)
    flow_id = await _open(hass, entry)
    result = await _goto(hass, flow_id, "add_service")
    assert result["step_id"] == "add_service"
    result = await hass.config_entries.options.async_configure(
        flow_id, {"company_uuid": "c-uuid"}
    )
    assert result["step_id"] == "add_details"
    result = await hass.config_entries.options.async_configure(
        flow_id, {"identifier": "17.214.352-0", "nickname": "Casa"}
    )
    assert result["type"] == FlowResultType.MENU
    assert linked == [
        (
            "ACCESS",
            {
                "nickname": "Casa",
                # Stripped to digits by the client (covered in test_api).
                "identifier": "17.214.352-0",
                "company_uuid": "c-uuid",
            },
        )
    ]
    assert reloaded == [entry.entry_id]


async def test_add_service_blank_fields_rejected(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty identifier/nickname never reaches the server."""
    called = False

    async def fake_link(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return {"ok": True}

    monkeypatch.setattr(UniredClient, "link_account", fake_link)
    entry = _entry()
    entry.add_to_hass(hass)
    flow_id = await _open(hass, entry)
    await _goto(hass, flow_id, "add_service_manual")
    result = await hass.config_entries.options.async_configure(
        flow_id, {"company_uuid": "c-uuid"}
    )
    assert result["step_id"] == "add_details"
    result = await hass.config_entries.options.async_configure(
        flow_id, {"identifier": "  ", "nickname": "Casa"}
    )
    assert result["errors"] == {"base": "invalid_input"}
    assert not called


async def test_catalog_failure_falls_back_to_manual(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unreachable catalog jumps straight to the manual UUID step."""
    from custom_components.unired.exceptions import UniredConnectionError

    async def fake_items(self: UniredClient) -> list[LinkableCompany]:
        raise UniredConnectionError("down")

    monkeypatch.setattr(UniredClient, "inscription_items", fake_items)
    entry = _entry()
    entry.add_to_hass(hass)
    flow_id = await _open(hass, entry)
    result = await _goto(hass, flow_id, "add_service")
    assert result["step_id"] == "add_service_manual"


async def test_remove_service_unlinks_and_reloads(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Multi-select unlink posts uuids then reloads back to the menu."""
    from tests.test_sensor import ACCOUNTS, _entry_data, _patch_backend

    _patch_backend(monkeypatch)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)

    deleted: list[tuple] = []
    reloaded: list[str] = []

    async def fake_delete(
        self: UniredClient, access_token: str, uuids: list[str]
    ) -> dict[str, Any]:
        deleted.append((access_token, uuids))
        return {"ok": True}

    monkeypatch.setattr(UniredClient, "delete_accounts", fake_delete)
    monkeypatch.setattr(
        hass.config_entries,
        "async_schedule_reload",
        lambda entry_id: reloaded.append(entry_id),
    )
    flow_id = await _open(hass, entry)
    result = await _goto(hass, flow_id, "remove_service")
    assert result["step_id"] == "remove_service"
    result = await hass.config_entries.options.async_configure(
        flow_id, {"accounts": ["a-luz"]}
    )
    assert result["type"] == FlowResultType.MENU
    assert deleted == [("ACCESS", ["a-luz"])]
    assert reloaded == [entry.entry_id]
    assert len(ACCOUNTS) == 3  # fixture sanity: three linked services


async def test_remove_service_empty_selection_rejected(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty multi-select stays on screen instead of calling delete."""
    from tests.test_sensor import _entry_data, _patch_backend

    _patch_backend(monkeypatch)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    flow_id = await _open(hass, entry)
    await _goto(hass, flow_id, "remove_service")
    result = await hass.config_entries.options.async_configure(
        flow_id, {"accounts": []}
    )
    assert result["errors"] == {"base": "invalid_input"}


async def test_settings_saves_scan_interval(hass: HomeAssistant) -> None:
    """Settings step persists the poll interval as options."""
    entry = _entry()
    entry.add_to_hass(hass)
    flow_id = await _open(hass, entry)
    await _goto(hass, flow_id, "settings")
    result = await hass.config_entries.options.async_configure(
        flow_id, {"scan_interval_s": 7200}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {"scan_interval_s": 7200}
