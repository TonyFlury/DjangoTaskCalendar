"""Configured access roles and Django group validation."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.db.models import Exists, OuterRef


# DV1-047: Simple V1 access settings.
# DV1-014: Startup access-group validation.
def access_groups():
    """Return configured access group names without querying the database.
    Raise ImproperlyConfigured for missing or invalid setting values.
    """
    result = {}
    for role, name in (('manager', 'DIARY_MANAGER'), ('user', 'DIARY_USER')):
        value = getattr(settings, name, None)

        # Each setting must identify one group without ambiguous whitespace or collection values.
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ImproperlyConfigured(f'{name} must name one Django group without surrounding spaces.')
        result[role] = value
    return result


# DV1-014: Startup access-group existence and membership validation.
def validate_access_groups():
    """Confirm that both configured access groups exist and contain a user.
    Use the configured Django user model without changing groups or memberships.
    Raise ImproperlyConfigured for missing groups, empty groups, or failed database checks.
    """
    groups = access_groups()
    configured = ', '.join(f'DIARY_{role.upper()}={name!r}' for role, name in groups.items())
    try:
        members = get_user_model()._base_manager.filter(groups=OuterRef('pk'))
        existing = dict(Group.objects.filter(name__in=groups.values()).annotate(
            has_members=Exists(members)).values_list('name', 'has_members'))
    except DatabaseError as error:
        raise ImproperlyConfigured(
            f'Diary cannot validate access groups against the database ({configured}). '
            'Check the database connection. Apply migrations and populate the configured groups before startup.'
        ) from error
    problems = []
    for role, name in groups.items():
        setting_name = f'DIARY_{role.upper()}'

        # Missing groups need creation, while existing empty groups need user assignments.
        if name not in existing:
            problems.append(f'{setting_name} references missing group {name!r}.')

        # Membership is checked independently of whether a group grants Django permissions.
        elif not existing[name]:
            problems.append(f'{setting_name} references empty group {name!r}.')

    # Report every invalid configured group together without changing stored membership.
    if problems:
        raise ImproperlyConfigured(
            'Diary access-group validation failed. ' + ' '.join(problems)
            + ' Create missing groups and add at least one user to each configured group before startup.'
        )


# DV1-009: Configured ownership role names and existence checks.
def task_owner_roles():
    """Return permitted ownership role names after validating the setting value."""
    roles = getattr(settings, 'DIARY_TASK_OWNER_ROLES', ())

    # Ownership roles must be an explicit collection of usable group names.
    if (not isinstance(roles, (list, tuple, set, frozenset))
            or any(not isinstance(role, str) or not role.strip() or role != role.strip() for role in roles)):
        raise ImproperlyConfigured(
            'DIARY_TASK_OWNER_ROLES must be a collection of nonempty role names without surrounding spaces.')
    return frozenset(roles)


# DV1-009: Configured ownership role names and existence checks.
# DV1-048: Standard Django groups and optional template default.
# DV1-015: Startup ownership-group membership validation.
# DV1-016: Reuse current ownership checks during diary creation.
def validate_task_owner_roles():
    """Check that every configured ownership group exists and contains a user.
    Raise ImproperlyConfigured for missing groups, empty groups, or unavailable database checks.
    Leave groups and memberships unchanged.
    """
    roles = task_owner_roles()

    # Projects without role ownership need no ownership-group database lookup.
    if not roles:
        return
    try:
        members = get_user_model()._base_manager.filter(groups=OuterRef('pk'))
        existing = dict(Group.objects.filter(name__in=roles).annotate(
            has_members=Exists(members)).values_list('name', 'has_members'))
    except DatabaseError as error:
        raise ImproperlyConfigured(
            'Diary cannot validate DIARY_TASK_OWNER_ROLES against the database. '
            'Check the database connection, apply migrations, and populate the configured roles before continuing.'
        ) from error
    missing = roles - existing.keys()

    # Existing ownership groups must have a member independently of the access groups.
    empty = {name for name, populated in existing.items() if not populated}
    problems = []

    # Absent configured ownership groups prevent ordinary application startup.
    if missing:
        problems.append('Roles missing from the database: ' + ', '.join(sorted(missing)) + '.')

    # Empty groups need user assignments, so report them separately from absent groups.
    if empty:
        problems.append('Empty roles with no members: ' + ', '.join(sorted(empty)) + '.')

    # Report all invalid ownership groups together without silently changing template assignments.
    if problems:
        raise ImproperlyConfigured(
            'DIARY_TASK_OWNER_ROLES validation failed. ' + ' '.join(problems)
            + ' Create missing groups and add at least one user to each configured role before continuing.'
        )
