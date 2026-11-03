"""Class-based callable API. Callers supply trusted identities, groups and dates."""
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .choices import DateKind, OwnerKind, VersionStatus
from .entry_mapping import EntryMapper, validate_entry_owner
from .models import (CalendarEntry, CalendarMilestone, CalendarTemplate, EntryDependency,
                     EventCalendar, Milestone, TemplateDependency, TemplateEntry, TemplateVersion)
from .roles import task_owner_roles as _task_owner_roles
from .roles import access_groups
from .template_graph import validate_template_graph

API_VERSION = 1
__all__ = [
    'API_VERSION', 'Actor', 'OwnerDirectory', 'EntrySpec',
    'DiaryAPI', 'DiaryInstance', 'DiaryTemplate', 'DiaryTemplateVersion',
]


@dataclass(frozen=True)
class Actor:
    """Store the trusted caller reference, current group names, and permitted diary keys.
    The host must construct this identity from authenticated data for each request.
    """
    reference: str
    groups: frozenset[str]
    calendar_keys: frozenset[UUID] = field(default_factory=frozenset)


class OwnerDirectory(Protocol):
    """Define caller-provided eligibility checks for opaque person references.
    Role ownership uses Django groups directly.
    """

    def person_in_groups(self, reference: str, group_names: frozenset[str]) -> bool:
        """Return whether the person reference belongs to any supplied group name."""
        ...


@dataclass(frozen=True)
class EntrySpec:
    """Describe entry identity, text, date rules, and ownership for an addition.
    Keep entry_key unchanged when repeating the same addition.
    EntryMapper handles database conversion and comparison.
    """
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
    """Return whether the configured V1 roles permit an internal action.
    Managers inherit user actions, and unknown actions receive no grant.
    """
    groups = DiaryAPI.permission_groups()

    # An empty caller reference must not receive role permissions.
    if not actor.reference.strip():
        return False

    # Managers inherit the basic diary capabilities available to users.
    if action in {'use', 'view'}:
        return bool(actor.groups & {groups['manager'], groups['user']})

    # Template access and privileged writes require the manager role in V1.
    if action in {'edit', 'view_template'}:
        return groups['manager'] in actor.groups
    return False


def _require(actor, action):
    """Raise PermissionDenied when the actor lacks the role required by the action."""

    # Each operation must enforce the current configured role permissions.
    if not _allowed(actor, action):

        # Privileged operations need an error that identifies the manager requirement.
        if action in {'edit', 'view_template'}:
            raise PermissionDenied('DiaryManager membership is required for this operation.')
        raise PermissionDenied('DiaryUser or DiaryManager membership is required for this operation.')


def _require_template_access(actor):
    """Require DiaryManager access before looking up template information."""
    _require(actor, 'view_template')


def _calendar(actor, key, action='view'):
    """Return the calendar identified by key after role and host-scope checks.
    Raise PermissionDenied for an unauthorized action or a key outside the actor scope.
    """
    _require(actor, action)
    key = UUID(str(key))

    # Role membership must not expand the diary scope granted by the host.
    if key not in actor.calendar_keys:
        raise PermissionDenied('This calendar is outside the caller scope.')
    return EventCalendar.objects.get(pk=key)


def _open_calendar(actor, key, action):
    """Return an authorized calendar with a database lock for a write operation.
    Raise ValidationError when the instance is closed.
    The caller must hold a database transaction.
    """
    calendar = _calendar(actor, key, action)
    calendar = EventCalendar.objects.select_for_update().get(pk=calendar.pk)

    # The locked closure state prevents writes after another caller closes the diary.
    if calendar.closed_at is not None:
        raise ValidationError('This diary is closed.')
    return calendar


def _template_version(key=None, name=None):
    """Resolve a version key or the latest approved version of a template name.
    Use DIARY_TEMPLATE_NAME only when no explicit selector is supplied.
    Raise ValidationError for conflicting selectors or an unavailable approved version.
    """

    # An explicit version key selects a fixed version rather than the latest approved version.
    if key is not None:

        # Conflicting selectors must not silently select a different template.
        if name is not None:
            raise ValidationError('Select a template by version key or name, not both.')
        return TemplateVersion.objects.get(pk=key)

    # Use the optional configured default only when the caller omitted the name.
    if name is None:
        name = getattr(settings, 'DIARY_TEMPLATE_NAME', '')

    # Without a usable selector, creation must not choose an arbitrary template.
    if not isinstance(name, str) or not name.strip():
        raise ValidationError('Supply a template name or version key, or set the optional DIARY_TEMPLATE_NAME default.')
    version = TemplateVersion.objects.filter(template__name__iexact=name.strip(),
                                             status=VersionStatus.APPROVED).order_by('-number').first()

    # Creation cannot substitute an unapproved draft when no approved version exists.
    if version is None:
        raise ValidationError('The selected template has no approved version.')
    return version


