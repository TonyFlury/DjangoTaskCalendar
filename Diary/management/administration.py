"""Shared operator command support and atomic whole-object deletion.

Parent-first SQL relies on Django's deferred PostgreSQL foreign keys. Guards allow
child cleanup only after the parent is absent; no triggers are disabled. These
operations are for deployment operators, outside the end-user callable API.
"""
import json
import logging

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, connection, transaction

from Diary.api import Actor
from Diary.models import (CalendarEntry, CalendarMilestone, CalendarTemplate, EntryDependency,
                          EventCalendar, TemplateDependency, TemplateEntry, TemplateMilestone, TemplateVersion)
from Diary.roles import access_groups

logger = logging.getLogger('Diary.management')


class OperatorCommand(BaseCommand):
    """Require a current manager and return structured command output."""

    def add_operator_arguments(self, parser):
        parser.add_argument('--actor', required=True, help='Username of an active DiaryManager; required for all operations.')
        parser.add_argument('--yes', action='store_true', help='Execute deletion rather than previewing it.')
        parser.add_argument('--dry-run', action='store_true', help='Preview a deletion even when --yes is supplied.')

    def require(self, options, *names):
        for name in names:
            if options.get(name) is None or options.get(name) == '':
                raise CommandError('--' + name.replace('_', '-') + ' is required for this operation.')

    def reject_unused(self, options, allowed, defaults):
        for name, default in defaults.items():
            if name not in allowed and options[name] != default:
                raise CommandError('--' + name.replace('_', '-') + ' does not apply to this operation.')

    def handle(self, *args, **options):
        try:
            if (options['yes'] or options['dry_run']) and options['operation'] not in {'delete', 'delete-version'}:
                raise CommandError('--yes and --dry-run apply only to deletion.')
            model = get_user_model()
            user = model._default_manager.get(**{model.USERNAME_FIELD: options['actor']}, is_active=True)
            groups = frozenset(user.groups.values_list('name', flat=True))
            if access_groups()['manager'] not in groups:
                raise CommandError('The actor must belong to the configured DiaryManager group.')
            self.actor = Actor(f'user:{user.pk}', groups)
            result = self.execute_operation(options)
            self.write_result(result, options)
        except (ObjectDoesNotExist, ValidationError, ValueError, IntegrityError, PermissionDenied, ImproperlyConfigured) as error:
            raise CommandError(str(error)) from error

    def execute_operation(self, options):
        raise NotImplementedError

    def write_result(self, result, options):
        self.stdout.write(json.dumps(result, cls=DjangoJSONEncoder, indent=2))


def delete_rows(model, clause, parameters):
    """Execute parameterised deletion using internal, fixed column clauses only."""
    table = connection.ops.quote_name(model._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f'DELETE FROM {table} WHERE {clause}', parameters)


@transaction.atomic
def delete_diary(*, key, actor, execute=False):
    diary = EventCalendar.objects.select_for_update().get(pk=key)
    entries = CalendarEntry.objects.filter(calendar=diary)
    result = {'operation': 'delete-diary', 'diary_key': diary.pk, 'name': diary.name,
              'event_ref': diary.event_ref, 'actor': actor.reference, 'deleted': False,
              'counts': {'diaries': 1, 'tasks': entries.count(),
                         'completed_tasks': entries.filter(completed_at__isnull=False).count(),
                         'dependencies': EntryDependency.objects.filter(entry__calendar=diary).count(),
                         'milestone_dates': diary.milestone_dates.count()}}
    if execute:
        delete_rows(EventCalendar, 'id = %s', [key])
        entry_table = connection.ops.quote_name(CalendarEntry._meta.db_table)
        delete_rows(EntryDependency, f'entry_id IN (SELECT id FROM {entry_table} WHERE calendar_id = %s)', [key])
        delete_rows(CalendarMilestone, 'calendar_id = %s', [key])
        delete_rows(CalendarEntry, 'calendar_id = %s', [key])
        result['deleted'] = True
        transaction.on_commit(lambda: logger.info('Diary deleted: actor=%s diary_key=%s', actor.reference, key))
    return result


@transaction.atomic
def delete_template(*, key, actor, number=None, execute=False):
    template = CalendarTemplate.objects.select_for_update().get(pk=key)
    versions = template.versions.order_by('number')
    if number is not None:
        versions = versions.filter(number=number)
    versions = list(versions.select_for_update())
    if number is not None and not versions:
        raise CommandError('The selected template version does not exist.')
    keys = [version.pk for version in versions]
    references = EventCalendar.objects.filter(template_version_id__in=keys)
    if references.exists():
        raise CommandError(f'Deletion blocked: {references.count()} diary instance(s) reference the selected version(s).')
    if CalendarEntry.objects.filter(source_entry__version_id__in=keys).exists():
        raise CommandError('Deletion blocked: diary tasks still reference the selected template version(s).')
    result = {'operation': 'delete-template' if number is None else 'delete-template-version',
              'template_key': template.pk, 'name': template.name, 'actor': actor.reference,
              'versions': [{'key': item.pk, 'number': item.number, 'status': item.status} for item in versions],
              'deleted': False,
              'counts': {'templates': int(number is None), 'versions': len(keys),
                         'tasks': TemplateEntry.objects.filter(version_id__in=keys).count(),
                         'dependencies': TemplateDependency.objects.filter(entry__version_id__in=keys).count(),
                         'milestone_declarations': TemplateMilestone.objects.filter(version_id__in=keys).count()}}
    if execute:
        for version in versions:
            delete_rows(TemplateVersion, 'id = %s', [version.pk])
            entry_table = connection.ops.quote_name(TemplateEntry._meta.db_table)
            delete_rows(TemplateDependency, f'entry_id IN (SELECT id FROM {entry_table} WHERE version_id = %s)', [version.pk])
            delete_rows(TemplateEntry, 'version_id = %s', [version.pk])
            delete_rows(TemplateMilestone, 'version_id = %s', [version.pk])
        if number is None:
            delete_rows(CalendarTemplate, 'id = %s', [key])
        result['deleted'] = True
        transaction.on_commit(lambda: logger.info('Template deletion: actor=%s template_key=%s version=%s', actor.reference, key, number))
    return result
