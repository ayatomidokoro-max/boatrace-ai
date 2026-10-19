"""Source deadlines are JST; SQLite legacy timestamps are UTC. Fail closed."""
from datetime import UTC, datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def instant(value: str | None, default_timezone=UTC) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=default_timezone) if parsed.tzinfo is None else parsed
    except (ValueError, TypeError):
        return None


def eligibility(predicted_at: str | None, closed_at: str | None) -> str:
    predicted, closed = instant(predicted_at), instant(closed_at, JST)
    if predicted is None or closed is None:
        return "missing_time"
    return "eligible" if predicted < closed else "after_deadline"


def upcoming(closed_at: str | None, now: datetime) -> bool:
    closed = instant(closed_at, JST)
    return closed is not None and closed > now
