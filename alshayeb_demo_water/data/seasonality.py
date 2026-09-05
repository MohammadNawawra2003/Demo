"""The demand model. Document A §11.

Seasonality here is severe and multi-peaked, and it is the single most important
characteristic of the demo data — because the **forecasting trap is the point**.

The Hijri calendar drifts about eleven days a year against the Gregorian, so
Ramadan and Hajj fall in different Gregorian months in consecutive years. Across
an eighteen-month window that means **the same month carries a different
seasonal load in consecutive years**, and any naive year-on-year comparison
produces a wrong answer. Odoo's reordering rules will not correct for it. That
is a legitimate, non-contrived place for AI judgement layered on top of
deterministic ERP logic, and a prospect recognises it immediately.

Pure functions, no ORM, so the model can be reasoned about and tested on its own.
"""

import datetime
import hashlib

from . import blueprint as bp

#: §11. Ramadan lifts gathering and charity consumption; retailers promote.
RAMADAN_UPLIFT = 1.35
#: §11. Pilgrimage demand, and it lands on Jeddah rather than the south.
HAJJ_UPLIFT = 1.55
#: §11. September, institutional channel.
BACK_TO_SCHOOL_UPLIFT = 1.12


def _as_date(value):
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(value)


def month_index(day):
    """The base-100 Gregorian seasonal index for a date. §11."""
    return bp.MONTHLY_INDEX[_as_date(day).month - 1] / 100.0


def in_window(day, window):
    if not window:
        return False
    start, end = (_as_date(bound) for bound in window)
    return start <= _as_date(day) <= end


def hijri_overlay(day):
    """Ramadan and Hajj, applied **by actual date, not by month**.

    Applying them by month is precisely the mistake the dataset exists to
    expose: it would smear the uplift across a Gregorian boundary and hide the
    drift.
    """
    day = _as_date(day)
    factor = 1.0
    if in_window(day, bp.RAMADAN.get(day.year)):
        factor *= RAMADAN_UPLIFT
    if in_window(day, bp.HAJJ.get(day.year)):
        factor *= HAJJ_UPLIFT
    if day.month == 9:
        factor *= BACK_TO_SCHOOL_UPLIFT
    return factor


def daily_factor(day):
    """Combined seasonal multiplier for one day."""
    return month_index(day) * hijri_overlay(day)


def daily_cartons(day, annual_cartons, run_days=350):
    """How many cartons of one SKU that day's demand implies."""
    return (annual_cartons / run_days) * daily_factor(day)


def window(anchor, months=18):
    """The 18-month history window ending at the anchor date. §14.

    Eighteen months is not arbitrary: it is the minimum that captures **two
    Ramadans and two Hajj seasons**, which is what makes the drift visible at
    all. A twelve-month window would show the seasonality and hide the trap.
    """
    anchor = _as_date(anchor)
    year = anchor.year
    month = anchor.month - months
    while month <= 0:
        month += 12
        year -= 1
    return datetime.date(year, month, 1), anchor


def days(anchor, months=18):
    start, end = window(anchor, months)
    step = datetime.timedelta(days=1)
    current = start
    while current <= end:
        yield current
        current += step


def year_on_year_error(anchor, months=18):
    """How wrong a naive year-on-year comparison is, as a fraction.

    Returned so a test can assert the trap is actually present in the data
    rather than merely intended. If this ever falls to zero, the dataset has
    stopped demonstrating the thing the Procurement Agent exists to catch.
    """
    start, end = window(anchor, months)
    this_year, last_year = {}, {}
    for day in days(anchor, months):
        bucket = this_year if day.year == end.year else last_year
        bucket.setdefault(day.month, 0.0)
        bucket[day.month] += daily_factor(day)

    shared = set(this_year) & set(last_year)
    if not shared:
        return 0.0
    errors = [
        abs(this_year[month] - last_year[month]) / last_year[month]
        for month in shared if last_year[month]
    ]
    return max(errors) if errors else 0.0


def treated_water_lot_name(day, sequence=1):
    """§8.2 lot format ``WT-{YYMMDD}-{SEQ}``, e.g. WT-260819-02."""
    return 'WT-%s-%02d' % (_as_date(day).strftime('%y%m%d'), sequence)


def finished_lot_name(line, day, sequence=1):
    """§8.2 lot format ``NQ-{LINE}-{YYMMDD}-{SEQ}``."""
    return 'NQ-%s-%s-%03d' % (line, _as_date(day).strftime('%y%m%d'), sequence)


def checksum(rows):
    """A stable digest over a declared field set. Document A §16.

    Reproducibility is asserted over **business values**, never over a dump. A
    database is never byte-for-byte reproducible — ``create_date``, ids and
    Postgres page layout all vary per run — and version 1.0's "byte for byte"
    wording set an acceptance criterion that cannot be met.
    """
    digest = hashlib.sha256()
    for row in rows:
        digest.update(('|'.join(str(value) for value in row) + '\n').encode())
    return digest.hexdigest()
