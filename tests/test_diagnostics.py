"""Diagnostics redaction: secrets and identifiers never leak."""

from __future__ import annotations

import json
from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unired import diagnostics as diag
from custom_components.unired.const import DOMAIN
from custom_components.unired.models import (
    Account,
    Bill,
    DebtSummary,
    Instrument,
    UniredData,
)


def _snapshot() -> UniredData:
    account = Account(
        uuid="a-uuid",
        nickname="CORE Luz",
        identifier="8899001",
        company_name="CGE S.A.",
        industry_name="Luz",
    )
    bill = Bill(
        amount=10600,
        debt_type="Deuda Total",
        due_date=None,
        contract="001122334455",
        selected=True,
        attributes={"NOMCON": "NOMBRE SECRETO", "DGLOSA": "CALLE SECRETA 123"},
    )
    summary = DebtSummary(
        instrument_uid="i-uuid",
        allows_credit=False,
        accept_zero_debt=False,
        bills=(bill,),
        presentation_rule=("AUTODE",),
        owed_total=10600,
    )
    instrument = Instrument(uuid="i-uuid", name="CGE S.A.", account_uuid="a-uuid")
    return UniredData(
        accounts=(account,),
        instruments={"a-uuid": (instrument,)},
        debts={("a-uuid", "i-uuid"): summary},
    )


async def test_diagnostics_redacts_secrets_and_pii(hass: HomeAssistant) -> None:
    """Tokens, contacts, contracts and addresses stay out of the payload."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "rut": "172143520",
            "email": "user@example.cl",
            "tokens": {"accessToken": "SECRET", "refreshToken": "SECRET-R"},
        },
        options={"scan_interval_s": 7200},
    )
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(coordinator=SimpleNamespace(data=_snapshot()))
    payload = await diag.async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(payload)
    for secret in (
        "SECRET",
        "user@example.cl",
        "172143520",
        "8899001",
        "001122334455",
        "NOMBRE SECRETO",
        "CALLE SECRETA 123",
    ):
        assert secret not in text
    assert payload["scan_interval_s"] == 7200
    assert payload["debts"]["a-uuid/i-uuid"]["owed_total"] == 10600
    assert payload["accounts"][0]["company_name"] == "CGE S.A."


async def test_redact_key_set_covers_wire_names() -> None:
    """The redact set tracks every sensitive wire/model key in use."""
    assert {
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
    } <= diag.TO_REDACT
