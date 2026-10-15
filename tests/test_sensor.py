"""End-to-end sensor tests over a fully set-up entry (mocked backend)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unired.api import UniredClient
from custom_components.unired.const import CONF_DEVICE, CONF_EMAIL, DOMAIN
from custom_components.unired.exceptions import UniredConnectionError
from custom_components.unired.models import DeviceFingerprint

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

CL = ZoneInfo("America/Santiago")

ACCOUNTS: list[dict[str, Any]] = [
    {
        "uuid": "a-internet",
        "nickname": "CORE Internet",
        "identifier": "11222333",
        "company": "Mundo Pacífico",
        "industry": "Tv Cable",
        "instrument": "i-internet",
        "debt": [],
    },
    {
        "uuid": "a-agua",
        "nickname": "CORE Agua",
        "identifier": "4455667",
        "company": "Essbio",
        "industry": "Agua",
        "instrument": "i-agua",
        "debt": [{"amount": 0}],
    },
    {
        "uuid": "a-luz",
        "nickname": "CORE Luz",
        "identifier": "8899001",
        "company": "CGE S.A.",
        "industry": "Luz",
        "instrument": "i-luz",
        "debt": [
            {
                "amount": 10600,
                "debtType": "Deuda Total",
                "queryAttribute": [
                    {"code": "NUMCON", "value": "001122334455"},
                    {"code": "FECVEN", "value": ""},
                ],
                "selected": True,
            }
        ],
    },
]


def _entry_data() -> dict[str, Any]:
    expires = datetime.now(CL) + timedelta(hours=6)
    return {
        "rut": "172143520",
        CONF_EMAIL: "user@example.cl",
        "name": "Test User",
        CONF_DEVICE: DeviceFingerprint.generate().to_dict(),
        "tokens": {
            "accessToken": "ACCESS",
            "refreshToken": "REFRESH",
            "expirationDate": expires.isoformat(),
        },
    }


def _patch_backend(monkeypatch: pytest.MonkeyPatch, fail_debt: bool = False) -> None:
    from custom_components.unired.models import (
        Account,
        DebtSummary,
        Instrument,
        debt_summary_from_dict,
    )

    async def fake_get_accounts(self: UniredClient, access_token: str) -> Any:
        return [
            Account(
                uuid=str(item["uuid"]),
                nickname=str(item["nickname"]),
                identifier=str(item["identifier"]),
                company_name=str(item["company"]),
                industry_name=str(item["industry"]),
            )
            for item in ACCOUNTS
        ]

    async def fake_get_instruments(
        self: UniredClient, access_token: str, account_uuid: str
    ) -> Any:
        item = next(a for a in ACCOUNTS if a["uuid"] == account_uuid)
        return [
            Instrument(
                uuid=str(item["instrument"]),
                name=str(item["company"]),
                account_uuid=account_uuid,
                account_identifier=str(item["identifier"]),
                account_nickname=str(item["nickname"]),
            )
        ]

    async def fake_get_debt(
        self: UniredClient, access_token: str, account_uuid: str, instrument_uuid: str
    ) -> Any:
        if fail_debt and account_uuid == "a-agua":
            raise UniredConnectionError("blip")
        item = next(a for a in ACCOUNTS if a["uuid"] == account_uuid)
        summary: DebtSummary = debt_summary_from_dict(
            instrument_uuid,
            {
                "allowsCredit": "N",
                "acceptZeroDebt": "N",
                "billList": item["debt"],
                "presentationRule": [{"code": "AUTODE"}],
            },
        )
        return summary

    monkeypatch.setattr(UniredClient, "get_accounts", fake_get_accounts)
    monkeypatch.setattr(UniredClient, "get_instruments", fake_get_instruments)
    monkeypatch.setattr(UniredClient, "get_debt", fake_get_debt)


def _entity_id(
    hass: HomeAssistant, account_uuid: str, instrument_uuid: str
) -> str | None:
    registry = er.async_get(hass)
    return registry.async_get_entity_id(
        "sensor", DOMAIN, f"{account_uuid}_{instrument_uuid}"
    )


async def test_bill_sensors_report_states_and_attributes(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owed/paid/empty instruments map to 10600/0/0 with rich attributes."""
    _patch_backend(monkeypatch)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)

    expectations = {
        ("a-internet", "i-internet"): ("0", 0),
        ("a-agua", "i-agua"): ("0", 1),
        ("a-luz", "i-luz"): ("10600", 1),
    }
    for (account_uuid, instrument_uuid), (state, bill_count) in expectations.items():
        entity_id = _entity_id(hass, account_uuid, instrument_uuid)
        assert entity_id is not None
        snapshot = hass.states.get(entity_id)
        assert snapshot is not None
        assert snapshot.state == state
        assert snapshot.attributes["bill_count"] == bill_count
        assert snapshot.attributes["device_class"] == "monetary"

    luz_id = _entity_id(hass, "a-luz", "i-luz")
    assert luz_id is not None
    luz_state = hass.states.get(luz_id)
    assert luz_state is not None
    attrs = luz_state.attributes
    assert attrs["company"] == "CGE S.A."
    assert attrs["account_identifier"] == "8899001"
    assert attrs["bills"][0]["contract"] == "001122334455"
    assert attrs["presentation_rule"] == ["AUTODE"]


async def test_missing_debt_reads_unknown(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An instrument whose debt poll fails stays unknown, not zero."""
    _patch_backend(monkeypatch, fail_debt=True)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    entity_id = _entity_id(hass, "a-agua", "i-agua")
    assert entity_id is not None
    snapshot = hass.states.get(entity_id)
    assert snapshot is not None
    assert snapshot.state == STATE_UNKNOWN
