import sys

from django.apps import AppConfig


class DiaryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Diary'
    verbose_name = 'Diary'

    # DV1-009: Configured ownership role names and existence checks.
    # DV1-047: Simple V1 access settings.
    # Partial DV1-014: Startup access-group validation.
    def ready(self):
        from .roles import access_groups, task_owner_roles, validate_task_owner_roles

        access_groups()
        task_owner_roles()

        # Bootstrap commands must be able to create the tables and host roles.
        if len(sys.argv) > 1 and sys.argv[1] in {'migrate', 'sync_access_policy'}:
            return
        validate_task_owner_roles()
