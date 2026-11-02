"""Version 1 callable boundary. Callers supply trusted identities, groups and dates."""
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .choices import DateKind, OwnerKind, VersionStatus
from .models import (CalendarEntry, CalendarMilestone, CalendarTemplate, EntryDependency,
                     EventCalendar, Milestone, TemplateDependency, TemplateEntry, TemplateVersion)

API_VERSION = 1
__all__ = [
    'API_VERSION', 'Actor', 'OwnerDirectory', 'EntrySpec', 'permission_groups',
    'define_milestones', 'required_milestones', 'create_template', 'create_template_version',
    'get_template_version', 'add_template_entry', 'approve_template_version',
    'create_calendar', 'set_milestone_dates', 'add_entry', 'get_calendar',
    'active_tasks', 'personal_tasks', 'available_predecessors', 'set_predecessors',
]


@dataclass(frozen=True)
class Actor:
    reference: str
    groups: frozenset[str]
    calendar_keys: frozenset[UUID] = field(default_factory=frozenset)


class OwnerDirectory(Protocol):
    def person_in_groups(self, reference: str, group_names: frozenset[str]) -> bool: ...
    def role_exists(self, reference: str) -> bool: ...


@dataclass(frozen=True)
class EntrySpec:
    name: str
    date_kind: str
    description: str = ''
    milestone_name: str = ''
    month: int | None = None
    day: int | None = None
    year_offset: int = 0
    day_offset: int = 0
    fixed_date: date | None = None
    owner_kind: str = OwnerKind.TEAM
    person_ref: str = ''
    role_ref: str = ''
    entry_key: UUID = field(default_factory=uuid4)


def permission_groups():
    """Return a copy of the configured groups; missing actions deny access."""
    configured = getattr(settings, 'DIARY_PERMISSION_GROUPS', {})
    result = {}
    for action, groups in configured.items():
        if not isinstance(groups, (list, tuple, set, frozenset)) or any(not isinstance(g, str) for g in groups):
            raise ValidationError('Diary permission groups must be collections of group names.')
        result[action] = frozenset(groups)
    return result


def _allowed(actor, action):
    return bool(actor.reference.strip() and actor.groups & permission_groups().get(action, frozenset()))


def _require(actor, action):
    if not _allowed(actor, action):
        raise PermissionDenied(f'Diary permission required: {action}.')


def _calendar(actor, key, action='view'):
    _require(actor, action)
    key = UUID(str(key))
    if key not in actor.calendar_keys:
        raise PermissionDenied('This calendar is outside the caller scope.')
    return EventCalendar.objects.get(pk=key)


def _owner(spec, directory):
    if spec.owner_kind == OwnerKind.TEAM:
        return
    if directory is None:
        raise ValidationError('Supply an owner directory for a person or role assignment.')
    if spec.owner_kind == OwnerKind.PERSON:
        if not directory.person_in_groups(spec.person_ref, permission_groups().get('use', frozenset())):
            raise ValidationError('Select a person with Diary use access.')
    elif spec.owner_kind == OwnerKind.ROLE:
        if not directory.role_exists(spec.role_ref):
            raise ValidationError('Select an existing role.')


def _values(spec):
    values = asdict(spec)
    name = values.pop('milestone_name')
    values['milestone'] = Milestone.objects.get(name=name) if name else None
    return values


def _copy_values(source):
    fields = ('entry_key', 'name', 'description', 'date_kind', 'milestone_id', 'month', 'day',
              'year_offset', 'day_offset', 'fixed_date', 'owner_kind', 'person_ref', 'role_ref')
    return {name: getattr(source, name) for name in fields}


@transaction.atomic
def define_milestones(*, actor, definitions):
    """Define named milestones from {name: label}; return their reference keys."""
    _require(actor, 'edit')
    result = {}
    for name, label in definitions.items():
        milestone, created = Milestone.objects.get_or_create(name=name, defaults={'label': label})
        if not created and milestone.label != label:
            milestone.label = label
            milestone.save()
        result[name] = milestone.pk
    return result


def _template_version(key=None):
    if key is not None:
        return TemplateVersion.objects.get(pk=key)
    name = getattr(settings, 'DIARY_TEMPLATE_NAME', '')
    if not isinstance(name, str) or not name.strip():
        raise ValidationError('Configure DIARY_TEMPLATE_NAME before selecting a template.')
    version = TemplateVersion.objects.filter(template__name__iexact=name.strip(), status=VersionStatus.APPROVED).order_by('-number').first()
    if version is None:
        raise ValidationError('The configured template has no approved version.')
    return version


def required_milestones(*, actor, template_version_key=None):
    """Enumerate distinct milestone definitions used by this version only."""
    _require(actor, 'view_template')
    version = _template_version(template_version_key)
    return tuple(Milestone.objects.filter(pk__in=version.entries.values('milestone_id'))
                 .order_by('name').values('id', 'name', 'label').distinct())


