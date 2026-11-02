"""Configured access roles and Django group validation."""
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError


def access_groups():
    result = {}
    for role, name in (('manager', 'DIARY_MANAGER'), ('user', 'DIARY_USER')):
        value = getattr(settings, name, None)
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ImproperlyConfigured(f'{name} must name one Django group without surrounding spaces.')
        result[role] = value
    return result


def task_owner_roles():
    roles = getattr(settings, 'DIARY_TASK_OWNER_ROLES', ())
    if (not isinstance(roles, (list, tuple, set, frozenset))
            or any(not isinstance(role, str) or not role.strip() or role != role.strip() for role in roles)):
        raise ImproperlyConfigured(
            'DIARY_TASK_OWNER_ROLES must be a collection of nonempty role names without surrounding spaces.')
    return frozenset(roles)


def validate_task_owner_roles():
    roles = task_owner_roles()
    if not roles:
        return
    try:
        existing = set(Group.objects.filter(name__in=roles).values_list('name', flat=True))
    except DatabaseError as error:
        raise ImproperlyConfigured(
            'Diary cannot validate DIARY_TASK_OWNER_ROLES against the database. '
            'Check the database connection, apply migrations, and create the configured roles before startup.'
        ) from error
    missing = roles - existing
    if missing:
        raise ImproperlyConfigured(
            'DIARY_TASK_OWNER_ROLES contains roles missing from the database: '
            + ', '.join(sorted(missing))
            + '. Create these Django groups or correct DIARY_TASK_OWNER_ROLES.'
        )
