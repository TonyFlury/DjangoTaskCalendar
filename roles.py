"""Configured task-owner roles and host database validation."""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.utils.module_loading import import_string


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
    path = getattr(settings, 'DIARY_ROLE_LOOKUP', '')
    if not isinstance(path, str) or not path:
        raise ImproperlyConfigured(
            'Set DIARY_ROLE_LOOKUP to a host database lookup callable when DIARY_TASK_OWNER_ROLES is not empty.')
    try:
        lookup = import_string(path)
    except (ImportError, AttributeError, ValueError) as error:
        raise ImproperlyConfigured(f'DIARY_ROLE_LOOKUP cannot import {path!r}.') from error
    if not callable(lookup):
        raise ImproperlyConfigured(f'DIARY_ROLE_LOOKUP {path!r} must be callable.')
    try:
        existing = lookup(roles)
        if isinstance(existing, str):
            raise TypeError('Expected a collection of role names.')
        existing = set(existing)
    except DatabaseError as error:
        raise ImproperlyConfigured(
            'Diary cannot validate DIARY_TASK_OWNER_ROLES against the database. '
            'Check the database connection, apply migrations, and create the configured roles before startup.'
        ) from error
    except TypeError as error:
        raise ImproperlyConfigured(
            f'DIARY_ROLE_LOOKUP {path!r} must return a collection of existing role names.') from error
    missing = roles - existing
    if missing:
        raise ImproperlyConfigured(
            'DIARY_TASK_OWNER_ROLES contains roles missing from the database: '
            + ', '.join(sorted(missing))
            + '. Create these roles in the host database or correct DIARY_TASK_OWNER_ROLES. '
            + f'Lookup: {path}.'
        )
