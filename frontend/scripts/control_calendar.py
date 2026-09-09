"""Bounded NYSE calendar, verified from NYSE hours-calendars on 2026-09-08.

https://www.nyse.com/trade/hours-calendars . Unscheduled closures require updates.
Outside the explicitly verified years, fail closed rather than guessing weekdays.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TORONTO = ZoneInfo('America/Toronto')
HOLIDAYS = {
    2026: '01-01 01-19 02-16 04-03 05-25 06-19 07-03 09-07 11-26 12-25'.split(),
    2027: '01-01 01-18 02-15 03-26 05-31 06-18 07-05 09-06 11-25 12-24'.split(),
    2028: '01-17 02-21 04-14 05-29 06-19 07-04 09-04 11-23 12-25'.split(),
}
EARLY = {'2026-11-27', '2026-12-24', '2027-11-26', '2028-07-03', '2028-11-24'}


def is_session(day: date) -> bool:
    if day.year not in HOLIDAYS:
        raise ValueError('NYSE calendar coverage is 2026–2028; update required')
    return day.weekday() < 5 and day.strftime('%m-%d') not in HOLIDAYS[day.year]


def latest_completed(now: datetime) -> date:
    local = now.astimezone(TORONTO)
    day = local.date()
    for _ in range(10):
        close = time(13 if day.isoformat() in EARLY else 16)
        if is_session(day) and datetime.combine(day, close, TORONTO) <= local:
            return day
        day -= timedelta(days=1)
    raise ValueError('No completed trading session in verified calendar')


def next_morning(now: datetime) -> datetime:
    local = now.astimezone(TORONTO)
    target = datetime.combine(local.date(), time(8), TORONTO)
    return target if target > local else datetime.combine(local.date() + timedelta(days=1), time(8), TORONTO)
