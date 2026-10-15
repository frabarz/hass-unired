"""Diagnostics for Unired config entries (secrets and PII redacted)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

TO_REDACT = {
    "accessToken",
    "refreshToken",
    "uniqueId",
    "deviceId",
    "NOMCON",
    "DGLOSA",
    "contract",
    "identifier",
    "account_identifier",
    "rut",
    "email",
}


def _bill_dict(bill: Any) -> dict[str, Any]:
    """Serialize one bill for the diagnostics payload."""
    return {
        "amount": bill.amount,
        "debt_type": bill.debt_type,
        "due_date": bill.due_date,
        "contract": bill.contract,
        "selected": bill.selected,
        "attributes": dict(bill.attributes),
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return the poll snapshot with secrets and identifiers redacted.

    Entry data (e-mail, RUT, tokens, device ids) is never dumped; only the
    coordinator snapshot and the non-sensitive scan interval are included.
    """
    data = entry.runtime_data.coordinator.data
    payload: dict[str, Any] = {
        "scan_interval_s": entry.options.get("scan_interval_s"),
        "accounts": [
            {
                "uuid": account.uuid,
                "nickname": account.nickname,
                "identifier": account.identifier,
                "company_name": account.company_name,
                "industry_name": account.industry_name,
            }
            for account in data.accounts
        ],
        "debts": {
            f"{account_uuid}/{instrument_uuid}": {
                "owed_total": summary.owed_total,
                "bill_count": len(summary.bills),
                "bills": [_bill_dict(bill) for bill in summary.bills],
                "allows_credit": summary.allows_credit,
                "accept_zero_debt": summary.accept_zero_debt,
                "presentation_rule": list(summary.presentation_rule),
            }
            for (account_uuid, instrument_uuid), summary in data.debts.items()
        },
    }
    return async_redact_data(payload, TO_REDACT)
