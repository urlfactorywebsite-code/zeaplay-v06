"""Calendar civil days mapped to naive UTC database timestamps, including DST."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import case, func


def calendar_zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise HTTPException(400, "Invalid calendar timezone") from error


def day_start(day: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)


def calendar_bounds(start: date, end: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    if (end - start).days > 366:
        raise HTTPException(400, "Calendar range cannot exceed 367 days")
    try:
        return day_start(start, zone), day_start(end + timedelta(days=1), zone)
    except (OverflowError, ValueError) as error:
        raise HTTPException(400, "Invalid calendar range") from error


def calendar_day_expression(column, start: date, end: date, zone: ZoneInfo):
    if zone.key == "UTC":
        return func.date(column)
    # Portable SQL: aggregate in the database instead of loading every task.
    # Each civil day's half-open UTC interval handles 23/25-hour DST days.
    intervals = []
    day = start
    while day <= end:
        lower, upper = day_start(day, zone), day_start(day + timedelta(days=1), zone)
        intervals.append(((column >= lower) & (column < upper), day.isoformat()))
        day += timedelta(days=1)
    return case(*intervals, else_=None)
