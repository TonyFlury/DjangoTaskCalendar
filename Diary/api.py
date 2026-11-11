"""Class-based callable API. Callers supply trusted identities, groups and dates."""
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .choices import DateKind, OwnerKind, VersionStatus
from .entry_mapping import EntryMapper, validate_entry_owner
from .models import (CalendarEntry, CalendarMilestone, CalendarTemplate, EntryDependency,
                     EventCalendar, Milestone, TemplateDependency, TemplateEntry, TemplateVersion, TemplateMilestone, TaskNote)
from .roles import task_owner_roles as _task_owner_roles
from .roles import access_groups
from .roles import validate_task_owner_roles as _validate_task_owner_roles
from .template_graph import validate_template_graph, ordered_task_choices
from .ownership import orphaned_entry_keys
from .identity import user_display_name
from .date_rules import task_date_order
from .signals import (_queue_task_event, task_created, task_note_added, task_dependency_changed,
                      task_closed, task_ownership_changed)

API_VERSION = 1
__all__ = [
    'API_VERSION', 'Actor', 'OwnerDirectory', 'EntrySpec',
    'DiaryAPI', 'DiaryInstance', 'DiaryTemplate', 'DiaryTemplateVersion',
]


# DV1-046: Class-based callable API and factories.
@dataclass(frozen=True)
class Actor:
    """Store the trusted caller reference, current group names, and permitted diary keys.
    The host must construct this identity from authenticated data for each request.
    Supply email for signal attribution; non-UI callers may leave it empty.
    """
    reference: str
    groups: frozenset[str]
    calendar_keys: frozenset[UUID] = field(default_factory=frozenset)
    email: str = ''


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
    source_task_key: UUID | None = None


# DV1-047: Simple V1 access settings.
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


# DV1-047: Simple V1 access settings.
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


# DV1-008: Close a diary instance.
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


# DV1-031, DV1-038: Personal entries and completion references remain private to permitted readers.
def _visible_entries(actor, entries):
    """Remove private tasks and private predecessor references from serialized entries.
    Preserve readiness calculated from the complete dependency graph.
    """

    # Managers can inspect every task within their host-authorized diary scope.
    if _allowed(actor, 'edit'):
        return tuple(entries)

    # Diary additions with person ownership are private to that person.
    visible = tuple(entry for entry in entries if entry['source'] == 'template'
                    or entry['owner_kind'] != OwnerKind.PERSON or entry['person_ref'] == actor.reference)
    keys = {entry['entry_key'] for entry in visible}

    # Related keys and completion comments must not disclose private predecessors or private completion targets.
    return tuple({**entry,
                  'completion_target_key': entry.get('completion_target_key')
                  if entry.get('completion_target_key') in keys else None,
                  'completion_comment': entry.get('completion_comment', '')
                  if entry.get('completion_target_key') is None or entry.get('completion_target_key') in keys
                  else 'Close all completed this predecessor for an inaccessible task.',
                  'predecessors': tuple(key for key in entry['predecessors'] if key in keys),
                  'blocking_predecessors': tuple(key for key in entry['blocking_predecessors'] if key in keys)}
                 for entry in visible)


# DV1-031: Search only results that have already passed the task visibility checks.
def _search_entries(entries, query):
    """Return visible entries whose names or descriptions contain the supplied text.
    Ignore case and surrounding spaces. Raise ValidationError for invalid or excessive input.
    """

    # A bounded text value prevents accidental broad searches from invalid caller inputs.
    if not isinstance(query, str) or len(query) > 256:
        raise ValidationError('Supply search text with at most 256 characters.')
    term = query.strip().casefold()

    # Match visible names and descriptions, or return all visible entries when search text is empty.
    return tuple(entry for entry in entries
                 if not term or term in entry['name'].casefold() or term in entry.get('description', '').casefold())


# DV1-020, DV1-050: Use one comparison date across all selected diaries.
def _comparison_date(today):
    """Return an explicit date or today's date in the configured Diary time zone.
    Raise ValidationError for timestamps and other incompatible values.
    """

    # The active user time zone must not replace the project or Diary setting.
    if today is None:
        today = timezone.localdate(timezone=ZoneInfo(getattr(settings, 'DIARY_TIME_ZONE', settings.TIME_ZONE)))

    # Lateness compares calendar dates rather than timestamps.
    if type(today) is not date:
        raise ValidationError('Supply a date for today.')
    return today


# DV1-048: Standard Django groups and optional template default.
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


def _creation_template(*, key=None, name=None, without_template=False):
    if type(without_template) is not bool:
        raise ValidationError('Supply a boolean without_template option.')
    if without_template:
        if key is not None or name is not None:
            raise ValidationError('Do not select a template with without_template=True.')
        return None
    if key is None and name is None and not getattr(settings, 'DIARY_TEMPLATE_NAME', None):
        return None
    return _template_version(key=key, name=name)


def _validate_milestone_dates(version, dates):
    if not isinstance(dates, dict) or any(not isinstance(name, str) for name in dates):
        raise ValidationError('Supply milestone dates by name.')
    required = set(version.milestones.values_list('name', flat=True)) if version else set()
    missing = required - dates.keys()
    if missing:
        raise ValidationError('Missing required milestone dates: ' + ', '.join(sorted(missing)) + '.')
    selected = {name: dates[name] for name in required}
    if any(type(value) is not date for value in selected.values()):
        raise ValidationError('Every required milestone value must be a date.')
    return selected


def _copy_template(calendar, version, actor):
    """Add template tasks only; keep every existing task field and record intact."""
    names = {name.casefold() for name in calendar.entries.values_list('name', flat=True)}
    keys = set(calendar.entries.values_list('entry_key', flat=True))
    copied = {}
    sources = list(version.entries.all())
    by_key = {source.entry_key: source for source in sources}
    fields_by_key = {}
    # Reserve display names in the original order, independently of date resolution order.
    for source in sources:
        if source.entry_key in keys:
            raise ValidationError('A template task identifier conflicts with an existing task. No template was applied.')
        fields = EntryMapper.snapshot_fields(source)
        proposed, sequence = source.name, 1
        while proposed.casefold() in names:
            suffix = ' (template)' if sequence == 1 else f' (template {sequence})'
            proposed = source.name[:160 - len(suffix)] + suffix
            sequence += 1
        fields['name'] = proposed
        names.add(proposed.casefold())
        fields_by_key[source.entry_key] = fields
    for key in task_date_order(sources):
        source = by_key[key]
        copied[source.pk] = CalendarEntry.objects.create(calendar=calendar, source_entry=source,
                                                          created_by_ref=actor.reference, **fields_by_key[key])
        _queue_task_event(task_created, actor=actor, entry=copied[source.pk])
    dependent_ids = set()
    for link in TemplateDependency.objects.filter(entry__version=version):
        EntryDependency.objects.create(entry=copied[link.entry_id], predecessor=copied[link.predecessor_id])
        dependent_ids.add(link.entry_id)
    for source_id in dependent_ids:
        _queue_task_event(task_dependency_changed, actor=actor, entry=copied[source_id])


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