def _set_dates(calendar, dates):
    """Save supplied milestone dates without changing unspecified values.
    Raise ValidationError for values other than a plain date or None.
    """
    for name, value in dates.items():

        # Accept missing dates but reject timestamps and other values before saving.
        if value is not None and type(value) is not date:
            raise ValidationError('Milestone values must be dates or None.')
        milestone = Milestone.objects.get(name=name)
        CalendarMilestone.objects.update_or_create(calendar=calendar, milestone=milestone, defaults={'date': value})


def _scope(actor, scope_key, template, action):
    """Return the authorized scope, entry model, dependency model, and scope field.
    Write access to a diary also locks it and requires an open instance.
    """

    # Template and diary dependencies use separate models and permission checks.
    if template:

        # Read access and write access use their corresponding template permission checks.
        _require(actor, 'view_template' if action == 'view' else 'edit')
        scope = TemplateVersion.objects.get(pk=scope_key)
        return scope, TemplateEntry, TemplateDependency, 'version'

    # Diary writes need a lock and closure check, while reads preserve access to closed diaries.
    calendar = _calendar(actor, scope_key) if action == 'view' else _open_calendar(actor, scope_key, action)
    return calendar, CalendarEntry, EntryDependency, 'calendar'


@dataclass(frozen=True, kw_only=True)
class _BoundObject:
    """Store an immutable actor context and normalized UUID without caching a Django model instance."""
    key: UUID
    actor: Actor = field(repr=False)

    def __post_init__(self):
        """Normalize the supplied key to a UUID.
        Raise ValueError when the key does not represent a UUID.
        """
        object.__setattr__(self, 'key', UUID(str(self.key)))


