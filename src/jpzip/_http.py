"""Shared regexes and retry policy helpers used by both clients."""

from __future__ import annotations

import re

ZIP_REGEX = re.compile(r"^\d{7}$")
PREFIX_REGEX = re.compile(r"^\d{1,3}$")

ACCEPT_HEADER = {"Accept": "application/json"}

MAX_ATTEMPTS = 3


def backoff_seconds(attempt: int) -> float:
    """Exponential backoff: 200ms * 2^attempt.

    ``attempt`` is the 0-indexed attempt count *after* the initial try.
    Mirrors the Go SDK's ``200 << attempt`` policy.
    """

    # 200ms << attempt -> 200ms, 400ms, 800ms, ...
    return (200 * (2**attempt)) / 1000.0


def is_valid_zipcode(s: str) -> bool:
    """Return True if *s* looks like a 7-digit zipcode (no fetch)."""

    return bool(ZIP_REGEX.match(s))


def is_valid_prefix(s: str) -> bool:
    return bool(PREFIX_REGEX.match(s))


__all__ = [
    "ACCEPT_HEADER",
    "MAX_ATTEMPTS",
    "PREFIX_REGEX",
    "ZIP_REGEX",
    "backoff_seconds",
    "is_valid_prefix",
    "is_valid_zipcode",
]
