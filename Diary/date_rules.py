"""Resolve task dates without a caller-supplied diary year."""
from datetime import date, timedelta

from .choices import DateKind


# DV1-051: Fixed dates use the next matching date after diary creation.
def next_annual_date(*, creation_date, month, day, year_offset=0):
    """Return the next matching month and day, then apply the year offset.
    Skip invalid leap days when finding the next occurrence.
    Return None for an invalid rule or a result outside the supported calendar.
    """
    try:
        date(2000, month, day)

        # Leap days can be eight years apart across a century without a leap day.
        for year in range(creation_date.year, min(creation_date.year + 9, 10000)):
            try:
                candidate = date(year, month, day)
            except ValueError:

                # February 29 must use the next year that has a leap day.
                continue

            # A matching date today must use a later occurrence.
            if candidate > creation_date:
                return date(candidate.year + year_offset, month, day)
    except (ValueError, TypeError, OverflowError):
        return None
    return None


# DV1-003: Date calculation.
# DV1-051: Annual dates retain the occurrence saved during creation.
def resolve_date(*, kind, source_dates, source='', month=None, day=None,
                 year_offset=0, day_offset=0, fixed_date=None, annual_due_date=None):
    """Return a stored fixed date or calculate a date from a named milestone.
    Return None for an unset milestone or a date outside the supported calendar.
    """

    # One-time tasks carry their full date and need no milestone lookup.
    if kind == DateKind.ONCE:
        return fixed_date

    # Annual dates must not move when time passes or milestone values change.
    if kind == DateKind.ANNUAL:
        return annual_due_date

    # Reject unknown rules rather than silently assigning an unrelated date.
    if kind not in {DateKind.SOURCE, DateKind.RELATIVE}:
        raise ValueError('Unknown date rule type.')
    source_date = source_dates.get(source)

    # Missing milestone values must not acquire an implicit date.
    if source_date is None:
        return None

    # A source rule uses the complete milestone date unchanged.
    if kind == DateKind.SOURCE:
        return source_date
    try:
        return source_date + timedelta(days=day_offset)
    except (ValueError, TypeError, OverflowError):
        return None