class _DependencyAPI(_BoundObject):
    """Share dependency traversal and replacement within diary or template-version scopes."""
    _template_scope = False

    def available_predecessors(self, *, entry_key):
        """Return same-scope predecessor choices excluding this task and all its successors.
        Each result contains the entry key and display name.
        """
        actor, scope_key, template = self.actor, self.key, self._template_scope
        scope, model, links, field_name = _scope(actor, scope_key, template, 'view')
        entry = model.objects.get(**{field_name: scope, 'entry_key': entry_key})
        successors = {}
        for item, predecessor in links.objects.filter(**{f'entry__{field_name}': scope}).values_list('entry_id',
                                                                                                     'predecessor_id'):
            successors.setdefault(predecessor, set()).add(item)
        excluded, pending = set(), [entry.pk]

        # Traverse successors until every task that would close a cycle has been excluded.
        while pending:
            item = pending.pop()

            # Visit each reachable task once, including when multiple dependency paths reach it.
            if item not in excluded:
                excluded.add(item)
                pending.extend(successors.get(item, ()))
        return tuple(model.objects.filter(**{field_name: scope}).exclude(pk__in=excluded)
                     .order_by('name').values('entry_key', 'name'))

    @transaction.atomic
    def set_predecessors(self, *, entry_key, predecessor_keys):
        """Replace the task predecessor links within a locked scope.
        Require a draft when the scope is a template version.
        Reject invalid links and roll back the replacement on failure.
        """
        actor, scope_key, template = self.actor, self.key, self._template_scope
        scope, model, links, field_name = _scope(actor, scope_key, template, 'edit')
        scope = type(scope).objects.select_for_update().get(pk=scope.pk)

        # Approved template versions must keep their saved dependency graph unchanged.
        if template and scope.status != VersionStatus.DRAFT:
            raise ValidationError('Create a draft version before changing its dependencies.')
        entry = model.objects.get(**{field_name: scope, 'entry_key': entry_key})
        keys = {UUID(str(key)) for key in predecessor_keys}
        predecessors = list(model.objects.filter(**{field_name: scope, 'entry_key__in': keys}))

        # Reject unknown or cross-scope predecessors before replacing any existing links.
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
        """Return configured task ownership role names as a frozenset."""
        return _task_owner_roles()

    @transaction.atomic
    def define_milestones(self, *, definitions):
        """Define stable milestone names and return their UUIDs by name.
        Update changed labels without replacing existing milestone identities.
        """
        actor = self.actor
        _require(actor, 'edit')
        result = {}
        for name, label in definitions.items():
            milestone, created = Milestone.objects.get_or_create(name=name, defaults={'label': label})

            # A repeated definition can update its display label without replacing the stable milestone identity.
            if not created and milestone.label != label:
                milestone.label = label
                milestone.save()
            result[name] = milestone.pk
        return result

    def create_template(self, *, name=None, description=''):
        """Create a named template for this actor and return its API reference.
        Use the optional configured name only when name is omitted.
        """
        return DiaryTemplate.create(actor=self.actor, name=name, description=description)

    def templates(self):
        """Return template names and keys for the manager's chooser without creating records."""
        _require_template_access(self.actor)
        return tuple(CalendarTemplate.objects.order_by('name').values('id', 'name', 'description'))

    def template(self, *, key=None, name=None):
        """Return a template reference selected by key or name.
        Raise ValidationError when both selectors are supplied.
        """

        # A supplied key identifies the exact template requested by the caller.
        if key is not None:

            # A name and key together could describe different templates.
            if name is not None:
                raise ValidationError('Select a template by key or name, not both.')
            return DiaryTemplate.from_key(actor=self.actor, key=key)
        return DiaryTemplate.from_name(actor=self.actor, name=name)

    def template_version(self, *, key=None, name=None):
        """Return a selected version reference for this actor.
        A name selects its latest approved version, while an omitted selector uses the optional default.
        Raise ValidationError for conflicting selectors.
        """

        # A supplied name selects its latest approved version without requiring a default setting.
        if name is not None:

            # Reject ambiguous selection before either lookup occurs.
            if key is not None:
                raise ValidationError('Select a template by version key or name, not both.')
            return DiaryTemplateVersion.from_name(actor=self.actor, name=name)

        # An omitted selector explicitly requests the optional default template.
        if key is None:
            return DiaryTemplateVersion.from_default(actor=self.actor)
        return DiaryTemplateVersion.from_key(actor=self.actor, key=key)

    def create_diary(self, *, event_ref, name, event_year, milestone_dates, template_version_key=None,
                     template_name=None):
        """Create a diary using this actor and return its API reference.
        Select a template by name, version key, or the optional default.
        Do not expand the actor calendar scope.
        """
        return DiaryInstance.create(
            actor=self.actor, event_ref=event_ref, name=name, event_year=event_year,
            milestone_dates=milestone_dates, template_version_key=template_version_key, template_name=template_name,
        )

    def diary(self, *, key):
        """Return a diary reference after checking the key against this actor role and calendar scope."""
        return DiaryInstance.from_key(actor=self.actor, key=key)