# DV1-046: Class-based callable API and factories.
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

    # DV1-006: Saved dependency validation.
    def available_predecessors(self, *, entry_key):
        """Return same-scope predecessor choices excluding this task and all its successors.
        Each result contains the entry key, display name, and diary/template-version scope.
        """
        actor, scope_key, template = self.actor, self.key, self._template_scope
        scope, model, links, field_name = _scope(actor, scope_key, template, 'view')
        choices = model.objects.filter(**{field_name: scope})

        # DV1-031: Private diary entries cannot become lookup targets or choices for other users.
        if not template and not _allowed(actor, 'edit'):
            choices = choices.filter(Q(source_entry__isnull=False) | ~Q(owner_kind=OwnerKind.PERSON)
                                     | Q(person_ref=actor.reference))
        entry = choices.get(entry_key=entry_key)

        # DV1-053: Diary additions can depend on template tasks but cannot become predecessors themselves.
        if not template:
            choices = choices.filter(source_entry__isnull=False)
        successors = {}
        link_pairs = list(links.objects.filter(**{f'entry__{field_name}': scope}).values_list('entry_id', 'predecessor_id'))
        for item, predecessor in link_pairs:
            successors.setdefault(predecessor, set()).add(item)
        excluded, pending = set(), [entry.pk]

        # Traverse successors until every task that would close a cycle has been excluded.
        while pending:
            item = pending.pop()

            # Visit each reachable task once, including when multiple dependency paths reach it.
            if item not in excluded:
                excluded.add(item)
                pending.extend(successors.get(item, ()))
        candidates = list(choices.order_by('name').values('pk', 'entry_key', 'name'))
        by_pk = {candidate['pk']: candidate for candidate in candidates}
        for candidate in candidates:
            candidate['predecessors'] = []
        for item, predecessor in link_pairs:
            if item in by_pk and predecessor in by_pk:
                by_pk[item]['predecessors'].append(by_pk[predecessor]['entry_key'])
        return tuple({'entry_key': item['entry_key'], 'name': item['name'],
                      'diary_key': None if template else scope_key,
                      'template_version_key': scope_key if template else None}
                     for item in ordered_task_choices(candidates) if item['pk'] not in excluded)

    # DV1-006, DV1-028: Only draft template dependencies can change in V1.
    @transaction.atomic
    def set_predecessors(self, *, entry_key, predecessor_keys):
        """Replace dependency links only in a permitted draft template version.
        Raise ValidationError for every diary dependency edit, including additions, removals, and repeated selections.
        Keep role, diary scope, and closure checks before reporting the V1 restriction.
        """
        actor, scope_key, template = self.actor, self.key, self._template_scope
        scope, model, links, field_name = _scope(actor, scope_key, template, 'edit')

        # Live diary graphs are immutable, even when a manager submits an empty or identical predecessor list.
        if not template:
            raise ValidationError('V1 does not allow dependency changes in an existing diary.')
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

        # DV1-053: Reject arbitrary diary tasks before replacing any saved links.
        if not template and any(item.source_entry_id is None for item in predecessors):
            raise ValidationError('Only template-sourced diary tasks can be predecessors.')
        links.objects.filter(entry=entry).delete()
        for predecessor in predecessors:
            links.objects.create(entry=entry, predecessor=predecessor)


# DV1-046: Class-based callable API and factories.
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

    def task_period(self, *, view='week', anchor_date=None, diary_key=None, mode='personal',
                    include_completed=False, show_blocked=True, include_whole_team=False,
                    query='', owner='', selected_day=None, page=1, late_page=1, undated_page=1,
                    period=None, today=None, directory=None, task_status='all', only_late=False):
        """DFUT-018: Return authorised day buckets and bounded previews for a week or month.
        Every task retains its diary key. Calendar selection never changes stored dates.
        """
        from .task_calendar import task_period
        return task_period(self, view=view, anchor_date=anchor_date, diary_key=diary_key, mode=mode,
            include_completed=include_completed, show_blocked=show_blocked, include_whole_team=include_whole_team,
            query=query, owner=owner, selected_day=selected_day, page=page, late_page=late_page,
            undated_page=undated_page, period=period, today=today, directory=directory,
            task_status=task_status, only_late=only_late)

    # DV1-002: Named milestone API.
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

    # DV1-024: Template chooser and named template view.
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

    # DV1-048: Standard Django groups and optional template default.
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

    # DV1-016: Revalidate ownership groups through the instance factory.
    # DV1-051: Creation requires no diary year.
    def create_diary(self, *, name, milestone_dates=None, template_version_key=None,
                     template_name=None, event_ref=None, without_template=False):
        """Create a diary using this actor and return its API reference.
        A missing selection/default creates an empty diary; without_template bypasses the default.
        Do not expand the actor calendar scope.
        """
        return DiaryInstance.create(
            actor=self.actor, event_ref=event_ref, name=name,
            milestone_dates=milestone_dates, template_version_key=template_version_key, template_name=template_name,
            without_template=without_template,
        )

    def diary(self, *, key):
        """Return a diary reference after checking the key against this actor role and calendar scope."""
        return DiaryInstance.from_key(actor=self.actor, key=key)

    # DV1-020: Owned tasks from one or all permitted open diaries.
    def personal_tasks(self, *, diary_key=None, today=None, include_whole_team=False):
        """Return owned open tasks with diary keys and names within the actor's scope.
        An omitted selector includes every permitted open diary.
        Explicit invalid or unauthorized selectors retain the normal diary lookup errors.
        """
        _require(self.actor, 'view')
        today = _comparison_date(today)

        # An explicit selector must pass the same scope and existence checks as other diary reads.
        if diary_key is not None:
            keys = (self.diary(key=diary_key).key,)

        # A broad selection can include only existing open diaries authorized by the host.
        else:
            keys = EventCalendar.objects.filter(pk__in=self.actor.calendar_keys, closed_at__isnull=True).values_list('pk', flat=True)
        result = []
        for key in keys:
            instance = DiaryInstance(actor=self.actor, key=key)
            for task in instance.personal_tasks(today=today, include_whole_team=include_whole_team):
                result.append(task)
        return tuple(sorted(result, key=self.personal_task_order))

    @staticmethod
    def personal_task_order(task):
        """Group task results by diary name and key, with late tasks first within each diary."""
        return (task['diary_name'].casefold(), str(task['diary_key']), not task['late'],
                task['date'] or date.max, task['name'].casefold(), str(task['entry_key']))

    # DV1-031: Cross-diary searches retain the host scope and each task's privacy boundary.
    def search_tasks(self, *, query='', diary_key=None):
        """Search visible task names and descriptions in one or all permitted diaries.
        Include completed tasks and closed diaries. Return diary keys and names with each task.
        Raise the normal scope and lookup errors for an explicit diary selector.
        """
        _require(self.actor, 'view')

        # Validate search input even when the actor has no permitted diaries.
        _search_entries((), query)

        # An explicit selector must not bypass scope checks or silently select another diary.
        if diary_key is not None:
            keys = (self.diary(key=diary_key).key,)

        # Omitted selectors search only existing diaries that the host authorized.
        else:
            keys = EventCalendar.objects.filter(pk__in=self.actor.calendar_keys).values_list('pk', flat=True)
        results = []
        for key in keys:
            results.extend(self.diary(key=key).search_tasks(query=query))
        return tuple(sorted(results, key=lambda task: (
            task['diary_name'].casefold(), str(task['diary_key']), task['name'].casefold(), str(task['entry_key']))))


