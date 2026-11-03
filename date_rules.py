from datetime import date, timedelta

from .choices import DateKind


# DV1-003: Date calculation.
def resolve_date(*, kind, event_year, source_dates, source='', month=None, day=None,
                 year_offset=0, day_offset=0, fixed_date=None):
    """Calculate a date from data supplied by the caller, without app imports."""
    if kind == DateKind.ONCE:
        return fixed_date
    if kind == DateKind.ANNUAL:
        if event_year is None or month is None or day is None:
            return None
        try:
            return date(event_year + year_offset, month, day)
        except ValueError:
            return None
    if kind not in {DateKind.SOURCE, DateKind.RELATIVE}:
        raise ValueError('Unknown date rule type.')
    source_date = source_dates.get(source)
    if source_date is None:
        return None
    if kind == DateKind.SOURCE:
        return source_date
    try:
        return source_date + timedelta(days=day_offset)
    except OverflowError:
        return None