class DiaryTemplate(_BoundObject):
    """A template reference. Each operation reads current database state."""

    def editor_data(self):
        """Return template metadata and the highest numbered version, including a draft.
        Return an empty entry sequence when the template has no version.
        """
        _require_template_access(self.actor)
        template = CalendarTemplate.objects.get(pk=self.key)
        version = template.versions.order_by('-number').first()
        result = {'key': template.pk, 'name': template.name, 'description': template.description,
                  'version_key': None, 'number': 0, 'status': '', 'entries': ()}

        # Empty templates must open for editing without creating a draft during a read.
        if version is not None:
            data = DiaryTemplateVersion(actor=self.actor, key=version.pk).read()
            result.update(version_key=data['key'], number=data['number'], status=data['status'],
                          entries=data['entries'])
        return result

    @transaction.atomic
    def save_version(self, *, entries, predecessors, expected_version_key, description=None,
                     milestone_definitions=None, directory=None):
        """Save and approve a complete new version after checking its predecessor graph.
        Preserve supplied entry keys and existing diaries. Lock the template against concurrent saves.
        Reject a stale expected_version_key with ValidationError. None expects an unversioned template.
        Define new milestones from name-to-label values without changing existing milestone labels.
        """
        _require(self.actor, 'edit')
        template = CalendarTemplate.objects.select_for_update().get(pk=self.key)
        latest = template.versions.order_by('-number').first()

        # Compare the editor's base version under the lock to prevent lost changes.
        current_key = latest.pk if latest is not None else None

        # Normalize UUID strings while preserving None for a template without versions.
        expected = UUID(str(expected_version_key)) if expected_version_key is not None else None

        # A newer save requires the manager to reopen the editor and review those changes.
        if current_key != expected:
            raise ValidationError('This template changed. Reopen it before saving your changes.')
        specs = tuple(entries)
        graph = validate_template_graph((spec.entry_key for spec in specs), predecessors)
        for name, label in (milestone_definitions or {}).items():
            Milestone.objects.get_or_create(name=name, defaults={'label': label})

        # A new version follows the highest existing number, including any draft.
        number = latest.number + 1 if latest is not None else 1
        version = self.create_version(number=number)
        for spec in specs:
            version.add_entry(spec=spec, directory=directory)
        for key, values in graph.items():
            version.set_predecessors(entry_key=key, predecessor_keys=values)

        # Omitted descriptions preserve template metadata for callable API users.
        if description is not None:
            template.description = description
            template.save()
        return version.approve()

    @classmethod
    def from_key(cls, *, actor, key):
        """Return a reference to the template key after checking manager access.
        Raise CalendarTemplate.DoesNotExist when the template is absent.
        """
        _require_template_access(actor)
        template = CalendarTemplate.objects.get(pk=key)
        return cls(actor=actor, key=template.pk)

    @classmethod
    def from_name(cls, *, actor, name=None):
        """Return a template reference by name after checking manager access.
        Use the optional default when name is omitted.
        Raise ValidationError when no usable name is available.
        """
        _require_template_access(actor)

        # The optional default is a convenience only when no explicit name was supplied.
        if name is None:
            name = getattr(settings, 'DIARY_TEMPLATE_NAME', '')

        # A missing default must produce a useful error instead of an unspecified lookup.
        if not isinstance(name, str) or not name.strip():
            raise ValidationError('Supply a template name or configure DIARY_TEMPLATE_NAME.')
        template = CalendarTemplate.objects.get(name__iexact=name.strip())
        return cls(actor=actor, key=template.pk)

    @classmethod
    def create(cls, *, actor, name=None, description=''):
        """Create a template and return its reference for the supplied actor.
        Require manager access and an explicit name or optional configured default.
        """
        _require(actor, 'edit')

        # Explicit caller names take precedence over the optional configured default.
        if name is None:
            name = getattr(settings, 'DIARY_TEMPLATE_NAME', '')

        # A new template must have a usable name even when the default setting is absent.
        if not isinstance(name, str) or not name.strip():
            raise ValidationError('Supply a template name or configure DIARY_TEMPLATE_NAME.')
        template = CalendarTemplate.objects.create(name=name, description=description)
        return cls(actor=actor, key=template.pk)

    def create_version(self, *, number):
        """Create a numbered draft for this template and return its version reference."""
        return DiaryTemplateVersion.create(actor=self.actor, template_key=self.key, number=number)

    def version(self, *, number):
        """Return this template version by number after checking manager access."""
        _require_template_access(self.actor)
        version = TemplateVersion.objects.get(template_id=self.key, number=number)
        return DiaryTemplateVersion(actor=self.actor, key=version.pk)

    def latest_version(self, *, approved_only=False):
        """Return the highest numbered version for this template.
        Restrict selection to approved versions when approved_only is true.
        Raise ValidationError when no version matches.
        """
        _require_template_access(self.actor)
        versions = TemplateVersion.objects.filter(template_id=self.key)

        # Creation needs approved versions, while an editor can also inspect the latest draft.
        if approved_only:
            versions = versions.filter(status=VersionStatus.APPROVED)
        version = versions.order_by('-number').first()

        # Do not substitute another template when this selection has no matching version.
        if version is None:
            raise ValidationError('The template has no matching version.')
        return DiaryTemplateVersion(actor=self.actor, key=version.pk)


