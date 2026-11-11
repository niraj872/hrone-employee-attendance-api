"""Pure date/time and attendance calculation helpers."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import calendar
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from fastapi import HTTPException

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc

def now_utc_naive() -> datetime:
    return datetime.now(UTC).replace(microsecond=0, tzinfo=None)


def from_epoch_ms(ms: Optional[int]) -> datetime:
    """Epoch milliseconds -> UTC-naive BSON datetime, truncated to seconds."""
    if ms is None:
        return now_utc_naive()
    return datetime.fromtimestamp(ms / 1000, tz=UTC).replace(microsecond=0, tzinfo=None)


def as_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(UTC).replace(microsecond=0, tzinfo=None)


def ist_dt(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(IST)


def attendance_date(punch_in: datetime, shift_start: str, shift_end: str) -> str:
    local = ist_dt(punch_in)
    if shift_end <= shift_start and local.time().replace(tzinfo=None) < time.fromisoformat(shift_end):
        local -= timedelta(days=1)
    return local.date().isoformat()


def shift_instant(day: str, hhmm: str, overnight_end: bool = False, shift_start: Optional[str] = None) -> datetime:
    d = date.fromisoformat(day)
    if overnight_end and shift_start and hhmm <= shift_start:
        d += timedelta(days=1)
    return datetime.combine(d, time.fromisoformat(hhmm), tzinfo=IST).astimezone(UTC).replace(microsecond=0, tzinfo=None)


def compute_late_minutes(punch_in: Optional[datetime], shift_start: str, day: str) -> int:
    if punch_in is None:
        return 0
    seconds = int((punch_in - shift_instant(day, shift_start)).total_seconds())
    return seconds // 60 if seconds > 600 else 0


def compute_work_hours(punch_in: Optional[datetime], punch_out: Optional[datetime]) -> Optional[float]:
    if punch_in is None or punch_out is None:
        return None
    hours = Decimal(str((punch_out - punch_in).total_seconds())) / Decimal(3600)
    return float(hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_overtime(
    punch_out: Optional[datetime],
    shift_end: str,
    day: str,
    shift_start: str,
    punch_in: Optional[datetime] = None,
) -> int:
    if punch_out is None:
        return 0
    end = shift_instant(day, shift_end, True, shift_start)
    overtime_start = end if punch_in is None else max(punch_in, end)
    minutes = int((punch_out - overtime_start).total_seconds() // 60)
    return minutes if minutes >= 30 else 0


def compute_half_day(hours: Optional[float]) -> bool:
    return hours is not None and hours < 4.5


def round_half_up(value: Any, places: int = 2) -> float:
    quantum = Decimal("1") if places == 0 else Decimal("1." + "0" * places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def parse_month(month: str) -> tuple[date, date]:
    try:
        if len(month) != 7 or month[4] != "-":
            raise ValueError
        first = date.fromisoformat(month + "-01")
    except ValueError:
        raise HTTPException(422, "month must be YYYY-MM")
    last = date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])
    return first, last


def month_bounds(month: str) -> tuple[str, str]:
    first, last = parse_month(month)
    return first.isoformat(), last.isoformat()


def is_weekday(d: date) -> bool:
    return d.weekday() < 5


def date_match(start: str, end: str) -> dict:
    return {"date": {"$gte": start, "$lte": end}}


def validate_iso_day(value: str, field: str) -> str:
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
    except ValueError:
        raise HTTPException(422, f"{field} must be YYYY-MM-DD")
    return value