# DV1-046: Class-based callable API and factories.
class DiaryTemplate(_BoundObject):
    """A template reference. Each operation reads current database state."""

    # DV1-024: Template chooser and named template view.
    def editor_data(self):
        """Return template metadata and the highest numbered version, including a draft.
        Return an empty entry sequence when the template has no version.
        """
        _require_template_access(self.actor)
        template = CalendarTemplate.objects.get(pk=self.key)
        version = template.versions.order_by('-number').first()
        result = {'key': template.pk, 'name': template.name, 'description': template.description,
                  'version_key': None, 'number': 0, 'status': '', 'entries': (), 'milestones': ()}

        # Empty templates must open for editing without creating a draft during a read.
        if version is not None:
            data = DiaryTemplateVersion(actor=self.actor, key=version.pk).read()
            result.update(version_key=data['key'], number=data['number'], status=data['status'],
                          entries=data['entries'], milestones=data['milestones'])
        return result

    # DV1-026: Versioned template save and approval.
    @transaction.atomic
    def save_version(self, *, entries, predecessors, expected_version_key, description=None,
                     milestone_names=None, directory=None):
        """Save and approve a complete new version after checking its predecessor graph.
        Preserve supplied entry keys and existing diaries. Lock the template against concurrent saves.
        Reject a stale expected_version_key with ValidationError. None expects an unversioned template.
        Derive requirements from task rules using the host milestone catalogue.
        milestone_names is accepted for compatibility; unused names do not become requirements.
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
        task_date_order(specs)
        graph = validate_template_graph((spec.entry_key for spec in specs), predecessors)

        # A new version follows the highest existing number, including any draft.
        number = latest.number + 1 if latest is not None else 1
        version = self.create_version(number=number, milestone_names=milestone_names or ())
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

    # DV1-048: Standard Django groups and optional template default.
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

    # DV1-048: Standard Django groups and optional template default.
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

    def create_version(self, *, number, milestone_names=()):
        """Create a numbered draft for this template and return its version reference."""
        return DiaryTemplateVersion.create(actor=self.actor, template_key=self.key, number=number,
                                           milestone_names=milestone_names)

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


# DV1-046: Class-based callable API and factories.
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
    @transaction.atomic
    def create(cls, *, actor, template_key, number, milestone_names=()):
        """Create a numbered draft version and return its reference.
        Record the supplied actor as its creator.
        """
        _require(actor, 'edit')
        version = TemplateVersion.objects.create(template_id=template_key, number=number,
                                                 created_by_ref=actor.reference)
        result = cls(actor=actor, key=version.pk)
        result.set_milestones(names=milestone_names)
        return result

    @transaction.atomic
    def set_milestones(self, *, names):
        """Replace a draft version's required milestones using existing catalogue names."""
        _require(self.actor, 'edit')
        version = TemplateVersion.objects.select_for_update().get(pk=self.key)
        if version.status != VersionStatus.DRAFT:
            raise ValidationError('Milestones in an approved template version cannot change.')
        if not isinstance(names, (list, tuple, set, frozenset)) or any(not isinstance(name, str) for name in names):
            raise ValidationError('Supply a collection of milestone names.')
        names = set(names)
        milestones = list(Milestone.objects.filter(name__in=names))
        if {item.name for item in milestones} != names:
            raise ValidationError('Select recognised catalogue milestones.')
        if version.entries.exclude(milestone__isnull=True).exclude(milestone__name__in=names).exists():
            raise ValidationError('A removed milestone is still used by template tasks.')
        version.milestone_declarations.exclude(milestone__name__in=names).delete()
        for milestone in milestones:
            TemplateMilestone.objects.get_or_create(version=version, milestone=milestone)
        return self

    # DV1-002: Named milestone API.
    def required_milestones(self):
        """Return the milestones used by this version, cached on approval."""
        actor, template_version_key = self.actor, self.key
        _require(actor, 'view_template')
        version = _template_version(template_version_key)
        milestones = version.milestones.all() if version.status == VersionStatus.APPROVED else Milestone.objects.filter(
            pk__in=version.entries.exclude(milestone_id=None).values('milestone_id'))
        return tuple(milestones.order_by('name').values('id', 'name', 'label').distinct())

    # DV1-005: Ownership data and assignment checks.
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

    # DV1-026: Versioned template save and approval.
    @transaction.atomic
    def approve(self):
        """Approve this version and return the same API reference.
        Repeated calls preserve the original approval time and actor.
        """
        actor, template_version_key = self.actor, self.key
        _require(actor, 'edit')
        template_id = TemplateVersion.objects.values_list('template_id', flat=True).get(pk=template_version_key)
        CalendarTemplate.objects.select_for_update().get(pk=template_id)
        version = TemplateVersion.objects.select_for_update().get(pk=template_version_key)

        if version.status == VersionStatus.DRAFT:
            task_date_order(version.entries.all())
            used = set(version.entries.exclude(milestone_id=None).values_list('milestone_id', flat=True))
            version.milestone_declarations.exclude(milestone_id__in=used).delete()
            for milestone_id in used:
                TemplateMilestone.objects.get_or_create(version=version, milestone_id=milestone_id)
        # Repeated approval preserves the original actor and approval time.
        if version.status != VersionStatus.APPROVED:
            previous = version.template.versions.filter(status=VersionStatus.APPROVED,
                                                         number__lt=version.number).order_by('-number').first()
            old_entries = {item.entry_key: item for item in previous.entries.prefetch_related('predecessors')} if previous else {}
            version.status = VersionStatus.APPROVED
            version.approved_at = timezone.now()
            version.approved_by_ref = actor.reference
            version.save()
            for entry in version.entries.prefetch_related('predecessors'):
                old = old_entries.get(entry.entry_key)
                if old is None:
                    _queue_task_event(task_created, actor=actor, entry=entry)
                elif ((old.owner_kind, old.person_ref, old.role_ref) !=
                      (entry.owner_kind, entry.person_ref, entry.role_ref)):
                    _queue_task_event(task_ownership_changed, actor=actor, entry=entry)
                before = {item.entry_key for item in old.predecessors.all()} if old else set()
                after = {item.entry_key for item in entry.predecessors.all()}
                if before != after:
                    _queue_task_event(task_dependency_changed, actor=actor, entry=entry)
        return self

    def read(self):
        """Return current version metadata, entry rules, and predecessor keys after checking manager access."""
        actor, template_version_key = self.actor, self.key
        _require(actor, 'view_template')
        version = _template_version(template_version_key)

        # Only milestone-based rules have a milestone name to include in the result.
        return {'key': version.pk, 'template_key': version.template_id, 'number': version.number,
                'status': version.status,
                'milestones': self.required_milestones(),
                'entries': tuple({**EntryMapper.snapshot_fields(entry),
                                  'template_version_key': version.pk,
                                  'milestone_name': entry.milestone.name if entry.milestone_id else None,
                                  'predecessors': tuple(entry.predecessors.values_list('entry_key', flat=True))}
                                 for entry in version.entries.select_related('milestone'))}


