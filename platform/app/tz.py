"""Local timezone helpers.

Internal storage stays UTC (naive `datetime.utcnow()` everywhere in the
models/audit log) — that convention is unchanged. These helpers exist for the
places that need to reason about "today" / business hours / displayed times
in the operator's local zone instead of UTC, since this deployment runs out
of Los Angeles.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

LOCAL_TZ_NAME = "America/Los_Angeles"
try:
    LOCAL_TZ = ZoneInfo(LOCAL_TZ_NAME)
except ZoneInfoNotFoundError:
    # Windows without the `tzdata` package has no IANA database at all.
    # Try to auto-install it, then fall back to a fixed UTC-8 offset — the
    # platform must NEVER fail to start because of timezone data.
    try:
        import subprocess
        import sys
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "tzdata"],
                       capture_output=True, timeout=120)
        import importlib
        import zoneinfo
        importlib.reload(zoneinfo)
        LOCAL_TZ = zoneinfo.ZoneInfo(LOCAL_TZ_NAME)
    except Exception:  # noqa: BLE001 — last resort: fixed offset (no DST)
        LOCAL_TZ = dt.timezone(dt.timedelta(hours=-8), "PST")


def now_local() -> dt.datetime:
    """Current time as an aware datetime in the local (LA) zone."""
    return dt.datetime.now(LOCAL_TZ)


def today_local() -> dt.date:
    """Today's date in the local (LA) zone (not UTC)."""
    return now_local().date()


def to_local(value: dt.datetime) -> dt.datetime:
    """Convert a stored UTC datetime (naive or aware) to local (LA) time."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(LOCAL_TZ)


def local_day_str(value: dt.datetime | None) -> str | None:
    """`YYYY-MM-DD` for a stored UTC datetime, using the local calendar day."""
    if value is None:
        return None
    return to_local(value).strftime("%Y-%m-%d")
