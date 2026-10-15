"""Typed payloads for the Unired API client (frozen dataclasses)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _flag(value: str | None) -> bool:
    return (value or "").upper() == "S"


@dataclass(frozen=True)
class Tokens:
    """Session token triple issued by authorize/refresh."""

    access_token: str
    refresh_token: str
    expires_at: datetime | None

    @classmethod
    def from_dict(cls, data: dict) -> Tokens:
        """Parse from a ``data`` envelope dict."""
        return cls(
            access_token=str(data["accessToken"]),
            refresh_token=str(data["refreshToken"]),
            expires_at=_parse_dt(data.get("expirationDate")),
        )

    def is_expired(self, now: datetime | None = None) -> bool:
        """True when no expiry is known or it has passed."""
        if self.expires_at is None:
            return True
        now = now or datetime.now(UTC)
        return not now < self.expires_at

    def to_dict(self) -> dict:
        """Serialize to the wire-format triple stored in the entry data."""
        return {
            "accessToken": self.access_token,
            "refreshToken": self.refresh_token,
            "expirationDate": self.expires_at.isoformat() if self.expires_at else None,
        }


@dataclass(frozen=True)
class Authorization:
    """Result of ``device/authorize``: tokens plus the account holder name."""

    tokens: Tokens
    name: str


@dataclass(frozen=True)
class DeviceFingerprint:
    """Stable per-entry Android fingerprint (react-native-device-info fields)."""

    device_id: str
    device_type: str = "Handset"
    device_name: str = "Galaxy A54"
    installer_package_name: str = "com.android.vending"
    mac_address: str = "02:00:00:00:00:00"
    manufacturer: str = "samsung"
    readable_version: str = "1.18.2"
    system_name: str = "Android"
    system_version: str = "14"
    unique_id: str = ""
    version: str = "1.18.2"
    emulator: bool = False
    supported_abis: tuple[str, ...] = ("arm64-v8a", "armeabi-v7a", "armeabi")
    build_number: str = "410"
    carrier: str = "unknown"
    build_id: str = "cl.unired.app"

    @classmethod
    def generate(cls) -> DeviceFingerprint:
        """Create a fresh fingerprint; persist and reuse it forever (SEC-003)."""
        stable = uuid.uuid4().hex
        return cls(device_id="HA-" + stable[:12], unique_id=stable)

    def to_dict(self) -> dict:
        """Serialize to the wire format the app sends as ``device``."""
        return {
            "deviceId": self.device_id,
            "deviceType": self.device_type,
            "deviceName": self.device_name,
            "installerPackageName": self.installer_package_name,
            "macAddress": self.mac_address,
            "manufacturer": self.manufacturer,
            "readableVersion": self.readable_version,
            "systemName": self.system_name,
            "systemVersion": self.system_version,
            "uniqueId": self.unique_id,
            "version": self.version,
            "emulator": self.emulator,
            "supportedAbis": list(self.supported_abis),
            "buildNumber": self.build_number,
            "carrier": self.carrier,
            "buildId": self.build_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DeviceFingerprint:
        """Restore a persisted fingerprint."""
        return cls(
            device_id=data["deviceId"],
            device_type=data.get("deviceType", "Handset"),
            device_name=data.get("deviceName", ""),
            installer_package_name=data.get("installerPackageName", ""),
            mac_address=data.get("macAddress", ""),
            manufacturer=data.get("manufacturer", ""),
            readable_version=data.get("readableVersion", ""),
            system_name=data.get("systemName", ""),
            system_version=data.get("systemVersion", ""),
            unique_id=data.get("uniqueId", ""),
            version=data.get("version", ""),
            emulator=bool(data.get("emulator", False)),
            supported_abis=tuple(data.get("supportedAbis", [])),
            build_number=data.get("buildNumber", ""),
            carrier=data.get("carrier", ""),
            build_id=data.get("buildId", ""),
        )


@dataclass(frozen=True)
class TermsInfo:
    """Terms-and-conditions descriptor; ``uuid`` is the ``uuidTyc``."""

    uuid: str
    version: str | None = None


@dataclass(frozen=True)
class DeviceRegistration:
    """Result of ``POST device``: pairing identifiers plus OTP cooldown."""

    device_uuid: str
    user_identifier: str
    cooldown: str | None = None


@dataclass(frozen=True)
class Account:
    """Linked utility account from ``GET account``."""

    uuid: str
    nickname: str
    identifier: str
    company_name: str
    industry_name: str | None = None


@dataclass(frozen=True)
class Instrument:
    """Billable instrument from ``GET account/{uuid}/instruments``."""

    uuid: str
    name: str
    account_uuid: str
    account_identifier: str | None = None
    account_nickname: str | None = None


@dataclass(frozen=True)
class Bill:
    """Single bill line from a debt ``billList`` entry."""

    amount: int
    debt_type: str | None = None
    due_date: str | None = None
    contract: str | None = None
    selected: bool = False
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DebtSummary:
    """Parsed debt payload for one instrument (debt endpoint returns 201)."""

    instrument_uid: str
    allows_credit: bool
    accept_zero_debt: bool
    bills: tuple[Bill, ...]
    presentation_rule: tuple[str, ...]
    owed_total: int

    @property
    def has_debt(self) -> bool:
        """True when at least one bill with ``amount > 0`` exists (prepared)."""
        return self.owed_total > 0


@dataclass(frozen=True)
class LinkableCompany:
    """Company available for linking via ``POST inscription/account``."""

    company_uuid: str
    company_name: str
    group: str
    multiple_identifier: bool
    allows_bill_scan: bool


def linkable_companies_from_dict(data: dict) -> list[LinkableCompany]:
    """Flatten ``itemsTypeList``/``itemList``/``companyList`` to pickable rows."""
    companies: list[LinkableCompany] = []
    for type_entry in data.get("itemsTypeList", []):
        for item in type_entry.get("itemList", []):
            group = f"{type_entry.get('name', '')} / {item.get('name', '')}"
            for company in item.get("companyList", []):
                if not company.get("uuid"):
                    continue
                companies.append(
                    LinkableCompany(
                        company_uuid=str(company["uuid"]),
                        company_name=str(company.get("name", "")),
                        group=group,
                        multiple_identifier=bool(
                            company.get("multipleIdentifier", False)
                        ),
                        allows_bill_scan=bool(company.get("allowsBillScan", False)),
                    )
                )
    return companies


@dataclass(frozen=True)
class UniredData:
    """One poll snapshot: accounts, their instruments, and each debt."""

    accounts: tuple[Account, ...] = ()
    instruments: dict[str, tuple[Instrument, ...]] = field(default_factory=dict)
    debts: dict[tuple[str, str], DebtSummary] = field(default_factory=dict)

    def debt_for(self, account_uuid: str, instrument_uuid: str) -> DebtSummary | None:
        """Return the debt of one instrument, if polled."""
        return self.debts.get((account_uuid, instrument_uuid))


def _bill_from_dict(raw: dict) -> Bill:
    attrs = {
        str(item.get("code")): str(item.get("value", ""))
        for item in raw.get("queryAttribute", [])
        if item.get("code")
    }

    def _clean(value: str | None) -> str | None:
        if value in (None, "", "00000000"):
            return None
        return value

    try:
        amount = int(raw.get("amount", 0) or 0)
    except (TypeError, ValueError):
        amount = 0
    return Bill(
        amount=amount,
        debt_type=raw.get("debtType"),
        due_date=_clean(attrs.get("FECVEN")),
        contract=_clean(attrs.get("NUMCON")),
        selected=bool(raw.get("selected", False)),
        attributes=attrs,
    )


def debt_summary_from_dict(instrument_uid: str, data: dict) -> DebtSummary:
    """Build a DebtSummary; owed = Σ amount for ``amount > 0`` (findings §7)."""
    bills = tuple(_bill_from_dict(item) for item in data.get("billList", []))
    return DebtSummary(
        instrument_uid=instrument_uid,
        allows_credit=_flag(data.get("allowsCredit")),
        accept_zero_debt=_flag(data.get("acceptZeroDebt")),
        bills=bills,
        presentation_rule=tuple(
            str(rule.get("code"))
            for rule in data.get("presentationRule", [])
            if rule.get("code")
        ),
        owed_total=sum(bill.amount for bill in bills if bill.amount > 0),
    )
