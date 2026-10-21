"""Weekly report date shared by the screener and market recap."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def previous_week_friday(today: date | None = None) -> date:
    """Return the Friday of the previous Monday-to-Sunday calendar week."""
    today = today or datetime.now(KST).date()
    return today - timedelta(days=today.weekday() + 3)
