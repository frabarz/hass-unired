"""Unit tests for the Unired coordinator (scripted client stub)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unired.const import CONF_DEVICE, CONF_EMAIL, CONF_TOKENS, DOMAIN
from custom_components.unired.coordinator import UniredCoordinator
from custom_components.unired.exceptions import (
    UniredAuthError,
    UniredConnectionError,
)
from custom_components.unired.models import (
    Account,
    DebtSummary,
    DeviceFingerprint,
    Instrument,
    Tokens,
    debt_summary_from_dict,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

CL = ZoneInfo("America/Santiago")


def _tokens(hours: float = 6) -> dict[str, Any]:
    expires = datetime.now(CL) + timedelta(hours=hours)
    return {
        "accessToken": "ACCESS",
        "refreshToken": "REFRESH",
        "expirationDate": expires.isoformat(),
    }


def _entry_data(**overrides: Any) -> dict[str, Any]:
    data = {
        "rut": "172143520",
        CONF_EMAIL: "user@example.cl",
        "name": "Test User",
        CONF_DEVICE: DeviceFingerprint.generate().to_dict(),
        CONF_TOKENS: _tokens(),
    }
    data.update(overrides)
    return data


def _account(uuid: str = "a-uuid") -> Account:
    return Account(
        uuid=uuid,
        nickname="CORE Luz",
        identifier="8899001",
        company_name="CGE S.A.",
        industry_name="Luz",
    )


def _instrument(uuid: str = "i-uuid") -> Instrument:
    return Instrument(
        uuid=uuid,
        name="CGE S.A.",
        account_uuid="a-uuid",
        account_identifier="8899001",
        account_nickname="CORE Luz",
    )


def _debt(bills: list[dict[str, Any]] | None = None) -> DebtSummary:
    if bills is None:
        bills = [
            {
                "amount": 10600,
                "debtType": "Deuda Total",
                "queryAttribute": [{"code": "NUMCON", "value": "001"}],
                "selected": True,
            }
        ]
    return debt_summary_from_dict(
        "i-uuid",
        {
            "allowsCredit": "N",
            "acceptZeroDebt": "N",
            "billList": bills,
            "presentationRule": [{"code": "AUTODE"}],
        },
    )


class ScriptedClient:
    """Stub UniredClient with scripted per-method outcomes."""

    def __init__(self, script: dict[str, list[Any]]) -> None:
        """Store per-method outcome queues."""
        self._script = {key: list(value) for key, value in script.items()}
        self.calls: list[tuple[str, tuple, dict]] = []

    def _next(self, name: str) -> Any:
        outcome = self._script[name].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def get_accounts(self, *args: Any, **kwargs: Any) -> Any:
        """Scripted accounts."""
        self.calls.append(("get_accounts", args, kwargs))
        return self._next("get_accounts")

    async def get_instruments(self, *args: Any, **kwargs: Any) -> Any:
        """Scripted instruments."""
        self.calls.append(("get_instruments", args, kwargs))
        return self._next("get_instruments")

    async def get_debt(self, *args: Any, **kwargs: Any) -> Any:
        """Scripted debt."""
        self.calls.append(("get_debt", args, kwargs))
        return self._next("get_debt")

    async def refresh(self, *args: Any, **kwargs: Any) -> Any:
        """Scripted rotation."""
        self.calls.append(("refresh", args, kwargs))
        return self._next("refresh")

    async def link_account(self, *args: Any, **kwargs: Any) -> Any:
        """Scripted link."""
        self.calls.append(("link_account", args, kwargs))
        return self._next("link_account")

    async def delete_accounts(self, *args: Any, **kwargs: Any) -> Any:
        """Scripted unlink."""
        self.calls.append(("delete_accounts", args, kwargs))
        return self._next("delete_accounts")


def _coordinator(
    hass: HomeAssistant, client: ScriptedClient, **overrides: Any
) -> tuple[UniredCoordinator, MockConfigEntry]:
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data(**overrides))
    entry.add_to_hass(hass)
    coordinator = UniredCoordinator(hass, entry, client)  # type: ignore[arg-type]
    return coordinator, entry


async def test_full_poll_assembles_snapshot(hass: HomeAssistant) -> None:
    """Accounts → instruments → debts land keyed per instrument."""
    client = ScriptedClient(
        {
            "get_accounts": [[_account()]],
            "get_instruments": [[_instrument()]],
            "get_debt": [_debt()],
        }
    )
    coordinator, _ = _coordinator(hass, client)
    data = await coordinator._async_update_data()
    assert [a.company_name for a in data.accounts] == ["CGE S.A."]
    summary = data.debt_for("a-uuid", "i-uuid")
    assert summary is not None
    assert summary.owed_total == 10600
    assert data.debt_for("a-uuid", "missing") is None
    assert not any(name == "refresh" for name, _, _ in client.calls)


async def test_expired_tokens_refresh_before_poll(hass: HomeAssistant) -> None:
    """Expired triple rotates first and persists to the entry."""
    fresh = Tokens("NEW-A", "NEW-R", datetime.now(CL) + timedelta(hours=6))
    client = ScriptedClient(
        {
            "refresh": [fresh],
            "get_accounts": [[_account()]],
            "get_instruments": [[_instrument()]],
            "get_debt": [_debt([{"amount": 0}])],
        }
    )
    coordinator, entry = _coordinator(hass, client, **{"tokens": _tokens(hours=-1)})
    data = await coordinator._async_update_data()
    summary = data.debt_for("a-uuid", "i-uuid")
    assert summary is not None
    assert summary.owed_total == 0
    assert entry.data[CONF_TOKENS]["accessToken"] == "NEW-A"


async def test_0700_triggers_single_refresh_retry(hass: HomeAssistant) -> None:
    """Mid-poll 0700 refreshes once and retries; second failure reauths."""
    fresh = Tokens("NEW-A", "NEW-R", datetime.now(CL) + timedelta(hours=6))
    client = ScriptedClient(
        {
            "get_accounts": [
                UniredAuthError("stale", "0700"),
                [_account()],
                UniredAuthError("stale", "0700"),
                UniredAuthError("stale", "0700"),
            ],
            "refresh": [fresh, fresh, fresh],
            "get_instruments": [[_instrument()]],
            "get_debt": [_debt([{"amount": 100}])],
        }
    )
    coordinator, _ = _coordinator(hass, client)
    data = await coordinator._async_update_data()
    summary = data.debt_for("a-uuid", "i-uuid")
    assert summary is not None
    assert summary.owed_total == 100
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_0509_reauths_without_refresh(hass: HomeAssistant) -> None:
    """New-device logout goes straight to reauth, no refresh attempted."""
    client = ScriptedClient({"get_accounts": [UniredAuthError("moved", "0509")]})
    coordinator, _ = _coordinator(hass, client)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
    assert not any(name == "refresh" for name, _, _ in client.calls)


async def test_connection_error_becomes_update_failed(hass: HomeAssistant) -> None:
    """Transport failure keeps last data via UpdateFailed."""
    client = ScriptedClient({"get_accounts": [UniredConnectionError("down")]})
    coordinator, _ = _coordinator(hass, client)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_add_and_remove_reload(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Link/unlink hit the server shapes then schedule a reload."""
    reloaded: list[str] = []
    monkeypatch.setattr(
        hass.config_entries,
        "async_schedule_reload",
        lambda entry_id: reloaded.append(entry_id),
    )
    client = ScriptedClient(
        {"link_account": [{"ok": True}], "delete_accounts": [{"ok": True}]}
    )
    coordinator, entry = _coordinator(hass, client)
    await coordinator.async_add_account("c-uuid", "172143520", "Casa")
    await coordinator.async_remove_accounts(["a-uuid"])
    _, link_args, link_kwargs = next(
        call for call in client.calls if call[0] == "link_account"
    )
    assert link_kwargs == {
        "nickname": "Casa",
        "identifier": "172143520",
        "company_uuid": "c-uuid",
    }
    _, del_args, _ = next(call for call in client.calls if call[0] == "delete_accounts")
    assert del_args[1] == ["a-uuid"]
    assert reloaded == [entry.entry_id, entry.entry_id]