def create_template(*, actor, name=None, description=''):
    _require(actor, 'edit')
    if name is None:
        name = getattr(settings, 'DIARY_TEMPLATE_NAME', '')
    if not isinstance(name, str) or not name.strip():
        raise ValidationError('Supply a template name or configure DIARY_TEMPLATE_NAME.')
    return CalendarTemplate.objects.create(name=name, description=description).pk


def create_template_version(*, actor, template_key, number):
    _require(actor, 'edit')
    return TemplateVersion.objects.create(template_id=template_key, number=number, created_by_ref=actor.reference).pk


@transaction.atomic
def add_template_entry(*, actor, template_version_key, spec, directory=None):
    _require(actor, 'edit')
    TemplateVersion.objects.select_for_update().get(pk=template_version_key)
    _owner(spec, directory)
    values = _values(spec)
    existing = TemplateEntry.objects.filter(version_id=template_version_key, entry_key=spec.entry_key).first()
    if existing:
        if _copy_values(existing) != values_without_milestone(values):
            raise ValidationError('The entry key already identifies a different entry.')
        return existing.entry_key
    return TemplateEntry.objects.create(version_id=template_version_key, **values).entry_key


def values_without_milestone(values):
    result = dict(values)
    milestone = result.pop('milestone')
    result['milestone_id'] = milestone.pk if milestone else None
    return result


@transaction.atomic
def approve_template_version(*, actor, template_version_key):
    _require(actor, 'edit')
    version = TemplateVersion.objects.select_for_update().get(pk=template_version_key)
    if version.status != VersionStatus.APPROVED:
        version.status = VersionStatus.APPROVED
        version.approved_at = timezone.now()
        version.approved_by_ref = actor.reference
        version.save()
    return version.pk


@transaction.atomic
def create_calendar(*, actor, event_ref, name, event_year, milestone_dates, template_version_key=None):
    """Return the stable calendar key. Repeat calls with the same inputs are safe."""
    _require(actor, 'use')
    selected = _template_version(template_version_key)
    version = TemplateVersion.objects.select_for_update().get(pk=selected.pk)
    # All versions of one template share this lock for repeated calendar creation.
    CalendarTemplate.objects.select_for_update().get(pk=version.template_id)
    existing = EventCalendar.objects.filter(event_ref=event_ref.strip()).first()
    if existing:
        dates = existing.date_context()
        if (existing.template_version_id != version.pk or existing.event_year != event_year
                or existing.name != name.strip() or dates != milestone_dates):
            raise ValidationError('This event reference already has a calendar with different inputs.')
        return existing.pk
    calendar = EventCalendar.objects.create(template_version=version, event_ref=event_ref, name=name,
                                            event_year=event_year, created_by_ref=actor.reference)
    _set_dates(calendar, milestone_dates)
    copied = {}
    for source in version.entries.all():
        copied[source.pk] = CalendarEntry.objects.create(calendar=calendar, source_entry=source,
                                                        created_by_ref=actor.reference, **_copy_values(source))
    for link in TemplateDependency.objects.filter(entry__version=version):
        EntryDependency.objects.create(entry=copied[link.entry_id], predecessor=copied[link.predecessor_id])
    return calendar.pk


def _set_dates(calendar, dates):
    for name, value in dates.items():
        if value is not None and type(value) is not date:
            raise ValidationError('Milestone values must be dates or None.')
        milestone = Milestone.objects.get(name=name)
        CalendarMilestone.objects.update_or_create(calendar=calendar, milestone=milestone, defaults={'date': value})


@transaction.atomic
def set_milestone_dates(*, actor, calendar_key, milestone_dates, event_year=None):
    calendar = _calendar(actor, calendar_key, 'edit')
    calendar = EventCalendar.objects.select_for_update().get(pk=calendar.pk)
    if event_year is not None:
        calendar.event_year = event_year
        calendar.save()
    _set_dates(calendar, milestone_dates)


@transaction.atomic
def add_entry(*, actor, calendar_key, spec, directory=None):
    calendar = _calendar(actor, calendar_key, 'use')
    EventCalendar.objects.select_for_update().get(pk=calendar.pk)
    if not _allowed(actor, 'edit'):
        if spec.owner_kind != OwnerKind.PERSON or spec.person_ref != actor.reference:
            raise PermissionDenied('A personal entry must belong to its creator.')
    else:
        _owner(spec, directory)
    values = _values(spec)
    existing = calendar.entries.filter(entry_key=spec.entry_key).first()
    if existing:
        if _copy_values(existing) != values_without_milestone(values):
            raise ValidationError('The entry key already identifies a different entry.')
        return existing.entry_key
    return CalendarEntry.objects.create(calendar=calendar, created_by_ref=actor.reference, **values).entry_key


