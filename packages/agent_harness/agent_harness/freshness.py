"""Data freshness: how old a retrieved snapshot is when the agent uses it.

Some tool results carry an `as_of` snapshot timestamp (e.g. an inventory record cached at
some point in the past). An agent that acts on a snapshot far older than the moment it is
handling the ticket can make a wrong call -- "out of stock last month" when the item is
back in stock today. These helpers turn an `as_of` into an age in days against a logical
"now", so the recorder can emit it as metadata and the detector can reason about it without
ever storing the underlying values.

REFERENCE_NOW is the logical time at which tickets are handled. The benchmark fixtures take
their fresh snapshots on 2026-10-01 and the stale one on 2026-08-12, so a 30-day window
separates the two cleanly and deterministically, independent of wall-clock time.
"""

from __future__ import annotations

from datetime import datetime

REFERENCE_NOW = "2026-10-15T00:00:00Z"
STALE_AFTER_DAYS = 30


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def age_days(as_of: str, checked_at: str = REFERENCE_NOW) -> float:
    """Days between the snapshot time and when it was used (negative if in the future)."""
    return (_parse(checked_at) - _parse(as_of)).total_seconds() / 86400.0


def is_stale(
    as_of: str, checked_at: str = REFERENCE_NOW, threshold: float = STALE_AFTER_DAYS
) -> bool:
    return age_days(as_of, checked_at) > threshold
