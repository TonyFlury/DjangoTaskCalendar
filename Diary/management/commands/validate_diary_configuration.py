"""Validate configured Diary groups after database setup."""
from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from Diary.roles import validate_access_groups, validate_task_owner_roles


class Command(BaseCommand):
    help = 'Check that configured Diary access and ownership groups exist and contain members.'

    def handle(self, *args, **options):
        try:
            validate_access_groups()
            validate_task_owner_roles()
        except ImproperlyConfigured as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS('Diary configuration is valid.'))
