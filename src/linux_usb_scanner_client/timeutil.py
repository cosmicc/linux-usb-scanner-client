"""Time helpers for consistent UTC timestamps."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""

    return datetime.now(timezone.utc)


def utc_timestamp(dt: datetime | None = None) -> str:
    """Serialize a datetime as UTC seconds with a trailing Z."""

    value = dt or utc_now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")


def parse_utc_timestamp(value: str | None) -> datetime | None:
    """Parse a stored UTC timestamp, returning None when it is missing or invalid."""

    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

