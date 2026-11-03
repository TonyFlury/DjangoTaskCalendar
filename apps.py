"""Diary application startup validation and administrative setup exceptions."""
import sys

from django.apps import AppConfig


class DiaryConfig(AppConfig):
    """Register Diary and validate configured access and ownership groups at startup."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Diary'
    verbose_name = 'Diary'

    # DV1-009: Configured ownership role names and existence checks.
    # DV1-047: Simple V1 access settings.
    # DV1-014: Startup access-group validation.
    def ready(self):
        """Validate settings and populated access groups before ordinary application startup.
        Leave database setup, repair, and test-database creation available to administrators.
        """
        from .roles import access_groups, task_owner_roles, validate_access_groups, validate_task_owner_roles

        access_groups()
        task_owner_roles()

        # Setup and repair commands must work before groups exist. Tests create their database after app loading.
        if len(sys.argv) > 1 and sys.argv[1] in {
            'migrate', 'sync_access_policy', 'shell', 'createsuperuser', 'loaddata', 'test',
        }:
            return
        validate_access_groups()
        validate_task_owner_roles()
