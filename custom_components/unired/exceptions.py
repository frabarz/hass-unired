"""Error taxonomy for the Unired API client."""

from __future__ import annotations


class UniredError(Exception):
    """Base error carrying the server result code, if any."""

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class UniredAuthError(UniredError):
    """Missing/expired/rejected session (0700/0701/0509/0605, HTTP 401)."""


class UniredNotFoundError(UniredError):
    """Unknown user (0603)."""


class UniredDeviceError(UniredError):
    """Device pairing state (0630 unregistered, 0907 already registered)."""


class UniredConnectionError(UniredError):
    """Network failure or timeout talking to the Unired backend."""


class UniredRateLimitError(UniredError):
    """Backend throttling (HTTP 429)."""