# DV1-046: Class-based callable API and factories.
class DiaryInstance(_DependencyAPI):
    """An instance reference without cached database or authorization results."""

    def graph(self, *, include_completed=False, exclude_blocked=False, exclude_non_late=False,
              today=None, directory=None):
        """DFUT-019: Return the selected diary's manager-only, filtered graph projection.
        Layout and colours remain presentation concerns; reads emit no task events.
        """
        from .diary_graph import diary_graph
        return diary_graph(self, include_completed=include_completed, exclude_blocked=exclude_blocked,
                           exclude_non_late=exclude_non_late, today=today, directory=directory)

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

    # DV1-004: Named diary creation and template snapshots.
    # DV1-048: Standard Django groups and optional template default.
    # DV1-016: Current ownership-group validation within the creation transaction.
    # DV1-051: A diary has a name and milestone dates without a diary year.
    @classmethod
    @transaction.atomic
    def create(cls, *, actor, name, milestone_dates=None, template_version_key=None,
               template_name=None, event_ref=None, without_template=False):
        """Create a stable diary, optionally copying an approved template atomically.
        Template-free diaries support personal tasks and later manager application.
        Repeated identical inputs with the same event_ref reuse the diary.
        Conflicting inputs raise ValidationError.
        Revalidate configured ownership groups on every call, including repeated requests.
        Raise ImproperlyConfigured when a configured group is missing or empty.
        Generate an internal reference when the optional caller reference is omitted.
        """
        _require(actor, 'use')
        _validate_task_owner_roles()

        # Independent callers can omit a host reference when they do not need safe retries.
        if event_ref is None:
            event_ref = f'diary:{uuid4()}'
        # A host reference serializes safe retries even before a template exists.
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', [event_ref.strip()])
        selected = _creation_template(key=template_version_key, name=template_name, without_template=without_template)
        version = None
        if selected is not None:
            CalendarTemplate.objects.select_for_update().get(pk=selected.template_id)
            version = TemplateVersion.objects.select_for_update().get(pk=selected.pk)
            if version.status != VersionStatus.APPROVED:
                raise ValidationError('Select an approved template version.')
        milestone_dates = {} if milestone_dates is None else milestone_dates
        milestone_dates = _validate_milestone_dates(version, milestone_dates)

        # The parent lock serializes repeated creation across template versions.
        existing = EventCalendar.objects.filter(event_ref=event_ref.strip()).first()

        # The host reference makes repeated creation safe without copying entries again.
        if existing:
            dates = existing.date_context()

            # Different inputs for the same reference require an explicit change rather than another creation.
            if (existing.name != name.strip() or (version is not None and
                    (existing.template_version_id != version.pk or {key: dates.get(key) for key in milestone_dates} != milestone_dates))):
                raise ValidationError('This event reference already has a calendar with different inputs.')
            return cls(actor=actor, key=existing.pk)

        # DV1-028: Only this new diary's creation transaction can initialize its dependency snapshot.
        calendar = EventCalendar.objects.create(template_version=version, event_ref=event_ref, name=name,
                                                created_by_ref=actor.reference, dependencies_locked=version is None)
        if version is not None:
            _set_dates(calendar, milestone_dates)
            _copy_template(calendar, version, actor)
            calendar.dependencies_locked = True
            calendar.save(update_fields=['dependencies_locked'])
        return cls(actor=actor, key=calendar.pk)

    @transaction.atomic
    def apply_template(self, *, milestone_dates, template_version_key=None, template_name=None):
        """Apply one approved template to an open diary, preserving all existing tasks.
        Managers only. Identical retries are safe; replacement is not supported.
        """
        _require(self.actor, 'edit')
        _validate_task_owner_roles()
        selected = _template_version(key=template_version_key, name=template_name)
        CalendarTemplate.objects.select_for_update().get(pk=selected.template_id)
        version = TemplateVersion.objects.select_for_update().get(pk=selected.pk)
        if version.status != VersionStatus.APPROVED:
            raise ValidationError('Select an approved template version.')
        milestone_dates = _validate_milestone_dates(version, milestone_dates)
        calendar = _open_calendar(self.actor, self.key, 'edit')
        if calendar.template_version_id:
            existing_dates = calendar.date_context()
            if (calendar.template_version_id == version.pk
                    and {key: existing_dates.get(key) for key in milestone_dates} == milestone_dates):
                return self
            raise ValidationError('This diary already has a template. It cannot be replaced.')
        calendar.template_version = version
        calendar.dependencies_locked = False
        calendar.save(update_fields=['template_version', 'dependencies_locked'])
        _set_dates(calendar, milestone_dates)
        _copy_template(calendar, version, self.actor)
        calendar.dependencies_locked = True
        calendar.save(update_fields=['dependencies_locked'])
        return self

    # DV1-008: Close a diary instance.
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
    def set_milestone_dates(self, *, milestone_dates):
        """Reject post-creation milestone changes with ValidationError under DV1-043.
        Preserve the current role, diary scope, and closure checks before rejecting the request.
        """
        _open_calendar(self.actor, self.key, 'edit')
        raise ValidationError('V1 does not allow milestone changes in an existing diary.')

    # DV1-040: Recover orphaned ownership without changing task identity or the live dependency graph.
    @transaction.atomic
    def reassign_task(self, *, entry_key, owner_kind, person_ref='', role_ref='', expected_revision,
                      update_template=False, expected_version_key=None, directory=None):
        """Assign an open orphaned task to an eligible person, role, or the whole team.
        Require a scoped manager and the inspected revision. Reject stale or ineligible requests with ValidationError.
        Optionally approve a matching template ownership revision in the same transaction.
        Preserve other diaries, task dates, dependencies, and completion records.
        """
        calendar = _open_calendar(self.actor, self.key, 'edit')
        entry = self._task_entry(calendar, entry_key)

        # An explicit boolean prevents nonempty strings from requesting a template revision.
        if type(update_template) is not bool:
            raise ValidationError('Supply a boolean template update option.')

        # Completed and concurrently changed tasks cannot accept an ownership edit.
        if entry.completed_at is not None or type(expected_revision) is not int or entry.revision != expected_revision:
            raise ValidationError('This task changed or completed. Reload it before reassignment.')

        # DV1-040: Diary additions cannot qualify for orphaned template ownership recovery.
        saved = {'source': 'template' if entry.source_entry_id else 'diary',
                 'entry_key': entry.entry_key, 'owner_kind': entry.owner_kind, 'person_ref': entry.person_ref,
                 'role_ref': entry.role_ref, 'completed_at': entry.completed_at}

        # A restored membership can make a previously inspected recovery action unnecessary.
        if entry.entry_key not in orphaned_entry_keys((saved,), directory=directory):
            raise ValidationError('This task is no longer orphaned. Reload it before reassignment.')
        values = EntryMapper.snapshot_fields(entry)
        values.pop('milestone_id')

        # Fixed-date tasks have no milestone name to preserve in the replacement specification.
        values['milestone_name'] = entry.milestone.name if entry.milestone_id else ''
        spec = replace(EntrySpec(**values), owner_kind=owner_kind, person_ref=person_ref, role_ref=role_ref)
        validate_entry_owner(spec, directory)

        # Recovery must not replace one unavailable owner with another unavailable owner.
        if orphaned_entry_keys(({'source': 'template', 'entry_key': entry.entry_key, 'owner_kind': owner_kind,
                                'person_ref': person_ref, 'role_ref': role_ref, 'completed_at': None},),
                               directory=directory):
            raise ValidationError('Select an active eligible person, a role with eligible members, or Whole team.')

        # Model validation also rejects incompatible person, role, and whole-team reference combinations.
        entry.owner_kind, entry.person_ref, entry.role_ref = owner_kind, person_ref, role_ref
        entry.revision += 1
        entry.save()
        _queue_task_event(task_ownership_changed, actor=self.actor, entry=entry)

        # A template update requires separate consent and keeps every other template field unchanged.
        if update_template:
            template = DiaryTemplate(actor=self.actor, key=calendar.template_version.template_id)
            CalendarTemplate.objects.select_for_update().get(pk=template.key)
            data = template.editor_data()
            specs, graph = [], {}
            found = False
            for item in data['entries']:

                # Serialized dependency fields are not task specification inputs.
                fields = {name: item[name] for name in EntrySpec.__dataclass_fields__ if name in item}
                proposed = EntrySpec(**fields)

                # Only the matching stable task key receives the replacement owner in the latest template.
                if proposed.entry_key == entry.entry_key:
                    proposed = replace(proposed, owner_kind=owner_kind, person_ref=person_ref, role_ref=role_ref)
                    found = True
                specs.append(proposed)
                graph[item['entry_key']] = item['predecessors']

            # Removed tasks must not be silently added back to the latest template version.
            if not found:
                raise ValidationError('This task is absent from the latest template. Save the diary assignment only.')
            template.save_version(entries=specs, predecessors=graph, expected_version_key=expected_version_key,
                                  directory=directory)
        return self.task(entry_key=entry.entry_key)

    # DV1-005: Ownership data and assignment checks.
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
        if spec.milestone_name and not calendar.milestone_dates.filter(
                milestone__name=spec.milestone_name).exists():
            raise ValidationError('Select a milestone available in this diary.')
        existing = calendar.entries.filter(entry_key=spec.entry_key).first()

        # Repeated entry requests reuse their stable identity within this diary.
        if existing:

            # Reject conflicting content rather than changing an entry during a repeated addition.
            if not EntryMapper.matches_spec(existing, spec):
                raise ValidationError('The entry key already identifies a different entry.')
            return existing.entry_key
        if spec.date_kind == DateKind.TASK:
            self._task_entry(calendar, spec.source_task_key)
        entry = CalendarEntry.objects.create(calendar=calendar, created_by_ref=actor.reference,
                                             **EntryMapper.to_model_fields(spec))
        _queue_task_event(task_created, actor=actor, entry=entry)
        return entry.entry_key

    # DV1-029, DV1-030, DV1-033: Save a task and an optional template revision together.
    @transaction.atomic
    def create_task(self, *, spec, template_spec=None, expected_version_key=None, directory=None):
        """Add a diary task and optionally approve a new version of its source template.
        Use the same entry key and owner for both additions.
        Reject repeated combined saves, stale versions, and nonreusable template rules with ValidationError.
        Roll back both additions if either operation fails.
        """
        calendar = _open_calendar(self.actor, self.key, 'use')

        # A diary-only addition keeps the existing ownership and safe-retry checks.
        if template_spec is None:
            return self.add_entry(spec=spec, directory=directory)
        _require(self.actor, 'edit')
        if calendar.template_version_id is None:
            raise ValidationError('Apply a template before adding tasks to it for future diaries.')

        # A recurring template task needs an explicitly supplied reusable rule and matching identity.
        if (template_spec.date_kind == DateKind.ONCE
                or template_spec.entry_key != spec.entry_key
                or (template_spec.name, template_spec.description, template_spec.owner_kind,
                    template_spec.person_ref, template_spec.role_ref)
                != (spec.name, spec.description, spec.owner_kind, spec.person_ref, spec.role_ref)):
            raise ValidationError('Use a reusable date rule with the same task identity and owner.')

        # The diary lock serializes retries before either addition can create another record.
        if calendar.entries.filter(entry_key=spec.entry_key).exists():
            raise ValidationError('This task was already added. Open a new task form.')
        template = DiaryTemplate(actor=self.actor, key=calendar.template_version.template_id)
        CalendarTemplate.objects.select_for_update().get(pk=template.key)
        data = template.editor_data()
        specs = []
        graph = {}
        for entry in data['entries']:

            # Serialized dependency and model fields are not EntrySpec constructor inputs.
            values = {name: entry[name] for name in EntrySpec.__dataclass_fields__ if name in entry}
            specs.append(EntrySpec(**values))
            graph[entry['entry_key']] = entry['predecessors']

        # A reused key must not replace a task in the current template revision.
        if template_spec.entry_key in graph:
            raise ValidationError('This task key already exists in the template.')
        self.add_entry(spec=spec, directory=directory)
        graph[spec.entry_key] = ()
        template.save_version(entries=(*specs, template_spec), predecessors=graph,
                              expected_version_key=expected_version_key, directory=directory)
        return spec.entry_key

    # DV1-023, DV1-031: Task lookup applies privacy before returning any task content.
    def _task_entry(self, calendar, entry_key):
        """Return one visible task or raise CalendarEntry.DoesNotExist for a private or unknown key."""
        entries = calendar.entries.select_related('milestone')

        # Managers can inspect private additions within scope, while ordinary users can inspect only their own additions.
        if not _allowed(self.actor, 'edit'):
            entries = entries.filter(Q(source_entry__isnull=False) | ~Q(owner_kind=OwnerKind.PERSON)
                                     | Q(person_ref=self.actor.reference))
        return entries.get(entry_key=entry_key)

    # DV1-032: Assignment alone cannot grant permission to edit a template task.
    def _can_edit_date(self, entry):
        """Return whether the actor can edit this task's diary-specific due date."""

        # Manager access permits scoped edits, while ordinary access requires a self-owned diary addition.
        return (_allowed(self.actor, 'edit') or
                (entry.source_entry_id is None and entry.owner_kind == OwnerKind.PERSON
                 and entry.person_ref == self.actor.reference))

    # DV1-035, DV1-037: Inspect the complete open chain without disclosing private task keys.
    def _open_blockers(self, calendar, entry):
        """Return open direct and indirect predecessors plus an opaque fingerprint of their current state.
        Stop traversal at completed tasks. Reject a corrupt cycle through the selected task.
        """
        entries = {item.entry_key: item for item in calendar.entries.select_related('milestone').prefetch_related('predecessors')}
        target = entries[entry.entry_key]
        pending = list(target.predecessors.all())
        found = {}

        # Each open predecessor contributes once, including shared and indirect blockers.
        while pending:
            item = entries[pending.pop().entry_key]

            # Completed predecessors no longer block this chain, and visited tasks need no second traversal.
            if item.completed_at is not None or item.entry_key in found:
                continue

            # Unsupported direct database changes must not force the selected task to complete itself as a predecessor.
            if item.entry_key == entry.entry_key:
                raise ValidationError('This task has a circular predecessor chain.')
            found[item.entry_key] = item
            pending.extend(item.predecessors.all())
        chain = tuple(found[key] for key in sorted(found))
        dates = calendar.date_context()
        state = [(str(item.entry_key), item.revision, str(item.open_due_date(source_dates=dates)),
                  sorted(str(predecessor.entry_key) for predecessor in item.predecessors.all()))
                 for item in (target, *chain)]
        token = salted_hmac('Diary.open-blockers', repr((str(calendar.pk), state)), algorithm='sha256').hexdigest()
        return chain, token

    # DV1-023, DV1-032, DV1-035, DV1-038: Task details and private-safe completion inspection.
    def task(self, *, entry_key):
        """Return task details, edit permission, completion history, and visible open predecessors.
        Represent inaccessible predecessors with one generic marker and no private identifiers.
        """
        calendar = _calendar(self.actor, self.key)
        entry = self._task_entry(calendar, entry_key)
        data = self.read()
        visible = {item['entry_key']: item for item in data['entries']}
        result = dict(visible[entry.entry_key])
        blockers, token = self._open_blockers(calendar, entry)
        listed = []
        private = False
        for blocker in blockers:

            # Private names, identifiers, dates, and owners must stay outside the result and HTML.
            if blocker.entry_key not in visible:
                private = True
                continue
            listed.append({**visible[blocker.entry_key], 'private': False})

        # One generic marker explains inaccessible blocking work without revealing its count.
        if private:
            listed.append({'private': True})

        # Metadata keeps the original rule, omits absent milestones, and permits edits only on an open task and diary.
        result.update(diary_key=calendar.pk, diary_name=calendar.name, closed=calendar.closed_at is not None,
                      can_edit_date=self._can_edit_date(entry) and entry.completed_at is None and calendar.closed_at is None,
                      manager=_allowed(self.actor, 'edit'), blockers=tuple(listed), blocker_token=token,
                      date_rule=EntryMapper.snapshot_fields(entry), date_rule_label=entry.get_date_kind_display(),
                      milestone_name=entry.milestone.name if entry.milestone_id else '')
        result['source_task_name'] = visible.get(entry.source_task_key, {}).get('name', 'Unavailable source task')
        result['task_due_date'] = entry.task_due_date
        if result['date_rule']['source_task_key'] not in visible:
            result['date_rule']['source_task_key'] = None
        today = _comparison_date(None)
        result['late'] = entry.completed_at is None and result['date'] is not None and result['date'] <= today

        # Direct late blockers determine the amber highlight even when their details are private.
        result['blocked_late'] = any(item.completed_at is None and item.open_due_date(source_dates=data['milestones']) is not None
                                    and item.open_due_date(source_dates=data['milestones']) <= today
                                    for item in entry.predecessors.select_related('milestone'))
        result['can_add_note'] = self._can_add_note(entry)
        result['notes'] = self.notes(entry_key=entry.entry_key)
        return result

    def _can_add_note(self, entry):
        return (_allowed(self.actor, 'edit') or entry.owner_kind == OwnerKind.TEAM
                or (entry.owner_kind == OwnerKind.PERSON and entry.person_ref == self.actor.reference)
                or (entry.owner_kind == OwnerKind.ROLE and entry.role_ref in self.actor.groups))

    def _note_data(self, note, labels, *, entry_key):
        return {'key': note.pk, 'diary_key': self.key, 'entry_key': entry_key,
                'text': note.text, 'author_ref': note.author_ref,
                'author_label': labels.get(note.author_ref, 'deleted user'), 'created_at': note.created_at}

    @staticmethod
    def _note_author_labels(references):
        model = get_user_model()
        keys = []
        for reference in references:
            if reference.startswith('user:'):
                try:
                    keys.append(model._meta.pk.to_python(reference[5:]))
                except (ValueError, TypeError, ValidationError):
                    pass
        return {f'user:{user.pk}': user_display_name(user) for user in model._default_manager.filter(pk__in=keys)}

    def notes(self, *, entry_key):
        """Read chronological notes using the task's normal visibility and diary scope."""
        entry = self._task_entry(_calendar(self.actor, self.key), entry_key)
        notes = tuple(entry.notes.all())
        labels = self._note_author_labels({note.author_ref for note in notes})
        return tuple(self._note_data(note, labels, entry_key=entry.entry_key) for note in notes)

    @transaction.atomic
    def add_note(self, *, entry_key, text, note_key=None):
        """Append a stamped note, including after task completion or diary closure.
        Assigned users/group members and managers may write. A repeated note_key
        reuses identical content by the same author; no task revision is changed.
        """
        calendar = _calendar(self.actor, self.key, 'use')
        EventCalendar.objects.select_for_update().get(pk=calendar.pk)
        entry = self._task_entry(calendar, entry_key)
        if not self._can_add_note(entry):
            raise PermissionDenied('Only the assigned users or a Diary Manager can add notes.')
        if not isinstance(text, str) or not text.strip():
            raise ValidationError('Enter a note.')
        text = text.strip()
        try:
            key = uuid4() if note_key is None else UUID(str(note_key))
        except (ValueError, TypeError, AttributeError) as error:
            raise ValidationError('Supply a valid note key.') from error
        existing = TaskNote.objects.filter(pk=key).first()
        if existing:
            if (existing.entry_id, existing.author_ref, existing.text) != (entry.pk, self.actor.reference, text):
                raise ValidationError('This note key was already used. Reload before adding a new note.')
            return self._note_data(existing, self._note_author_labels({existing.author_ref}), entry_key=entry.entry_key)
        note = TaskNote.objects.create(id=key, entry=entry, text=text, author_ref=self.actor.reference)
        _queue_task_event(task_note_added, actor=self.actor, entry=entry)
        return self._note_data(note, self._note_author_labels({note.author_ref}), entry_key=entry.entry_key)

    # DV1-032: Users edit their personal additions, while managers can also edit template-task dates.
    @transaction.atomic
    def update_due_date(self, *, entry_key, due_date, expected_revision):
        """Set a diary-specific due date after permission, closure, completion, and revision checks.
        Raise PermissionDenied for unauthorized edits and ValidationError for invalid or stale input.
        Keep template rules, ownership, dependencies, and other diaries unchanged.
        """
        calendar = _open_calendar(self.actor, self.key, 'use')
        entry = self._task_entry(calendar, entry_key)

        # A role assignment or copied template task does not grant ordinary users date-edit permission.
        if not self._can_edit_date(entry):
            raise PermissionDenied('Only managers can edit this task date.')

        # Completion freezes the due date and every task field.
        if entry.completed_at is not None:
            raise ValidationError('A completed task cannot change.')

        # Plain calendar dates prevent timestamps or empty values from changing the date interpretation.
        if type(due_date) is not date:
            raise ValidationError('Supply a due date.')

        # A stale form must not replace a date saved by another caller.
        if type(expected_revision) is not int or expected_revision != entry.revision:
            raise ValidationError('This task changed. Reload it before saving.')
        entry.due_date_override = due_date
        entry.revision += 1
        entry.save()
        return self.task(entry_key=entry.entry_key)

    # DV1-036, DV1-037, DV1-038: Normal and forced completion share the diary write lock.
    @transaction.atomic
    def complete(self, *, entry_key, expected_revision, close_all=False, expected_blockers=None):
        """Complete an accessible task, or its open blocking chain when a manager selects Close all.
        Recheck blocking and revisions under the diary lock. Keep repeated completion requests unchanged.
        Record the actor, time, effective due date, action, and forced-predecessor comments atomically.
        """
        calendar = _open_calendar(self.actor, self.key, 'use')

        # Reject nonboolean action flags before interpreting privileged completion behavior.
        if type(close_all) is not bool:
            raise ValidationError('Supply a boolean Close all option.')

        # Forced completion requires manager permission even when the selected task is already complete.
        if close_all:
            _require(self.actor, 'edit')
        entry = self._task_entry(calendar, entry_key)

        # A repeated request keeps the first completion actor, time, date, and comments.
        if entry.completed_at is not None:
            return self.task(entry_key=entry.entry_key)

        # A completion form must describe the task date and state that the caller inspected.
        if type(expected_revision) is not int or expected_revision != entry.revision:
            raise ValidationError('This task changed. Reload it before completion.')
        blockers, token = self._open_blockers(calendar, entry)

        # Normal completion cannot bypass any open direct or indirect predecessor.
        if blockers and not close_all:
            raise ValidationError('Open predecessors must finish before this task can complete.')

        # A changed chain requires another inspection before a manager can force its completion.
        if close_all and expected_blockers != token:
            raise ValidationError('The predecessor chain changed. Reload it before Close all.')
        now = timezone.now()

        # Normal completion changes only the selected task, while Close all first completes the inspected open chain.
        affected = (*blockers, entry) if close_all else (entry,)
        for item in affected:
            item.completed_at = now
            item.completed_by_ref = self.actor.reference
            item.completion_target_key = entry.entry_key
            item.revision += 1

            # Forced predecessor comments identify the selected task without replacing an earlier completion record.
            if item.entry_key != entry.entry_key:
                item.completion_action = 'forced_predecessor'
                item.completion_comment = f'Close all completed this predecessor for "{entry.name}" ({entry.entry_key}).'

            # The selected task records the exact action used by the caller.
            else:
                item.completion_action = 'close_all' if close_all else 'complete'
            item.save()
            _queue_task_event(task_closed, actor=self.actor, entry=item)
        return self.task(entry_key=entry.entry_key)

    # DV1-007: Task reads for one diary.
    def read(self):
        """Return diary metadata and visible entries without private predecessor references.
        DV1-031: Preserve blocking without exposing another person's private task.
        """
        return self._read()

    # DV1-031: Search applies privacy before text matching and before returning related task references.
    def search_tasks(self, *, query=''):
        """Search visible task names and descriptions, including completion history.
        Return diary keys and names. Preserve private-safe dependency and completion references.
        """
        data = self.read()
        return tuple({**entry, 'diary_key': data['key'], 'diary_name': data['name']}
                     for entry in _search_entries(data['entries'], query))

    def _read(self, *, filter_visibility=True):
        """Return current diary metadata, milestone values, entries, and dependency state.
        Internal state calculations can inspect the full graph before filtering output.
        """
        actor, calendar_key = self.actor, self.key
        calendar = _calendar(actor, calendar_key)
        context = calendar.date_context()
        entries = []
        for entry in calendar.entries.select_related('milestone').prefetch_related('predecessors'):
            predecessors = tuple(entry.predecessors.all())

            # Completed tasks retain their recorded due date when source milestones later change.
            # Completed predecessors remain in history but no longer block the task.
            # DV1-022, DV1-052: Managers can display task origin and the completing actor.
            # A source-entry reference distinguishes copied tasks from diary additions.
            # DV1-032, DV1-036: Open tasks use effective date overrides, while completed tasks keep their recorded dates.
            entries.append({'entry_key': entry.entry_key, 'diary_key': calendar.pk,
                            'name': entry.name, 'description': entry.description,
                            'date': (entry.completed_due_date if entry.completed_at is not None else
                                     entry.open_due_date(source_dates=context)),
                            'source': 'template' if entry.source_entry_id else 'diary',
                            'owner_kind': entry.owner_kind, 'person_ref': entry.person_ref, 'role_ref': entry.role_ref,
                            'predecessors': tuple(item.entry_key for item in predecessors),
                            'blocking_predecessors': tuple(
                                item.entry_key for item in predecessors if item.completed_at is None),
                            'completed_at': entry.completed_at,
                            'completed_by_ref': entry.completed_by_ref,
                            'completed_due_date': entry.completed_due_date, 'revision': entry.revision,
                            'completion_action': entry.completion_action, 'completion_comment': entry.completion_comment,
                            'completion_target_key': entry.completion_target_key,
                            'ready': entry.completed_at is None and all(
                                item.completed_at is not None for item in predecessors)})
        # Public reads protect private entries after calculating readiness from all predecessors.
        visible = _visible_entries(actor, entries) if filter_visibility else tuple(entries)
        return {'key': calendar.pk, 'name': calendar.name, 'event_ref': calendar.event_ref,
                'template_version_key': calendar.template_version_id,
                'closed': calendar.closed_at is not None, 'closed_at': calendar.closed_at,
                'closed_by_ref': calendar.closed_by_ref,
                'milestones': context, 'entries': visible}

    # DV1-003: Date calculation.
    # DV1-007: Task reads for one diary.
    # DV1-050: Optional Diary time zone with the project default.
    def active_tasks(self, *, today=None):
        """Return open tasks with independently calculated readiness and lateness.
        Use the configured local date when today is omitted.
        Use Django's project-default time zone when DIARY_TIME_ZONE is absent.
        Return an empty tuple for a closed diary.
        """

        calendar, tasks = self._calendar_tasks(today=today)
        return () if calendar['closed'] else tuple(item for item in tasks if item['completed_at'] is None)

    def _calendar_tasks(self, *, today=None):
        """Calculate full-graph status once before privacy filtering, including completion history.
        Calendar selection may subsequently filter dates without losing out-of-period blockers.
        """
        today = _comparison_date(today)
        calendar = self._read(filter_visibility=False)
        # Aggregate blocker lateness without returning private dates, text, or keys.
        late_keys = {entry['entry_key'] for entry in calendar['entries']
                     if entry['completed_at'] is None and entry['date'] is not None and entry['date'] <= today}
        result = []
        for entry in calendar['entries']:

            # Readiness identifies blocking predecessors independently of the separate lateness calculation.
            # Tasks due today are late, while tasks without a due date are not late.
            completed = entry['completed_at'] is not None
            result.append({**entry, 'state': 'completed' if completed else 'ready' if entry['ready'] else 'blocked',
                           'late': not completed and entry['date'] is not None and entry['date'] <= today,
                           'blocked_late': any(key in late_keys for key in entry['blocking_predecessors']),
                           'diary_key': calendar['key'], 'diary_name': calendar['name'],
                           'date_not_set': entry['date'] is None})
        return calendar, tuple(sorted(_visible_entries(self.actor, result), key=lambda item: (not item['late'], item['date'] or date.max,
                                                      item['name'].casefold(), str(item['entry_key']))))

    # DV1-007: Task reads for one diary.
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
