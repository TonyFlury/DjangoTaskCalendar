"""Shared operator command support and atomic whole-object deletion.

Parent-first SQL relies on Django's deferred PostgreSQL foreign keys. Guards allow
child cleanup only after the parent is absent; no triggers are disabled. These
operations are for deployment operators, outside the end-user callable API.
"""
import logging

from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, IntegrityError, connection, transaction

from Diary.api import Actor
from Diary.models import (CalendarEntry, CalendarMilestone, CalendarTemplate, EntryDependency,
                          EventCalendar, TemplateDependency, TemplateEntry, TemplateMilestone, TemplateVersion, TaskNote)
from Diary.roles import access_groups
from Diary.management.output import write_command_result

logger = logging.getLogger('Diary.management')


def operator_actor():
    """Trust command-line access and use a stable, non-user audit identity."""
    return Actor('management:operator', frozenset({access_groups()['manager']}))


def integrity_error_message(error, *, deleting):
    """Preserve PostgreSQL diagnostics rather than guessing every failure is a foreign key."""
    cause = error.__cause__
    diagnostic = getattr(cause, 'diag', None)
    reason = getattr(diagnostic, 'message_primary', None) or str(error).strip()
    detail = getattr(diagnostic, 'message_detail', None)
    state = getattr(cause, 'sqlstate', None) or getattr(cause, 'pgcode', None)
    parts = [f'Database rejected {"deletion" if deleting else "the operation"}: {reason or "integrity check failed"}.']
    if detail:
        parts.append(f'Details: {detail}')
    for attribute, label in (('table_name', 'Table'), ('constraint_name', 'Constraint')):
        value = getattr(diagnostic, attribute, None)
        if value:
            parts.append(f'{label}: {value}.')
    if state:
        parts.append(f'SQLSTATE: {state}.')
    if deleting:
        parts.append('No records were deleted.')
        if state == '23514' and 'V1 does not allow' in reason:
            parts.append('A Diary protection trigger blocked cleanup. Check that migration '
                         'Diary.0009_administrative_deletion is applied: '
                         'python manage.py showmigrations Diary; python manage.py migrate Diary.')
    return ' '.join(parts)


class OperatorCommand(BaseCommand):
    """Trust deployment operators and render human-readable or JSON results."""

    def add_operator_arguments(self, parser):
        parser.add_argument('--force', '--yes', dest='yes', action='store_true', help='Delete without interactive confirmation (--yes is an alias).')
        parser.add_argument('--dry-run', action='store_true', help='Preview deletion without prompting or changing data, even with --force.')

    def require(self, options, *names):
        for name in names:
            if options.get(name) is None or options.get(name) == '':
                raise CommandError('--' + name.replace('_', '-') + ' is required for this operation.')

    def reject_unused(self, options, allowed, defaults):
        for name, default in defaults.items():
            if name not in allowed and options[name] != default:
                raise CommandError('--' + name.replace('_', '-') + ' does not apply to this operation.')

    def handle(self, *args, **options):
        deleting = options['operation'] in {'delete', 'delete-version'}
        try:
            if (options['yes'] or options['dry_run']) and options['operation'] not in {'delete', 'delete-version'}:
                raise CommandError('--force/--yes and --dry-run apply only to deletion.')
            self.actor = operator_actor()
            if deleting and not options['yes'] and not options['dry_run']:
                if options['json']:
                    raise CommandError('JSON deletion requires --force to execute or --dry-run to preview; no confirmation is read from stdin.')
                preview = self.execute_operation({**options, 'dry_run': True})
                self.write_result(preview, options)
                if not self.confirm_deletion():
                    self.stdout.write('Deletion cancelled. No records were deleted.')
                    return
                options['yes'] = True
                options['_delete_preview'] = preview
            result = self.execute_operation(options)
            self.write_result(result, options)
        except (CommandError, ObjectDoesNotExist, ValidationError, ValueError, DatabaseError, PermissionDenied, ImproperlyConfigured) as error:
            operation = options['operation']
            target = (options.get('name') if operation == 'create' else None) or options.get('diary') or options.get('template') or 'selection'
            if options.get('template_version') is not None:
                target = f"{target} (version {options['template_version']})"
            message = '; '.join(error.messages) if isinstance(error, ValidationError) else str(error)
            if isinstance(error, ObjectDoesNotExist):
                message = 'The selected item does not exist.'
            if isinstance(error, IntegrityError):
                message = integrity_error_message(error, deleting=deleting)
            elif isinstance(error, DatabaseError):
                message = 'Database operation failed. Check the connection and apply the Diary migrations.'
            raise CommandError(f'Cannot {operation} {target}: {message}') from error

    def confirm_deletion(self):
        while True:
            try:
                answer = input('Delete the item shown above? [y/N]: ').strip().lower()
            except (EOFError, KeyboardInterrupt):
                return False
            if answer in {'y', 'yes'}:
                return True
            if answer in {'', 'n', 'no'}:
                return False
            self.stderr.write('Please answer y or n.')

    def execute_operation(self, options):
        raise NotImplementedError

    def write_result(self, result, options):
        write_command_result(self.stdout, result, as_json=options['json'])


def delete_rows(model, clause, parameters):
    """Execute parameterised deletion using internal, fixed column clauses only."""
    table = connection.ops.quote_name(model._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f'DELETE FROM {table} WHERE {clause}', parameters)


@transaction.atomic
def delete_diary(*, key, actor, execute=False, expected=None):
    diary = EventCalendar.objects.select_for_update().get(pk=key)
    entries = CalendarEntry.objects.filter(calendar=diary)
    result = {'operation': 'delete-diary', 'diary_key': diary.pk, 'name': diary.name,
              'event_ref': diary.event_ref, 'actor': actor.reference, 'deleted': False,
              'counts': {'diaries': 1, 'tasks': entries.count(),
                         'completed_tasks': entries.filter(completed_at__isnull=False).count(),
                         'dependencies': EntryDependency.objects.filter(entry__calendar=diary).count(),
                         'milestone_dates': diary.milestone_dates.count(),
                         'notes': TaskNote.objects.filter(entry__calendar=diary).count()}}
    if execute and expected is not None and result != expected:
        raise CommandError('The diary changed after the preview. Inspect it again before deleting.')
    if execute:
        delete_rows(EventCalendar, 'id = %s', [key])
        entry_table = connection.ops.quote_name(CalendarEntry._meta.db_table)
        delete_rows(EntryDependency, f'entry_id IN (SELECT id FROM {entry_table} WHERE calendar_id = %s)', [key])
        delete_rows(CalendarMilestone, 'calendar_id = %s', [key])
        delete_rows(TaskNote, f'entry_id IN (SELECT id FROM {entry_table} WHERE calendar_id = %s)', [key])
        delete_rows(CalendarEntry, 'calendar_id = %s', [key])
        result['deleted'] = True
        transaction.on_commit(lambda: logger.info('Diary deleted: actor=%s diary_key=%s', actor.reference, key))
    return result


@transaction.atomic
def delete_template(*, key, actor, number=None, execute=False, expected=None):
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
    if execute and expected is not None and result != expected:
        raise CommandError('The template changed after the preview. Inspect it again before deleting.')
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
