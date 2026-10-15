"""Async client for the Unired app backend.

All methods raise :mod:`exceptions` on failure; ``UniredAuthError`` carries
the server result code (``0700``/``0701`` refreshable, ``0509``/``0605``
re-pair). The debt endpoint answers HTTP 201 — any 2xx is accepted.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .const import (
    API_BASE,
    CODE_AUTH_RETRY,
    CODE_DEVICE_ALREADY_REGISTERED,
    CODE_LOGOUT,
    CODE_NEW_DEVICE_LOGOUT,
    CODE_OK,
    CODE_UNAUTHORIZED,
    CODE_UNREGISTERED_DEVICE,
    CODE_UNREGISTERED_USER,
    PATH_ACCOUNT,
    PATH_ACCOUNT_DELETE,
    PATH_DEBT,
    PATH_DEVICE,
    PATH_DEVICE_AUTHORIZE,
    PATH_INSCRIPTION_ACCOUNT,
    PATH_INSCRIPTION_ITEMS,
    PATH_INSTRUMENT_LOOKUP,
    PATH_INSTRUMENTS,
    PATH_LOGIN_AUTHORIZE,
    PATH_LOGIN_DEVICE,
    PATH_LOGOUT,
    PATH_REFRESH,
    PATH_REGISTRATION,
    PATH_REGISTRATION_ACTIVATION,
    PATH_REGISTRATION_COMPLETE,
    PATH_TYC,
    REQUEST_TIMEOUT_S,
    normalize_rut,
)
from .exceptions import (
    UniredAuthError,
    UniredConnectionError,
    UniredDeviceError,
    UniredError,
    UniredNotFoundError,
    UniredRateLimitError,
)
from .models import (
    Account,
    Authorization,
    DebtSummary,
    DeviceFingerprint,
    DeviceRegistration,
    Instrument,
    LinkableCompany,
    TermsInfo,
    Tokens,
    debt_summary_from_dict,
    linkable_companies_from_dict,
)

_AUTH_HEADER = "access_token"
_REFRESH_HEADER = "refresh_token"


class UniredClient:
    """Thin async wrapper over the Unired v1 API on an injected session."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def _call(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        access_token: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        """Perform a request and return the ``data`` envelope, mapped to errors."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if access_token:
            headers[_AUTH_HEADER] = access_token
        if extra_headers:
            headers.update(extra_headers)
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_S):
                async with self._session.request(
                    method, API_BASE + path, json=json_body, headers=headers
                ) as response:
                    return self._handle(response.status, await self._json(response))
        except UniredError:
            raise
        except (TimeoutError, aiohttp.ClientError) as err:
            raise UniredConnectionError(f"Unired request failed: {err}") from err

    @staticmethod
    async def _json(response: aiohttp.ClientResponse) -> dict:
        try:
            payload = await response.json()
        except (aiohttp.ContentTypeError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _handle(status: int, payload: dict) -> Any:
        if status == 429:
            raise UniredRateLimitError("Unired backend throttled the request", "429")
        code = payload.get("code")
        message = str(payload.get("message", f"HTTP {status}"))
        if not 200 <= status < 300 or code not in (None, CODE_OK):
            if code == CODE_UNREGISTERED_USER:
                raise UniredNotFoundError(message, code)
            if code in (CODE_UNREGISTERED_DEVICE, CODE_DEVICE_ALREADY_REGISTERED):
                raise UniredDeviceError(message, code)
            if (
                code
                in (
                    CODE_UNAUTHORIZED,
                    CODE_AUTH_RETRY,
                    CODE_NEW_DEVICE_LOGOUT,
                    CODE_LOGOUT,
                )
                or status == 401
            ):
                raise UniredAuthError(message, code)
            raise UniredError(message, code)
        return payload.get("data")

    async def get_tyc(self) -> TermsInfo:
        """Fetch current terms; ``uuid`` is the ``uuidTyc`` for registration."""
        data = await self._call("GET", PATH_TYC)
        return TermsInfo(uuid=str(data["uuid"]), version=data.get("version"))

    async def preregister(self, rut: str, email: str) -> str:
        """Start registration; returns the ``userIdentifier`` (HTTP 201)."""
        data = await self._call(
            "POST",
            PATH_REGISTRATION,
            json_body={"rut": normalize_rut(rut), "email": email.strip()},
        )
        return str(data["userIdentifier"])

    async def activate_registration(
        self, user_identifier: str, code: str, device: DeviceFingerprint
    ) -> dict:
        """Validate the e-mail OTP for a pending registration (shape TBD live)."""
        return await self._call(
            "PATCH",
            PATH_REGISTRATION_ACTIVATION.format(uid=user_identifier),
            json_body={"codeVerification": code, "device": device.to_dict()},
        )

    async def complete_registration(
        self, user_identifier: str, name: str, uuid_tyc: str
    ) -> dict:
        """Finish registration with the holder name + accepted terms (shape TBD)."""
        return await self._call(
            "PATCH",
            PATH_REGISTRATION_COMPLETE.format(uid=user_identifier),
            json_body={"name": name, "uuidTyc": uuid_tyc},
        )

    async def login(self, rut: str, email: str, device: DeviceFingerprint) -> Tokens:
        """Log in a known device; raises 0603/0630 for unknown user/device."""
        data = await self._call(
            "POST",
            PATH_LOGIN_DEVICE,
            json_body={
                "user": {"email": email.strip(), "rut": normalize_rut(rut)},
                "device": device.to_dict(),
            },
        )
        return Tokens.from_dict(data)

    async def login_authorize(self, user_identifier: str, otp: str) -> Tokens:
        """Contingency login-OTP path (OOS-001 unless the server demands it)."""
        data = await self._call(
            "POST",
            PATH_LOGIN_AUTHORIZE.format(uid=user_identifier),
            json_body={"otp": otp},
        )
        return Tokens.from_dict(data)

    async def register_device(
        self, email: str, rut: str, device: DeviceFingerprint
    ) -> DeviceRegistration:
        """Pair a new device; returns identifiers and OTP cooldown (HTTP 201)."""
        data = await self._call(
            "POST",
            PATH_DEVICE,
            json_body={
                "user": {"email": email.strip(), "rut": normalize_rut(rut)},
                "device": device.to_dict(),
            },
        )
        return DeviceRegistration(
            device_uuid=str(data["deviceUuid"]),
            user_identifier=str(data["userIdentifier"]),
            cooldown=data.get("cooldown"),
        )

    async def authorize_device(
        self, device: DeviceFingerprint, email: str, rut: str, otp: str
    ) -> Authorization:
        """Verify the device OTP; returns fresh tokens plus the holder name."""
        data = await self._call(
            "POST",
            PATH_DEVICE_AUTHORIZE,
            json_body={
                "device": device.to_dict(),
                "user": {"email": email.strip(), "rut": normalize_rut(rut)},
                "otp": otp,
            },
        )
        return Authorization(
            tokens=Tokens.from_dict(data), name=str(data.get("name", ""))
        )

    async def refresh(self, tokens: Tokens) -> Tokens:
        """Rotate the token triple; the old one dies — persist the result."""
        data = await self._call(
            "POST",
            PATH_REFRESH,
            json_body={},
            extra_headers={
                _AUTH_HEADER: tokens.access_token,
                _REFRESH_HEADER: tokens.refresh_token,
            },
        )
        return Tokens.from_dict(data)

    async def logout(self, tokens: Tokens) -> None:
        """Close the server session (best effort on entry removal)."""
        await self._call("POST", PATH_LOGOUT, access_token=tokens.access_token)

    async def get_accounts(self, access_token: str) -> list[Account]:
        """List linked utility accounts."""
        data = await self._call("GET", PATH_ACCOUNT, access_token=access_token)
        return [
            Account(
                uuid=str(item["uuid"]),
                nickname=str(item.get("nickname", "")),
                identifier=str(item.get("identifier", "")),
                company_name=str(item.get("company", {}).get("name", "")),
                industry_name=item.get("company", {}).get("industryName"),
            )
            for item in data.get("accounts", [])
        ]

    async def get_instruments(
        self, access_token: str, account_uuid: str
    ) -> list[Instrument]:
        """List billable instruments of one account."""
        data = await self._call(
            "GET",
            PATH_INSTRUMENTS.format(uuid=account_uuid),
            access_token=access_token,
        )
        return [
            Instrument(
                uuid=str(item["instrumentUuid"]),
                name=str(item.get("name", "")),
                account_uuid=account_uuid,
                account_identifier=(item.get("account") or {}).get("identifier"),
                account_nickname=(item.get("account") or {}).get("nickname"),
            )
            for item in data.get("instrumentList", [])
        ]

    async def get_debt(
        self, access_token: str, account_uuid: str, instrument_uuid: str
    ) -> DebtSummary:
        """Fetch the debt payload (HTTP 201) parsed to a DebtSummary."""
        data = await self._call(
            "GET",
            PATH_DEBT.format(
                account_uuid=account_uuid, instrument_uuid=instrument_uuid
            ),
            access_token=access_token,
        )
        return debt_summary_from_dict(instrument_uuid, data)

    async def inscription_items(
        self, access_token: str | None = None
    ) -> list[LinkableCompany]:
        """List linkable companies (works unauthenticated; verified live)."""
        data = await self._call(
            "GET", PATH_INSCRIPTION_ITEMS, access_token=access_token
        )
        return linkable_companies_from_dict(data)

    async def lookup_instrument(
        self, code: str, access_token: str | None = None
    ) -> list[dict]:
        """Look up instruments by service code (shape probed live)."""
        data = await self._call(
            "GET",
            f"{PATH_INSTRUMENT_LOOKUP}?code={code}",
            access_token=access_token,
        )
        if isinstance(data, list):
            return list(data)
        return list(data.get("instrumentList", data.get("items", [])))

    async def link_account(
        self, access_token: str, *, nickname: str, identifier: str, company_uuid: str
    ) -> dict:
        """Link a service: identifier is RUT-like, dots/dashes stripped (app)."""
        return await self._call(
            "POST",
            PATH_INSCRIPTION_ACCOUNT,
            json_body={
                "nickname": nickname,
                "identifier": normalize_rut(identifier),
                "companyUuid": company_uuid,
            },
            access_token=access_token,
        )

    async def delete_accounts(
        self, access_token: str, account_uuids: list[str]
    ) -> dict:
        """Unlink accounts; body is a list of {accountUuid} objects (app)."""
        return await self._call(
            "POST",
            PATH_ACCOUNT_DELETE,
            json_body={"accounts": [{"accountUuid": uuid} for uuid in account_uuids]},
            access_token=access_token,
        )
