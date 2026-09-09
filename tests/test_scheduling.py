from datetime import datetime

from scheduling import matches_schedule_day, schedule_datetime


def test_matches_configured_weekday():
    wednesday = datetime(2026, 9, 9, 10, 0)

    assert matches_schedule_day(wednesday, "wed,sun") is True
    assert matches_schedule_day(wednesday, "mon,fri") is False


def test_schedule_datetime_replaces_only_time():
    now = datetime(2026, 9, 9, 10, 23, 45, 100)

    assert schedule_datetime(now, 15, 30) == datetime(2026, 9, 9, 15, 30)
