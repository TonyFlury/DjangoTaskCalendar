"""Resolve task dates without a caller-supplied diary year."""
from datetime import date, timedelta
from uuid import UUID

from django.core.exceptions import ValidationError

from .choices import DateKind


def task_date_order(entries):
    """Validate date references independently of completion dependencies.

    Return stable task keys in source-first order, including disconnected tasks.
    Drafts may be assembled in any order; validate the complete set on approval.
    """
    entries = tuple(entries)
    try:
        keys = [UUID(str(entry.entry_key)) for entry in entries]
        sources = {key: UUID(str(entry.source_task_key)) if entry.source_task_key is not None else None
                   for key, entry in zip(keys, entries)}
    except (TypeError, ValueError, AttributeError) as error:
        raise ValidationError('Supply valid task keys for date references.') from error
    if len(set(keys)) != len(keys):
        raise ValidationError('Each task must have a different entry key.')
    successors = {key: [] for key in keys}
    pending = []
    for key, entry in zip(keys, entries):
        source = sources[key]
        if entry.date_kind != DateKind.TASK:
            if source is not None:
                raise ValidationError('Only a task-relative date rule can select a source task.')
            pending.append(key)
        elif source not in successors or source == key:
            raise ValidationError('Select another task in this template as the date source.')
        else:
            successors[source].append(key)
    order = []
    while pending:
        key = pending.pop()
        order.append(key)
        pending.extend(successors[key])
    if len(order) != len(keys):
        raise ValidationError('Task date references create a circular date dependency.')
    return order


def task_relative_date(source_date, day_offset):
    """Calculate a signed calendar-day offset once, rejecting unresolved or overflowing dates."""
    try:
        if type(source_date) is not date or type(day_offset) is not int:
            raise ValueError
        return source_date + timedelta(days=day_offset)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValidationError('The source task needs a due date and the offset must produce a valid date.') from error


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
                 year_offset=0, day_offset=0, fixed_date=None, annual_due_date=None, task_due_date=None):
    """Return a stored date snapshot or calculate a date from a named milestone.
    Return None for an unset milestone or a date outside the supported calendar.
    """

    # One-time tasks carry their full date and need no milestone lookup.
    if kind == DateKind.ONCE:
        return fixed_date

    # Annual dates must not move when time passes or milestone values change.
    if kind == DateKind.ANNUAL:
        return annual_due_date
    if kind == DateKind.TASK:
        return task_due_date

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
