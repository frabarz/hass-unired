"""Pairing orchestration: login → registration/device branches → tokens.

Implements PAT-002: the setup flow tries ``loginWithDevice`` first and lets
the *server codes* decide the path — ``0603`` starts registration,
``0630`` starts device pairing, tokens mean done. Each OTP is submitted
exactly once per user-provided code (SEC-002); there is no resend path
(the server resend endpoints are dead — findings.md §7).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .api import UniredClient
from .exceptions import UniredDeviceError, UniredError, UniredNotFoundError
from .models import DeviceFingerprint, Tokens

#: OTP reason passed to the provider: a code for a pending registration…
REASON_REGISTRATION = "registration"
#: …or a code for pairing this device.
REASON_DEVICE = "device"

#: Async callback returning the user-typed OTP for the given reason.
OtpProvider = Callable[[str], Awaitable[str]]

#: Sync callback receiving rotated tokens so the caller can persist them.
TokensSink = Callable[[Tokens], None]


@dataclass(frozen=True)
class Authenticated:
    """Pairing complete; ready to create the config entry."""

    tokens: Tokens
    name: str = ""


@dataclass(frozen=True)
class NeedRegistration:
    """Unknown user: a registration OTP is on its way."""

    user_identifier: str


@dataclass(frozen=True)
class NeedDevicePairing:
    """Unknown device: a pairing OTP is on its way."""

    device_uuid: str | None
    user_identifier: str | None
    cooldown: str | None


@dataclass(frozen=True)
class Failed:
    """Terminal failure carrying the server code for UI mapping."""

    code: str | None
    message: str


AuthResult = Authenticated | NeedRegistration | NeedDevicePairing | Failed


async def start_login(
    client: UniredClient, rut: str, email: str, device: DeviceFingerprint
) -> AuthResult:
    """Try login; branch to registration/pairing on 0603/0630.

    The code-sending POST (``registration`` or ``device``) is issued here so
    that ``Need*`` always means "OTP already sent".
    """
    try:
        tokens = await client.login(rut, email, device)
    except UniredNotFoundError:
        try:
            user_identifier = await client.preregister(rut, email)
        except UniredError as err:
            return Failed(err.code, str(err))
        return NeedRegistration(user_identifier)
    except UniredDeviceError:
        try:
            reg = await client.register_device(email, rut, device)
        except UniredError as err:
            return Failed(err.code, str(err))
        return NeedDevicePairing(reg.device_uuid, reg.user_identifier, reg.cooldown)
    except UniredError as err:
        return Failed(err.code, str(err))
    return Authenticated(tokens)


async def submit_registration_otp(
    client: UniredClient,
    *,
    user_identifier: str,
    code: str,
    device: DeviceFingerprint,
    email: str,
    rut: str,
    name: str,
    uuid_tyc: str,
) -> AuthResult:
    """Validate a registration OTP, complete signup, start device pairing."""
    try:
        await client.activate_registration(user_identifier, code, device)
        await client.complete_registration(user_identifier, name, uuid_tyc)
        reg = await client.register_device(email, rut, device)
    except UniredError as err:
        return Failed(err.code, str(err))
    return NeedDevicePairing(reg.device_uuid, reg.user_identifier, reg.cooldown)


async def submit_device_otp(
    client: UniredClient,
    *,
    device: DeviceFingerprint,
    email: str,
    rut: str,
    otp: str,
) -> AuthResult:
    """Verify a device-pairing OTP; single attempt, no retries (SEC-002)."""
    try:
        authz = await client.authorize_device(device, email, rut, otp)
    except UniredError as err:
        return Failed(err.code, str(err))
    return Authenticated(authz.tokens, authz.name)


async def ensure_tokens(
    client: UniredClient,
    rut: str,
    email: str,
    device: DeviceFingerprint,
    otp_provider: OtpProvider,
    *,
    name: str,
) -> AuthResult:
    """Run the whole pairing tree; ``otp_provider`` supplies each OTP once."""
    result = await start_login(client, rut, email, device)
    if isinstance(result, (Authenticated, Failed)):
        return result
    if isinstance(result, NeedRegistration):
        try:
            terms = await client.get_tyc()
        except UniredError as err:
            return Failed(err.code, str(err))
        code = await otp_provider(REASON_REGISTRATION)
        result = await submit_registration_otp(
            client,
            user_identifier=result.user_identifier,
            code=code,
            device=device,
            email=email,
            rut=rut,
            name=name,
            uuid_tyc=terms.uuid,
        )
        if isinstance(result, (Authenticated, Failed)):
            return result
    pairing = result
    assert isinstance(pairing, NeedDevicePairing)
    code = await otp_provider(REASON_DEVICE)
    return await submit_device_otp(
        client, device=device, email=email, rut=rut, otp=code
    )


async def refresh_if_needed(
    client: UniredClient,
    tokens: Tokens,
    *,
    force: bool = False,
    on_refreshed: TokensSink | None = None,
) -> Tokens:
    """Return valid tokens, rotating via refresh when expired/forced.

    The rotated triple must be persisted by ``on_refreshed`` — the old one
    dies server-side. Refresh-on-0700 with single retry lives in the
    coordinator (Phase 4); this helper only covers expiry/forced rotation.
    """
    if not force and not tokens.is_expired():
        return tokens
    fresh = await client.refresh(tokens)
    if on_refreshed is not None:
        on_refreshed(fresh)
    return fresh
