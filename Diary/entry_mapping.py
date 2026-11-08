"""Convert entry specifications and validate proposed task ownership."""
from dataclasses import asdict
from uuid import UUID

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError

from .choices import OwnerKind
from .models import Milestone
from .roles import access_groups, task_owner_roles


class EntryMapper:
    """Map entry input and stored entries without copying completion or audit records.
    The methods use an explicit snapshot field list and do not retain state.
    """

    SNAPSHOT_FIELDS = (
        'entry_key', 'name', 'description', 'date_kind', 'milestone_id', 'month', 'day',
        'year_offset', 'day_offset', 'fixed_date', 'owner_kind', 'person_ref', 'role_ref', 'source_task_key',
    )

    @staticmethod
    def to_model_fields(spec):
        """Return model creation fields for an EntrySpec.
        Resolve its named milestone once when the rule needs one.
        Raise Milestone.DoesNotExist for an unknown milestone name.
        """
        values = asdict(spec)
        if values['source_task_key'] is not None:
            try:
                values['source_task_key'] = UUID(str(values['source_task_key']))
            except (TypeError, ValueError, AttributeError) as error:
                raise ValidationError('Supply a valid source task key.') from error
        name = values.pop('milestone_name')

        # Fixed-date rules have no milestone reference to resolve.
        values['milestone'] = Milestone.objects.get(name=name) if name else None
        return values

    # DV1-004: Named diary creation and template snapshots.
    @classmethod
    def snapshot_fields(cls, entry):
        """Return reusable identity, text, date rule, and ownership fields from a stored entry.
        Read milestone_id directly without loading the related milestone object.
        Exclude database container keys, completion records, and audit metadata.
        """
        return {name: getattr(entry, name) for name in cls.SNAPSHOT_FIELDS}

    @classmethod
    def matches_spec(cls, entry, spec):
        """Return whether the stored entry has the same reusable fields as an EntrySpec.
        Resolve the input milestone once and compare foreign keys as UUIDs.
        Leave both the input and stored entry unchanged.
        Unknown milestone names raise Milestone.DoesNotExist.
        """
        fields = cls.to_model_fields(spec)
        milestone = fields.pop('milestone')

        # Compare relation identities while keeping fixed-date rules independent of milestones.
        fields['milestone_id'] = milestone.pk if milestone else None
        return cls.snapshot_fields(entry) == fields


# DV1-005: Ownership data and assignment checks.
# DV1-048: Standard Django groups and optional template default.
def validate_entry_owner(spec, directory=None):
    """Validate ownership before saving an entry.
    Person references require directory eligibility checks.
    Roles must be configured and exist as Django groups.
    Raise ValidationError for unavailable or ineligible ownership references.
    """

    # Whole-team ownership has no person or role reference to resolve.
    if spec.owner_kind == OwnerKind.TEAM:
        return

    # Opaque person references need the caller eligibility contract.
    if spec.owner_kind == OwnerKind.PERSON:

        # Reject person assignments when no eligibility check is available.
        if directory is None:
            raise ValidationError('Supply an owner directory for a person assignment.')

        # Person owners must qualify through the configured user or manager group.
        if not directory.person_in_groups(spec.person_ref, frozenset(access_groups().values())):
            raise ValidationError('Select a DiaryUser or DiaryManager.')

    # Role assignments use configured names and the standard Django group database.
    elif spec.owner_kind == OwnerKind.ROLE:

        # A database group alone must not bypass the configured ownership role list.
        if spec.role_ref not in task_owner_roles():
            raise ValidationError('Select a role from DIARY_TASK_OWNER_ROLES.')

        # A group may have disappeared since startup, so assignment checks its current existence.
        if not Group.objects.filter(name=spec.role_ref).exists():
            raise ValidationError('Select an existing role.')
