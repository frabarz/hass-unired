"""Bill sensors: one monetary sensor per account instrument."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import APP_VERSION, ATTRIBUTION, DOMAIN
from .coordinator import UniredCoordinator
from .entity import UniredEntity
from .models import Account, DebtSummary, Instrument


def _bill_dict(bill: Any) -> dict[str, Any]:
    """Serialize one bill for state attributes (no raw PII blob)."""
    return {
        "amount": bill.amount,
        "debt_type": bill.debt_type,
        "due_date": bill.due_date,
        "contract": bill.contract,
        "selected": bill.selected,
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add one bill sensor per instrument known after the first refresh."""
    coordinator: UniredCoordinator = entry.runtime_data.coordinator
    data = coordinator.data
    async_add_entities(
        UniredBillSensor(coordinator, account, instrument)
        for account in data.accounts
        for instrument in data.instruments.get(account.uuid, ())
    )


class UniredBillSensor(UniredEntity, SensorEntity):
    """Total owed for one instrument; amount > 0 means a bill is prepared."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "CLP"
    _attr_has_entity_name = True
    _attr_translation_key = "bill_amount"

    def __init__(
        self,
        coordinator: UniredCoordinator,
        account: Account,
        instrument: Instrument,
    ) -> None:
        """Bind the sensor and fix stable ids from server UUIDs."""
        super().__init__(coordinator)
        self._account_uuid = account.uuid
        self._instrument_uuid = instrument.uuid
        self._attr_unique_id = f"{account.uuid}_{instrument.uuid}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, account.uuid)},
            name=account.nickname or account.company_name,
            manufacturer=account.company_name,
            model=account.industry_name or account.company_name,
            sw_version=APP_VERSION,
        )

    def _summary(self) -> DebtSummary | None:
        data = self.coordinator.data
        if data is None:
            return None
        return data.debt_for(self._account_uuid, self._instrument_uuid)

    @property
    def native_value(self) -> int | None:
        """Return total owed CLP, or unknown while the poll lacks data."""
        summary = self._summary()
        if summary is None:
            return None
        return summary.owed_total

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return bill detail backing cards and automations."""
        summary = self._summary()
        if summary is None:
            return {"attribution": ATTRIBUTION}
        account = next(
            (
                item
                for item in self.coordinator.data.accounts
                if item.uuid == self._account_uuid
            ),
            None,
        )
        return {
            "bills": [_bill_dict(bill) for bill in summary.bills],
            "bill_count": len(summary.bills),
            "company": account.company_name if account else None,
            "account_identifier": account.identifier if account else None,
            "account_nickname": account.nickname if account else None,
            "allows_credit": summary.allows_credit,
            "accept_zero_debt": summary.accept_zero_debt,
            "presentation_rule": list(summary.presentation_rule),
            "attribution": ATTRIBUTION,
        }
