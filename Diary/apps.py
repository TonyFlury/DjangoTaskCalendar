"""Diary application registration and database-free settings validation."""
from django.apps import AppConfig


class DiaryConfig(AppConfig):
    """Register Diary and validate access and ownership setting values."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Diary'
    verbose_name = 'Diary'

    # DV1-009: Configured ownership role names and existence checks.
    # DV1-047: Simple V1 access settings.
    # DV1-014: Startup access-group validation.
    # DV1-015: Startup ownership-group membership validation.
    def ready(self):
        """Validate setting values without accessing the database during app loading.

        Run validate_diary_configuration after database and group setup to check
        that configured groups exist and contain members.
        """
        from .roles import access_groups, task_owner_roles

        access_groups()
        task_owner_roles()