class DiaryTemplateVersion(_DependencyAPI):
    """A version reference with template entry and dependency operations."""

    _template_scope = True

    @classmethod
    def from_key(cls, *, actor, key):
        """Return the version reference for key after checking manager access."""
        _require_template_access(actor)
        version = TemplateVersion.objects.get(pk=key)
        return cls(actor=actor, key=version.pk)

    @classmethod
    def from_default(cls, *, actor):
        """Return the latest approved version of the optional default template for the supplied actor.
        Raise ValidationError when the default or its approved version is unavailable.
        """
        _require_template_access(actor)
        return cls(actor=actor, key=_template_version().pk)

    @classmethod
    def from_name(cls, *, actor, name):
        """Return the latest approved version of the named template after checking manager access."""
        _require_template_access(actor)
        return cls(actor=actor, key=_template_version(name=name).pk)

    @classmethod
    def create(cls, *, actor, template_key, number):
        """Create a numbered draft version and return its reference.
        Record the supplied actor as its creator.
        """
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
        """Add an entry to this version and return its stable entry UUID.
        Reuse an identical existing entry and reject conflicting content for the same key.
        Validate ownership while the version is locked.
        """
        actor, template_version_key = self.actor, self.key
        _require(actor, 'edit')
        TemplateVersion.objects.select_for_update().get(pk=template_version_key)
        validate_entry_owner(spec, directory)
        existing = TemplateEntry.objects.filter(version_id=template_version_key, entry_key=spec.entry_key).first()

        # A repeated entry key must reuse its original template entry.
        if existing:

            # The same key must not silently overwrite different template content.
            if not EntryMapper.matches_spec(existing, spec):
                raise ValidationError('The entry key already identifies a different entry.')
            return existing.entry_key
        return TemplateEntry.objects.create(version_id=template_version_key,
                                            **EntryMapper.to_model_fields(spec)).entry_key

    @transaction.atomic
    def approve(self):
        """Approve this version and return the same API reference.
        Repeated calls preserve the original approval time and actor.
        """
        actor, template_version_key = self.actor, self.key
        _require(actor, 'edit')
        version = TemplateVersion.objects.select_for_update().get(pk=template_version_key)

        # Repeated approval preserves the original actor and approval time.
        if version.status != VersionStatus.APPROVED:
            version.status = VersionStatus.APPROVED
            version.approved_at = timezone.now()
            version.approved_by_ref = actor.reference
            version.save()
        return self

    def read(self):
        """Return current version metadata, entry rules, and predecessor keys after checking manager access."""
        actor, template_version_key = self.actor, self.key
        _require(actor, 'view_template')
        version = _template_version(template_version_key)

        # Only milestone-based rules have a milestone name to include in the result.
        return {'key': version.pk, 'template_key': version.template_id, 'number': version.number,
                'status': version.status,
                'entries': tuple({**EntryMapper.snapshot_fields(entry),
                                  'milestone_name': entry.milestone.name if entry.milestone_id else None,
                                  'predecessors': tuple(entry.predecessors.values_list('entry_key', flat=True))}
                                 for entry in version.entries.select_related('milestone'))}


