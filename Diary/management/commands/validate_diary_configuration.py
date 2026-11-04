"""Validate configured Diary groups after database setup."""
from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from Diary.roles import validate_access_groups, validate_task_owner_roles
from Diary.management.output import write_command_result


class Command(BaseCommand):
    help = 'Check that configured Diary access and ownership groups exist and contain members.'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', help='Return a JSON validation result for scripts.')

    def handle(self, *args, **options):
        try:
            validate_access_groups()
            validate_task_owner_roles()
        except ImproperlyConfigured as error:
            raise CommandError(str(error)) from error
        write_command_result(self.stdout, {'valid': True, 'message': 'Diary configuration is valid.'}, as_json=options['json'])
