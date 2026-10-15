"""Constants for the Unired integration.

Endpoint paths, server error codes, device-fingerprint values, and config
entry keys. API facts verified live 2026-10-15, see ``findings.md`` §§1-7.
"""

from __future__ import annotations

import re

DOMAIN = "unired"

# Decrypted once during research (findings.md §1); stable across app
# versions 1.7.3 → 1.18.2, hence hardcoded instead of reimplementing the
# app's CryptoJS AES config decryption at runtime.
API_BASE = "https://app1-prod-01.unired.cl/unired-api/v1/"

APP_VERSION = "1.18.2"
BUILD_NUMBER = "410"
BUNDLE_ID = "cl.unired.app"

REQUEST_TIMEOUT_S = 10

# Endpoint paths (relative to API_BASE).
PATH_TYC = "publicInfo/tyc"
PATH_REGISTRATION = "registration"
PATH_REGISTRATION_COMPLETE = "registration/{uid}"
PATH_REGISTRATION_ACTIVATION = "registration/{uid}/activation"
PATH_DEVICE = "device"
PATH_DEVICE_AUTHORIZE = "device/authorize"
PATH_LOGIN_DEVICE = "session/secure/loginWithDevice"
PATH_LOGIN_AUTHORIZE = "session/secure/login/{uid}/authorize"
PATH_REFRESH = "session/refreshToken"
PATH_LOGOUT = "session/logout"
PATH_ACCOUNT = "account"
PATH_INSTRUMENTS = "account/{uuid}/instruments"
PATH_DEBT = "debt/account/{account_uuid}/instrument/{instrument_uuid}"
PATH_INSCRIPTION_ITEMS = "inscription/items"
PATH_INSTRUMENT_LOOKUP = "instrument"
PATH_INSCRIPTION_ACCOUNT = "inscription/account"
PATH_ACCOUNT_DELETE = "account/delete"

# Server result codes.
CODE_OK = "0000"
CODE_UNREGISTERED_USER = "0603"
CODE_UNREGISTERED_DEVICE = "0630"
CODE_DEVICE_ALREADY_REGISTERED = "0907"
CODE_UNAUTHORIZED = "0700"
CODE_AUTH_RETRY = "0701"
CODE_EXTERNAL_ERROR = "0801"
CODE_NEW_DEVICE_LOGOUT = "0509"
CODE_LOGOUT = "0605"
CODE_BAD_OTP = "0407"
CODE_OTP_LOCKED = "0408"
CODE_OTP_WRONG = "0500"
CODE_NO_OTP = "0604"
CODE_DEBT_1 = "0427"
CODE_DEBT_2 = "0428"

# Codes that mean "re-authenticate via a fresh OTP pairing".
REAUTH_CODES = frozenset({CODE_NEW_DEVICE_LOGOUT, CODE_LOGOUT})
# Codes answered by a token refresh + single retry.
REFRESH_CODES = frozenset({CODE_UNAUTHORIZED, CODE_AUTH_RETRY})

# react-native-device-info fields sent as `device` (bundle module 675).
DEVICE_FIELDS = (
    "deviceId",
    "deviceType",
    "deviceName",
    "installerPackageName",
    "macAddress",
    "manufacturer",
    "readableVersion",
    "systemName",
    "systemVersion",
    "uniqueId",
    "version",
    "emulator",
    "supportedAbis",
    "buildNumber",
    "carrier",
    "buildId",
)

# The app strips dots and dashes from the RUT before sending it.
RUT_STRIP_RE = re.compile(r"[.\-]")


def normalize_rut(rut: str) -> str:
    """Normalize a Chilean RUT to digits + check digit, no separators."""
    return RUT_STRIP_RE.sub("", rut.strip()).upper()


# Config entry keys.
CONF_RUT = "rut"
CONF_EMAIL = "email"
CONF_NAME = "name"
CONF_NAME = "name"
CONF_DEVICE = "device"
CONF_TOKENS = "tokens"
CONF_USER_ID = "user_identifier"
CONF_DEVICE_UUID = "device_uuid"
CONF_SCAN_INTERVAL_S = "scan_interval_s"

DEFAULT_SCAN_INTERVAL_S = 21600  # 6h: bills change monthly, not by the minute.
MIN_SCAN_INTERVAL_S = 3600
MAX_SCAN_INTERVAL_S = 86400

ATTRIBUTION = "Datos: Unired (no oficial)"

# Options-flow field keys.
CONF_COMPANY_UUID = "company_uuid"
CONF_IDENTIFIER = "identifier"
CONF_NICKNAME = "nickname"