class DiaryInstance(_DependencyAPI):
    """An instance reference without cached database or authorization results."""

    @classmethod
    def from_key(cls, *, actor, key):
        """Return a diary reference after role, host-scope, and existence checks.
        Each later operation still checks its own required permission.
        """
        actions = ('view', 'use', 'edit')

        # Bind references only through an action currently permitted to this actor.
        action = next((name for name in actions if _allowed(actor, name)), None)

        # Reference lookup must not grant access when the actor has no diary role.
        if action is None:
            raise PermissionDenied('Diary access permission required.')
        calendar = _calendar(actor, key, action)
        return cls(actor=actor, key=calendar.pk)

    @classmethod
    @transaction.atomic
    def create(cls, *, actor, event_ref, name, event_year, milestone_dates, template_version_key=None,
               template_name=None):
        """Create a diary reference with a stable key from an approved template.
        Copy its rules, owners, and dependencies in one transaction.
        Repeated identical inputs reuse the existing diary, while conflicting inputs raise ValidationError.
        """
        _require(actor, 'use')
        selected = _template_version(key=template_version_key, name=template_name)
        version = TemplateVersion.objects.select_for_update().get(pk=selected.pk)

        # All versions of one template share this lock for repeated calendar creation.
        CalendarTemplate.objects.select_for_update().get(pk=version.template_id)
        existing = EventCalendar.objects.filter(event_ref=event_ref.strip()).first()

        # The host reference makes repeated creation safe without copying entries again.
        if existing:
            dates = existing.date_context()

            # Different inputs for the same reference require an explicit change rather than another creation.
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
                                                             created_by_ref=actor.reference,
                                                             **EntryMapper.snapshot_fields(source))
        for link in TemplateDependency.objects.filter(entry__version=version):
            EntryDependency.objects.create(entry=copied[link.entry_id], predecessor=copied[link.predecessor_id])
        return cls(actor=actor, key=calendar.pk)

    @transaction.atomic
    def close(self):
        """Close this diary and return the same reference without completing or deleting tasks.
        Repeated calls preserve the original closure record.
        """
        actor, calendar_key = self.actor, self.key
        calendar = _calendar(actor, calendar_key, 'edit')
        calendar = EventCalendar.objects.select_for_update().get(pk=calendar.pk)

        # Repeated closure preserves the original closure record.
        if calendar.closed_at is None:
            calendar.closed_at = timezone.now()
            calendar.closed_by_ref = actor.reference
            calendar.save(update_fields=['closed_at', 'closed_by_ref'])
        return self

    @transaction.atomic
    def set_milestone_dates(self, *, milestone_dates, event_year=None):
        """Save supplied milestone values and the optional year for an open diary.
        Preserve unspecified milestone values.
        This existing mutation remains outside the approved V1 change workflow.
        """
        actor, calendar_key = self.actor, self.key
        calendar = _open_calendar(actor, calendar_key, 'edit')

        # An omitted year must not change the stored year used by annual date rules.
        if event_year is not None:
            calendar.event_year = event_year
            calendar.save()
        _set_dates(calendar, milestone_dates)

    @transaction.atomic
    def add_entry(self, *, spec, directory=None):
        """Add an entry to this open diary and return its stable UUID.
        Restrict ordinary users to self-owned personal entries.
        Reuse identical requests and reject conflicting content for the same key.
        """
        actor, calendar_key = self.actor, self.key
        calendar = _open_calendar(actor, calendar_key, 'use')

        # Ordinary users can add personal entries but cannot choose another owner.
        if not _allowed(actor, 'edit'):

            # Enforce self-ownership even when a caller submits a different ownership selection.
            if spec.owner_kind != OwnerKind.PERSON or spec.person_ref != actor.reference:
                raise PermissionDenied('A personal entry must belong to its creator.')

        # Managers can select another owner after the normal ownership checks.
        else:
            validate_entry_owner(spec, directory)
        existing = calendar.entries.filter(entry_key=spec.entry_key).first()

        # Repeated entry requests reuse their stable identity within this diary.
        if existing:

            # Reject conflicting content rather than changing an entry during a repeated addition.
            if not EntryMapper.matches_spec(existing, spec):
                raise ValidationError('The entry key already identifies a different entry.')
            return existing.entry_key
        return CalendarEntry.objects.create(calendar=calendar, created_by_ref=actor.reference,
                                            **EntryMapper.to_model_fields(spec)).entry_key

    def read(self):
        """Return current diary metadata, milestone values, entries, and dependency state.
        Use preserved due dates for completed tasks.
        """
        actor, calendar_key = self.actor, self.key
        calendar = _calendar(actor, calendar_key)
        context = calendar.date_context()
        entries = []
        for entry in calendar.entries.select_related('milestone').prefetch_related('predecessors'):
            predecessors = tuple(entry.predecessors.all())

            # Completed tasks retain their recorded due date when source milestones later change.
            # Completed predecessors remain in history but no longer block the task.
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
        """Return open tasks with independently calculated readiness and lateness.
        Use the configured local date when today is omitted.
        Return an empty tuple for a closed diary.
        """

        # An omitted comparison date uses the configured Diary time zone.
        if today is None:
            today = timezone.localdate(timezone=ZoneInfo(getattr(settings, 'DIARY_TIME_ZONE', 'Europe/London')))

        # Date comparisons must not accept timestamps or other incompatible values.
        if type(today) is not date:
            raise ValidationError('Supply a date for today.')
        calendar = self.read()

        # A closed diary keeps its records but contributes no active tasks.
        if calendar['closed']:
            return ()
        result = []
        for entry in calendar['entries']:

            # Completion removes a task from active work without deleting its stored entry.
            if entry['completed_at'] is not None:
                continue

            # Readiness identifies blocking predecessors independently of the separate lateness calculation.
            # Tasks due today are late, while tasks without a due date are not late.
            result.append({**entry, 'state': 'ready' if entry['ready'] else 'blocked',
                           'late': entry['date'] is not None and entry['date'] <= today,
                           'date_not_set': entry['date'] is None})
        return tuple(sorted(result, key=lambda item: (not item['late'], item['date'] or date.max,
                                                      item['name'].casefold(), str(item['entry_key']))))

    def personal_tasks(self, *, today=None, include_whole_team=False):
        """Return open tasks owned by this actor or their current roles.
        Include whole-team tasks only when include_whole_team is true.
        """
        actor = self.actor

        # Select personal and current role assignments, with whole-team work available only through the explicit option.
        return tuple(item for item in self.active_tasks(today=today)
                     if ((item['owner_kind'] == OwnerKind.PERSON and item['person_ref'] == actor.reference)
                         or (item['owner_kind'] == OwnerKind.ROLE and item['role_ref'] in actor.groups)
                         or (include_whole_team and item['owner_kind'] == OwnerKind.TEAM)))
