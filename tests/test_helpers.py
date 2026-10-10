from datetime import datetime

from app.main import (
    attendance_date,
    compute_half_day,
    compute_late_minutes,
    compute_overtime,
    compute_work_hours,
    parse_month,
    round_half_up,
)


def test_late_grace_is_strictly_more_than_ten_minutes():
    assert compute_late_minutes(datetime(2026, 1, 5, 4, 10, 0), "09:30", "2026-01-05") == 0
    assert compute_late_minutes(datetime(2026, 1, 5, 4, 10, 1), "09:30", "2026-01-05") == 10
    assert compute_late_minutes(datetime(2026, 1, 5, 4, 45, 59), "09:30", "2026-01-05") == 45


def test_work_hours_round_half_up_then_half_day_uses_rounded_value():
    start = datetime(2026, 1, 5, 4, 0, 0)
    assert compute_work_hours(start, datetime(2026, 1, 5, 8, 29, 0)) == 4.48
    assert compute_work_hours(start, datetime(2026, 1, 5, 8, 29, 59)) == 4.50
    assert compute_half_day(4.49) is True
    assert compute_half_day(4.50) is False


def test_overtime_has_thirty_minute_threshold():
    # 18:59:59 IST is 29m59s beyond an 18:30 shift end.
    assert compute_overtime(datetime(2026, 1, 5, 13, 29, 59), "18:30", "2026-01-05", "09:30") == 0
    assert compute_overtime(datetime(2026, 1, 5, 13, 30, 0), "18:30", "2026-01-05", "09:30") == 30


def test_overnight_shift_assigns_after_midnight_to_previous_day():
    # 02:00 IST on Jan 6 = 20:30 UTC on Jan 5.
    punch = datetime(2026, 1, 5, 20, 30, 0)
    assert attendance_date(punch, "22:00", "06:00") == "2026-01-05"


def test_month_validation_and_half_up_rounding():
    assert parse_month("2026-02")[1].isoformat() == "2026-02-28"
    assert round_half_up(1.005, 2) == 1.01


def test_all_required_routes_are_registered():
    from app.main import app
    routes = {(method, route.path) for route in app.routes for method in (getattr(route, "methods", None) or set())}
    required = {
        ("GET", "/health"),
        ("POST", "/employees"),
        ("GET", "/employees"),
        ("POST", "/attendance/punch-in"),
        ("POST", "/attendance/punch-out"),
        ("GET", "/attendance"),
        ("PATCH", "/attendance/{emp_code}/{date}"),
        ("GET", "/analytics/employees/{emp_code}/monthly"),
        ("GET", "/analytics/departments/summary"),
        ("GET", "/analytics/leaderboard/late"),
        ("GET", "/analytics/departments/{department}/trend"),
        ("GET", "/admin/explain/{endpoint}"),
    }
    assert required <= routes
