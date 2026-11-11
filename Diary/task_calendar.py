"""DFUT-018: Date-only period selection shared by calendars and their JSON interface."""
import calendar
from collections import defaultdict
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError

from .choices import OwnerKind
from .models import EventCalendar
from .ownership import orphaned_entry_keys


def shifted_month(day, offset):
    """Move by calendar months, clamping the day rather than overflowing February."""
    index = day.year * 12 + day.month - 1 + offset
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _setting(name, default, maximum):
    """Validate preview/page limits before allocating response slices."""
    value = getattr(settings, name, default)
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValidationError(f'{name} must be between 1 and {maximum}.')
    return value


def _page(rows, number, size):
    """Count the complete selection while returning only one bounded page."""
    pages = max(1, (len(rows) + size - 1) // size)
    number = min(number, pages)
    return {'count': len(rows), 'page': number, 'pages': pages,
            'previous': number - 1 if number > 1 else None,
            'next': number + 1 if number < pages else None,
            'tasks': tuple(rows[(number - 1) * size:number * size])}


def task_period(api, *, view, anchor_date, diary_key, mode, include_completed, show_blocked,
                include_whole_team, query, owner, selected_day, page, late_page, undated_page,
                period, today, directory, task_status='all', only_late=False):
    """Select visible tasks before counting or slicing; date bounds are half-open."""
    from .api import _comparison_date, _require
    _require(api.actor, 'edit' if mode == 'manager' else 'view')
    if mode not in {'personal', 'manager'} or view not in {'list', 'day', 'week', 'month'}:
        raise ValidationError('Select a valid calendar view and mode.')
    if period not in {None, 'day', 'week', 'month'}:
        raise ValidationError('Select a valid calendar period.')
    if task_status not in {'all', 'late', 'ready', 'blocked'}:
        raise ValidationError('Select a valid task status.')
    for flag in (include_completed, show_blocked, include_whole_team, only_late):
        if type(flag) is not bool:
            raise ValidationError('Calendar filter flags must be booleans.')
    for number in (page, late_page, undated_page):
        if type(number) is not int or not 1 <= number <= 1000000:
            raise ValidationError('Supply a positive calendar page number.')
    if not isinstance(query, str) or len(query) > 160 or not isinstance(owner, str) or len(owner) > 200:
        raise ValidationError('Supply valid calendar search and owner filters.')
    if owner and mode != 'manager':
        raise ValidationError('Owner filtering requires manager mode.')
    today = _comparison_date(today)
    anchor = today if anchor_date is None else _comparison_date(anchor_date)
    selected = anchor if selected_day is None else _comparison_date(selected_day)
    period = view if view != 'list' else period or 'week'
    weekday = getattr(settings, 'DIARY_WEEK_START', 0)
    if type(weekday) is not int or not 0 <= weekday <= 6:
        raise ValidationError('DIARY_WEEK_START must be between 0 and 6.')
    try:
        first = anchor if period in {'day', 'week'} else anchor.replace(day=1)
        start = first if period == 'day' else first - timedelta(days=(first.weekday() - weekday) % 7)
        if period == 'day':
            end = start + timedelta(days=1)
            primary_start, primary_end = start, end
            previous, following = anchor - timedelta(days=1), anchor + timedelta(days=1)
        elif period == 'week':
            end = start + timedelta(days=7)
            primary_start, primary_end = start, end
            previous, following = anchor - timedelta(days=7), anchor + timedelta(days=7)
        else:
            primary_start, primary_end = first, shifted_month(first, 1)
            end = primary_end + timedelta(days=(weekday - primary_end.weekday()) % 7)
            previous, following = shifted_month(anchor, -1), shifted_month(anchor, 1)
    except (ValueError, OverflowError):
        raise ValidationError('Choose a calendar date away from the supported year boundaries.')
    if not start <= selected < end:
        raise ValidationError('The selected day must be in the displayed period.')
    preview_size = _setting('DIARY_CALENDAR_WEEK_PREVIEW' if period == 'week' else 'DIARY_CALENDAR_MONTH_PREVIEW',
                            5 if period == 'week' else 3, 50)
    page_size = _setting('DIARY_CALENDAR_PAGE_SIZE', 25, 100)
    # Validate an explicit diary even when it is closed or has no matching tasks.
    if diary_key is not None:
        instances = (api.diary(key=diary_key),)
    elif mode == 'manager':
        raise ValidationError('Select one permitted diary for manager mode.')
    else:
        keys = EventCalendar.objects.filter(pk__in=api.actor.calendar_keys, closed_at__isnull=True).values_list('pk', flat=True)
        instances = tuple(api.diary(key=key) for key in keys)
    rows, selected_diary, owners = [], None, {}
    for instance in instances:
        data, tasks = instance._calendar_tasks(today=today)
        if diary_key is not None:
            selected_diary = {'key': data['key'], 'name': data['name'], 'closed': data['closed']}
        if data['closed'] and mode == 'personal':
            continue
        orphaned = orphaned_entry_keys(tasks, directory=directory) if mode == 'manager' else frozenset()
        for task in tasks:
            owner_value = ('person:' + task['person_ref'] if task['owner_kind'] == OwnerKind.PERSON
                           else 'role:' + task['role_ref'] if task['owner_kind'] == OwnerKind.ROLE else 'team')
            if mode == 'manager':
                owners[owner_value] = {'value': owner_value, 'kind': task['owner_kind'],
                                       'reference': task['person_ref'] or task['role_ref']}
            if not include_completed and task['completed_at'] is not None:
                continue
            if not show_blocked and task['state'] == 'blocked':
                continue
            if only_late and not task['late']:
                continue
            if task_status != 'all' and ('late' if task['late'] else task['state']) != task_status:
                continue
            if mode == 'personal' and not (
                task['owner_kind'] == OwnerKind.PERSON and task['person_ref'] == api.actor.reference
                or task['owner_kind'] == OwnerKind.ROLE and task['role_ref'] in api.actor.groups
                or include_whole_team and task['owner_kind'] == OwnerKind.TEAM):
                continue
            if query.strip().casefold() not in (task['name'] + '\n' + task['description']).casefold():
                continue
            if owner and owner != owner_value:
                continue
            rows.append({**task, 'orphaned': task['entry_key'] in orphaned,
                         'status_label': task['state'].capitalize(),
                         'date_label': 'Due today' if task['late'] and task['date'] == today else 'Late' if task['late'] else ''})
    rows.sort(key=lambda row: (not row['orphaned'], row['completed_at'] is not None,
                              row['name'].casefold(), str(row['diary_key']), str(row['entry_key'])))
    buckets = defaultdict(list)
    late, undated = [], []
    for row in rows:
        due = row['date']
        if due is None:
            if row['completed_at'] is None:
                undated.append(row)
        elif start <= due < end:
            buckets[due].append(row)
        elif row['late']:
            late.append(row)
    late.sort(key=lambda row: (not row['orphaned'], row['date'], row['name'].casefold(), str(row['diary_key']), str(row['entry_key'])))
    days = []
    current = start
    while current < end:
        tasks = buckets[current]
        days.append({'date': current, 'today': current == today, 'selected': current == selected,
                     'outside_month': period == 'month' and current.month != anchor.month,
                     'count': len(tasks), 'tasks': tuple(tasks[:preview_size]),
                     'more': max(0, len(tasks) - preview_size)})
        current += timedelta(days=1)
    return {'view': view, 'period': period, 'anchor_date': anchor, 'selected_day': selected,
            'start': start, 'end': end, 'primary_start': primary_start, 'primary_end': primary_end,
            'today': today, 'time_zone': str(ZoneInfo(getattr(settings, 'DIARY_TIME_ZONE', settings.TIME_ZONE))),
            'weekdays': tuple(calendar.day_name[(weekday + index) % 7] for index in range(7)),
            'previous_date': previous, 'next_date': following, 'diary': selected_diary, 'mode': mode,
            'owners': tuple(owners[value] for value in sorted(owners)),
            'days': tuple(days), 'count': sum(day['count'] for day in days),
            'day': {'date': selected, **_page(buckets[selected], page, page_size)},
            'late': _page(late, late_page, page_size), 'undated': _page(undated, undated_page, page_size)}