def _scope(actor, scope_key, template, action):
    if template:
        _require(actor, 'view_template' if action == 'view' else 'edit')
        scope = TemplateVersion.objects.get(pk=scope_key)
        return scope, TemplateEntry, TemplateDependency, 'version'
    return _calendar(actor, scope_key, action), CalendarEntry, EntryDependency, 'calendar'


def available_predecessors(*, actor, scope_key, entry_key, template=False):
    scope, model, links, field_name = _scope(actor, scope_key, template, 'view')
    entry = model.objects.get(**{field_name: scope, 'entry_key': entry_key})
    successors = {}
    for item, predecessor in links.objects.filter(**{f'entry__{field_name}': scope}).values_list('entry_id', 'predecessor_id'):
        successors.setdefault(predecessor, set()).add(item)
    excluded, pending = set(), [entry.pk]
    while pending:
        item = pending.pop()
        if item not in excluded:
            excluded.add(item)
            pending.extend(successors.get(item, ()))
    return tuple(model.objects.filter(**{field_name: scope}).exclude(pk__in=excluded)
                 .order_by('name').values('entry_key', 'name'))


@transaction.atomic
def set_predecessors(*, actor, scope_key, entry_key, predecessor_keys, template=False):
    scope, model, links, field_name = _scope(actor, scope_key, template, 'edit')
    scope = type(scope).objects.select_for_update().get(pk=scope.pk)
    if template and scope.status != VersionStatus.DRAFT:
        raise ValidationError('Create a draft version before changing its dependencies.')
    entry = model.objects.get(**{field_name: scope, 'entry_key': entry_key})
    keys = {UUID(str(key)) for key in predecessor_keys}
    predecessors = list(model.objects.filter(**{field_name: scope, 'entry_key__in': keys}))
    if len(predecessors) != len(keys):
        raise ValidationError('All predecessors must belong to this scope.')
    links.objects.filter(entry=entry).delete()
    for predecessor in predecessors:
        links.objects.create(entry=entry, predecessor=predecessor)


def get_calendar(*, actor, calendar_key):
    calendar = _calendar(actor, calendar_key)
    context = calendar.date_context()
    entries = []
    for entry in calendar.entries.select_related('milestone').prefetch_related('predecessors'):
        predecessors = tuple(entry.predecessors.all())
        entries.append({'entry_key': entry.entry_key, 'name': entry.name, 'description': entry.description,
                        'date': (entry.completed_due_date if entry.completed_at is not None else
                                 entry.resolve_date(event_year=calendar.event_year, source_dates=context)),
                        'owner_kind': entry.owner_kind, 'person_ref': entry.person_ref, 'role_ref': entry.role_ref,
                        'predecessors': tuple(item.entry_key for item in predecessors),
                        'blocking_predecessors': tuple(item.entry_key for item in predecessors if item.completed_at is None),
                        'completed_at': entry.completed_at,
                        'ready': entry.completed_at is None and all(item.completed_at is not None for item in predecessors)})
    return {'key': calendar.pk, 'name': calendar.name, 'event_ref': calendar.event_ref,
            'event_year': calendar.event_year, 'milestones': context, 'entries': tuple(entries)}


def active_tasks(*, actor, calendar_key, today=None):
    """Return open tasks with readiness and lateness as independent values."""
    if today is None:
        today = timezone.localdate(timezone=ZoneInfo(getattr(settings, 'DIARY_TIME_ZONE', 'Europe/London')))
    if type(today) is not date:
        raise ValidationError('Supply a date for today.')
    calendar = get_calendar(actor=actor, calendar_key=calendar_key)
    result = []
    for entry in calendar['entries']:
        if entry['completed_at'] is not None:
            continue
        result.append({**entry, 'state': 'ready' if entry['ready'] else 'blocked',
                       'late': entry['date'] is not None and entry['date'] <= today,
                       'date_not_set': entry['date'] is None})
    return tuple(sorted(result, key=lambda item: (not item['late'], item['date'] or date.max,
                                                item['name'].casefold(), str(item['entry_key']))))


def personal_tasks(*, actor, calendar_key, today=None, include_whole_team=False):
    """Select tasks owned by this person or a role in their supplied membership."""
    return tuple(item for item in active_tasks(actor=actor, calendar_key=calendar_key, today=today)
                 if ((item['owner_kind'] == OwnerKind.PERSON and item['person_ref'] == actor.reference)
                     or (item['owner_kind'] == OwnerKind.ROLE and item['role_ref'] in actor.groups)
                     or (include_whole_team and item['owner_kind'] == OwnerKind.TEAM)))


def get_template_version(*, actor, template_version_key=None):
    _require(actor, 'view_template')
    version = _template_version(template_version_key)
    return {'key': version.pk, 'template_key': version.template_id, 'number': version.number,
            'status': version.status,
            'entries': tuple({**_copy_values(entry),
                              'milestone_name': entry.milestone.name if entry.milestone_id else None,
                              'predecessors': tuple(entry.predecessors.values_list('entry_key', flat=True))}
                             for entry in version.entries.select_related('milestone'))}
