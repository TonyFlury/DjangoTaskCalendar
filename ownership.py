"""DV1-040: Identify tasks that require an explicit manager ownership review."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef

from .choices import OwnerKind
from .roles import access_groups, task_owner_roles


def orphaned_entry_keys(entries, *, directory):
    """Return open task keys whose person or configured role has no eligible active owner.
    Use the supplied directory for person references and Django groups for role membership.
    Keep diary additions, completed tasks, and whole-team tasks outside ownership recovery.
    """
    entries = tuple(entries)
    people = {}
    eligible_users = get_user_model()._default_manager.filter(
        is_active=True, groups__name=access_groups()['user']).filter(groups=OuterRef('pk'))
    active_roles = set(Group.objects.filter(name__in=task_owner_roles()).annotate(
        has_eligible_member=Exists(eligible_users)).filter(has_eligible_member=True).values_list('name', flat=True))
    orphaned = set()
    for entry in entries:

        # DV1-040: Only open template copies require manager ownership recovery.
        if entry.get('source') != 'template' or entry['completed_at'] is not None:
            continue

        # A person must remain an active member of the configured DiaryUser group.
        if entry['owner_kind'] == OwnerKind.PERSON:
            reference = entry['person_ref']

            # Cache each directory result within this inspection without retaining stale membership decisions.
            if reference not in people:

                # Opaque person references require the host's eligibility adapter.
                if directory is None:
                    raise ValidationError('Supply an owner directory to review person ownership.')
                people[reference] = directory.person_in_groups(reference, frozenset({access_groups()['user']}))

            # An unavailable or ineligible person requires an explicit replacement.
            if not people[reference]:
                orphaned.add(entry['entry_key'])

        # Missing, unconfigured, or empty eligible ownership groups also need manager review.
        elif entry['owner_kind'] == OwnerKind.ROLE and entry['role_ref'] not in active_roles:
            orphaned.add(entry['entry_key'])
    return frozenset(orphaned)
