"""Class-based callable API. Callers supply trusted identities, groups and dates."""
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
from .roles import task_owner_roles as _task_owner_roles
from .roles import access_groups

API_VERSION = 1
__all__ = [
    'API_VERSION', 'Actor', 'OwnerDirectory', 'EntrySpec',
    'DiaryAPI', 'DiaryInstance', 'DiaryTemplate', 'DiaryTemplateVersion',
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


def _allowed(actor, action):
    groups = DiaryAPI.permission_groups()
    if not actor.reference.strip():
        return False
    if action in {'use', 'view'}:
        return bool(actor.groups & {groups['manager'], groups['user']})
    if action in {'edit', 'view_template'}:
        return groups['manager'] in actor.groups
    return False


def _require(actor, action):
    if not _allowed(actor, action):
        if action in {'edit', 'view_template'}:
            raise PermissionDenied('DiaryManager membership is required for this operation.')
        raise PermissionDenied('DiaryUser or DiaryManager membership is required for this operation.')


def _require_template_access(actor):
    _require(actor, 'view_template')


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
        if not directory.person_in_groups(spec.person_ref, frozenset(DiaryAPI.permission_groups().values())):
            raise ValidationError('Select a DiaryUser or DiaryManager.')
    elif spec.owner_kind == OwnerKind.ROLE:
        if spec.role_ref not in DiaryAPI.task_owner_roles():
            raise ValidationError('Select a role from DIARY_TASK_OWNER_ROLES.')
        if not directory.role_exists(spec.role_ref):
            raise ValidationError('Select an existing role.')


def _open_calendar(actor, key, action):
    calendar = _calendar(actor, key, action)
    calendar = EventCalendar.objects.select_for_update().get(pk=calendar.pk)
    if calendar.closed_at is not None:
        raise ValidationError('This diary is closed.')
    return calendar


def _values(spec):
    values = asdict(spec)
    name = values.pop('milestone_name')
    values['milestone'] = Milestone.objects.get(name=name) if name else None
    return values


def _copy_values(source):
    fields = ('entry_key', 'name', 'description', 'date_kind', 'milestone_id', 'month', 'day',
              'year_offset', 'day_offset', 'fixed_date', 'owner_kind', 'person_ref', 'role_ref')
    return {name: getattr(source, name) for name in fields}


def _template_version(key=None):
    if key is not None:
        return TemplateVersion.objects.get(pk=key)
    name = getattr(settings, 'DIARY_TEMPLATE_NAME', '')
    if not isinstance(name, str) or not name.strip():
        raise ValidationError('Configure DIARY_TEMPLATE_NAME before selecting a template.')
    version = TemplateVersion.objects.filter(template__name__iexact=name.strip(),
                                             status=VersionStatus.APPROVED).order_by('-number').first()
    if version is None:
        raise ValidationError('The configured template has no approved version.')
    return version


def _values_without_milestone(values):
    result = dict(values)
    milestone = result.pop('milestone')
    result['milestone_id'] = milestone.pk if milestone else None
    return result


def _set_dates(calendar, dates):
    for name, value in dates.items():
        if value is not None and type(value) is not date:
            raise ValidationError('Milestone values must be dates or None.')
        milestone = Milestone.objects.get(name=name)
        CalendarMilestone.objects.update_or_create(calendar=calendar, milestone=milestone, defaults={'date': value})


def _scope(actor, scope_key, template, action):
    if template:
        _require(actor, 'view_template' if action == 'view' else 'edit')
        scope = TemplateVersion.objects.get(pk=scope_key)
        return scope, TemplateEntry, TemplateDependency, 'version'
    calendar = _calendar(actor, scope_key) if action == 'view' else _open_calendar(actor, scope_key, action)
    return calendar, CalendarEntry, EntryDependency, 'calendar'


@dataclass(frozen=True, kw_only=True)
class _BoundObject:
    key: UUID
    actor: Actor = field(repr=False)

    def __post_init__(self):
        object.__setattr__(self, 'key', UUID(str(self.key)))


class _DependencyAPI(_BoundObject):
    _template_scope = False

    def available_predecessors(self, *, entry_key):
        actor, scope_key, template = self.actor, self.key, self._template_scope
        scope, model, links, field_name = _scope(actor, scope_key, template, 'view')
        entry = model.objects.get(**{field_name: scope, 'entry_key': entry_key})
        successors = {}
        for item, predecessor in links.objects.filter(**{f'entry__{field_name}': scope}).values_list('entry_id',
                                                                                                     'predecessor_id'):
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
    def set_predecessors(self, *, entry_key, predecessor_keys):
        actor, scope_key, template = self.actor, self.key, self._template_scope
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


@dataclass(frozen=True, kw_only=True)
class DiaryAPI:
    """Caller context and factories for Diary objects."""

    actor: Actor = field(repr=False)

    @staticmethod
    def permission_groups():
        """Return the V1 manager and user group names."""
        return access_groups()

    @staticmethod
    def task_owner_roles():
        return _task_owner_roles()

    @transaction.atomic
    def define_milestones(self, *, definitions):
        """Define named milestones from {name: label}; return their reference keys."""
        actor = self.actor
        _require(actor, 'edit')
        result = {}
        for name, label in definitions.items():
            milestone, created = Milestone.objects.get_or_create(name=name, defaults={'label': label})
            if not created and milestone.label != label:
                milestone.label = label
                milestone.save()
            result[name] = milestone.pk
        return result

    def create_template(self, *, name=None, description=''):
        return DiaryTemplate.create(actor=self.actor, name=name, description=description)

    def template(self, *, key=None, name=None):
        if key is not None:
            if name is not None:
                raise ValidationError('Select a template by key or name, not both.')
            return DiaryTemplate.from_key(actor=self.actor, key=key)
        return DiaryTemplate.from_name(actor=self.actor, name=name)

    def template_version(self, *, key=None):
        if key is None:
            return DiaryTemplateVersion.from_default(actor=self.actor)
        return DiaryTemplateVersion.from_key(actor=self.actor, key=key)

    def create_diary(self, *, event_ref, name, event_year, milestone_dates, template_version_key=None):
        return DiaryInstance.create(
            actor=self.actor, event_ref=event_ref, name=name, event_year=event_year,
            milestone_dates=milestone_dates, template_version_key=template_version_key,
        )

    def diary(self, *, key):
        return DiaryInstance.from_key(actor=self.actor, key=key)


class DiaryTemplate(_BoundObject):
    """A template reference. Each operation reads current database state."""

    @classmethod
    def from_key(cls, *, actor, key):
        _require_template_access(actor)
        template = CalendarTemplate.objects.get(pk=key)
        return cls(actor=actor, key=template.pk)

    @classmethod
    def from_name(cls, *, actor, name=None):
        _require_template_access(actor)
        if name is None:
            name = getattr(settings, 'DIARY_TEMPLATE_NAME', '')
        if not isinstance(name, str) or not name.strip():
            raise ValidationError('Supply a template name or configure DIARY_TEMPLATE_NAME.')
        template = CalendarTemplate.objects.get(name__iexact=name.strip())
        return cls(actor=actor, key=template.pk)

    @classmethod
    def create(cls, *, actor, name=None, description=''):
        _require(actor, 'edit')
        if name is None:
            name = getattr(settings, 'DIARY_TEMPLATE_NAME', '')
        if not isinstance(name, str) or not name.strip():
            raise ValidationError('Supply a template name or configure DIARY_TEMPLATE_NAME.')
        template = CalendarTemplate.objects.create(name=name, description=description)
        return cls(actor=actor, key=template.pk)

    def create_version(self, *, number):
        return DiaryTemplateVersion.create(actor=self.actor, template_key=self.key, number=number)

    def version(self, *, number):
        _require_template_access(self.actor)
        version = TemplateVersion.objects.get(template_id=self.key, number=number)
        return DiaryTemplateVersion(actor=self.actor, key=version.pk)

    def latest_version(self, *, approved_only=False):
        _require_template_access(self.actor)
        versions = TemplateVersion.objects.filter(template_id=self.key)
        if approved_only:
            versions = versions.filter(status=VersionStatus.APPROVED)
        version = versions.order_by('-number').first()
        if version is None:
            raise ValidationError('The template has no matching version.')
        return DiaryTemplateVersion(actor=self.actor, key=version.pk)


class DiaryTemplateVersion(_DependencyAPI):
    """A version reference with template entry and dependency operations."""

    _template_scope = True

    @classmethod
    def from_key(cls, *, actor, key):
        _require_template_access(actor)
        version = TemplateVersion.objects.get(pk=key)
        return cls(actor=actor, key=version.pk)

    @classmethod
    def from_default(cls, *, actor):
        _require_template_access(actor)
        return cls(actor=actor, key=_template_version().pk)

    @classmethod
    def create(cls, *, actor, template_key, number):
        _require(actor, 'edit')
        version = TemplateVersion.objects.create(template_id=template_key, number=number,
                                                 created_by_ref=actor.reference)
        return cls(actor=actor, key=version.pk)

    def required_milestones(self):
        """Enumerate distinct milestone definitions used by this version only."""
        actor, template_version_key = self.actor, self.key
        _require(actor, 'view_template')
        version = _template_version(template_version_key)
        return tuple(Milestone.objects.filter(pk__in=version.entries.values('milestone_id'))
                     .order_by('name').values('id', 'name', 'label').distinct())

    @transaction.atomic
    def add_entry(self, *, spec, directory=None):
        actor, template_version_key = self.actor, self.key
        _require(actor, 'edit')
        TemplateVersion.objects.select_for_update().get(pk=template_version_key)
        _owner(spec, directory)
        values = _values(spec)
        existing = TemplateEntry.objects.filter(version_id=template_version_key, entry_key=spec.entry_key).first()
        if existing:
            if _copy_values(existing) != _values_without_milestone(values):
                raise ValidationError('The entry key already identifies a different entry.')
            return existing.entry_key
        return TemplateEntry.objects.create(version_id=template_version_key, **values).entry_key

    @transaction.atomic
    def approve(self):
        actor, template_version_key = self.actor, self.key
        _require(actor, 'edit')
        version = TemplateVersion.objects.select_for_update().get(pk=template_version_key)
        if version.status != VersionStatus.APPROVED:
            version.status = VersionStatus.APPROVED
            version.approved_at = timezone.now()
            version.approved_by_ref = actor.reference
            version.save()
        return self

    def read(self):
        actor, template_version_key = self.actor, self.key
        _require(actor, 'view_template')
        version = _template_version(template_version_key)
        return {'key': version.pk, 'template_key': version.template_id, 'number': version.number,
                'status': version.status,
                'entries': tuple({**_copy_values(entry),
                                  'milestone_name': entry.milestone.name if entry.milestone_id else None,
                                  'predecessors': tuple(entry.predecessors.values_list('entry_key', flat=True))}
                                 for entry in version.entries.select_related('milestone'))}


class DiaryInstance(_DependencyAPI):
    """An instance reference without cached database or authorization results."""

    @classmethod
    def from_key(cls, *, actor, key):
        actions = ('view', 'use', 'edit')
        action = next((name for name in actions if _allowed(actor, name)), None)
        if action is None:
            raise PermissionDenied('Diary access permission required.')
        calendar = _calendar(actor, key, action)
        return cls(actor=actor, key=calendar.pk)

    @classmethod
    @transaction.atomic
    def create(cls, *, actor, event_ref, name, event_year, milestone_dates, template_version_key=None):
        """Create a diary reference with a stable key. Repeat calls with the same inputs are safe."""
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
            return cls(actor=actor, key=existing.pk)
        calendar = EventCalendar.objects.create(template_version=version, event_ref=event_ref, name=name,
                                                event_year=event_year, created_by_ref=actor.reference)
        _set_dates(calendar, milestone_dates)
        copied = {}
        for source in version.entries.all():
            copied[source.pk] = CalendarEntry.objects.create(calendar=calendar, source_entry=source,
                                                             created_by_ref=actor.reference, **_copy_values(source))
        for link in TemplateDependency.objects.filter(entry__version=version):
            EntryDependency.objects.create(entry=copied[link.entry_id], predecessor=copied[link.predecessor_id])
        return cls(actor=actor, key=calendar.pk)

    @transaction.atomic
    def close(self):
        """Close an instance without completing or deleting any of its tasks."""
        actor, calendar_key = self.actor, self.key
        calendar = _calendar(actor, calendar_key, 'edit')
        calendar = EventCalendar.objects.select_for_update().get(pk=calendar.pk)
        if calendar.closed_at is None:
            calendar.closed_at = timezone.now()
            calendar.closed_by_ref = actor.reference
            calendar.save(update_fields=['closed_at', 'closed_by_ref'])
        return self

    @transaction.atomic
    def set_milestone_dates(self, *, milestone_dates, event_year=None):
        actor, calendar_key = self.actor, self.key
        calendar = _open_calendar(actor, calendar_key, 'edit')
        if event_year is not None:
            calendar.event_year = event_year
            calendar.save()
        _set_dates(calendar, milestone_dates)

    @transaction.atomic
    def add_entry(self, *, spec, directory=None):
        actor, calendar_key = self.actor, self.key
        calendar = _open_calendar(actor, calendar_key, 'use')
        if not _allowed(actor, 'edit'):
            if spec.owner_kind != OwnerKind.PERSON or spec.person_ref != actor.reference:
                raise PermissionDenied('A personal entry must belong to its creator.')
        else:
            _owner(spec, directory)
        values = _values(spec)
        existing = calendar.entries.filter(entry_key=spec.entry_key).first()
        if existing:
            if _copy_values(existing) != _values_without_milestone(values):
                raise ValidationError('The entry key already identifies a different entry.')
            return existing.entry_key
        return CalendarEntry.objects.create(calendar=calendar, created_by_ref=actor.reference, **values).entry_key

    def read(self):
        actor, calendar_key = self.actor, self.key
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
                            'blocking_predecessors': tuple(
                                item.entry_key for item in predecessors if item.completed_at is None),
                            'completed_at': entry.completed_at,
                            'ready': entry.completed_at is None and all(
                                item.completed_at is not None for item in predecessors)})
        return {'key': calendar.pk, 'name': calendar.name, 'event_ref': calendar.event_ref,
                'closed': calendar.closed_at is not None, 'closed_at': calendar.closed_at,
                'closed_by_ref': calendar.closed_by_ref,
                'event_year': calendar.event_year, 'milestones': context, 'entries': tuple(entries)}

    def active_tasks(self, *, today=None):
        """Return open tasks with readiness and lateness as independent values."""
        if today is None:
            today = timezone.localdate(timezone=ZoneInfo(getattr(settings, 'DIARY_TIME_ZONE', 'Europe/London')))
        if type(today) is not date:
            raise ValidationError('Supply a date for today.')
        calendar = self.read()
        if calendar['closed']:
            return ()
        result = []
        for entry in calendar['entries']:
            if entry['completed_at'] is not None:
                continue
            result.append({**entry, 'state': 'ready' if entry['ready'] else 'blocked',
                           'late': entry['date'] is not None and entry['date'] <= today,
                           'date_not_set': entry['date'] is None})
        return tuple(sorted(result, key=lambda item: (not item['late'], item['date'] or date.max,
                                                      item['name'].casefold(), str(item['entry_key']))))

    def personal_tasks(self, *, today=None, include_whole_team=False):
        """Select tasks owned by this person or a role in their supplied membership."""
        actor = self.actor
        return tuple(item for item in self.active_tasks(today=today)
                     if ((item['owner_kind'] == OwnerKind.PERSON and item['person_ref'] == actor.reference)
                         or (item['owner_kind'] == OwnerKind.ROLE and item['role_ref'] in actor.groups)
                         or (include_whole_team and item['owner_kind'] == OwnerKind.TEAM)))
