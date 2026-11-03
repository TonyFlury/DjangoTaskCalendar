"""Verify current ownership validation and atomic diary creation."""
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured, PermissionDenied, ValidationError
from django.db import OperationalError
from django.test import TestCase, override_settings

from Diary.api import Actor, DiaryAPI, DiaryInstance, EntrySpec
from Diary.choices import DateKind, OwnerKind
from Diary.models import CalendarEntry, CalendarMilestone, EntryDependency, EventCalendar
from Diary.roles import validate_task_owner_roles


# Verifies DV1-016: Current ownership checks and transaction safety during diary creation.
@override_settings(DIARY_MANAGER='Managers', DIARY_USER='Users', DIARY_TASK_OWNER_ROLES=('Owners', 'OtherOwners'))
class DiaryCreationValidationTests(TestCase):
    """Exercise both creation factories after ownership configuration changes at runtime."""

    def setUp(self):
        """Create populated ownership groups and an approved template with dates and dependencies."""
        self.owners = Group.objects.create(name='Owners')
        self.other_owners = Group.objects.create(name='OtherOwners')
        model = get_user_model()
        self.member = model._default_manager.create_user(**{model.USERNAME_FIELD: 'creation-owner@example.test'})
        self.member.groups.add(self.owners, self.other_owners)
        self.actor = Actor('manager', frozenset({'Managers'}))
        self.api = DiaryAPI(actor=self.actor)
        template = self.api.create_template(name='Creation validation')
        self.version = template.create_version(number=1)
        self.api.define_milestones(definitions={'target': 'Target'})
        self.first = EntrySpec('Prepare', DateKind.RELATIVE, milestone_name='target', day_offset=-2,
                               owner_kind=OwnerKind.ROLE, role_ref='Owners')
        self.second = EntrySpec('Review', DateKind.SOURCE, milestone_name='target',
                                owner_kind=OwnerKind.ROLE, role_ref='OtherOwners')
        self.version.add_entry(spec=self.first)
        self.version.add_entry(spec=self.second)
        self.version.set_predecessors(entry_key=self.second.entry_key, predecessor_keys=[self.first.entry_key])
        self.version.approve()
        validate_task_owner_roles()

    def create(self, reference='creation:1', direct=False):
        """Create through the API context or directly through the instance factory."""
        values = {'event_ref': reference, 'name': 'Creation diary', 'event_year': 2027,
                  'milestone_dates': {'target': date(2027, 6, 1)}, 'template_version_key': self.version.key}

        # Both public entry points must enforce identical ownership checks.
        if direct:
            return DiaryInstance.create(actor=self.actor, **values)
        return self.api.create_diary(**values)

    def snapshot(self):
        """Return diary data so failures can be checked for complete transaction rollback."""
        return {model.__name__: tuple(model.objects.order_by('pk').values())
                for model in (EventCalendar, CalendarEntry, CalendarMilestone, EntryDependency)}

    def test_both_factories_create_complete_snapshots_with_populated_groups(self):
        """Create named diaries, milestone dates, task copies, and predecessor links through both factories."""
        for direct in (False, True):
            with self.subTest(direct=direct):
                diary = self.create(reference=f'valid:{direct}', direct=direct)
                calendar = EventCalendar.objects.get(pk=diary.key)
                self.assertEqual(calendar.entries.count(), 2)
                self.assertEqual(calendar.milestone_dates.get().date, date(2027, 6, 1))
                self.assertEqual(EntryDependency.objects.filter(entry__calendar=calendar).count(), 1)

    def test_both_factories_reject_groups_emptied_after_startup(self):
        """Recheck current membership rather than reuse an earlier successful startup result."""
        self.member.groups.remove(self.owners)
        before = self.snapshot()
        for direct in (False, True):
            with self.subTest(direct=direct):
                with self.assertRaisesMessage(ImproperlyConfigured, 'Empty roles with no members: Owners.'):
                    self.create(direct=direct)
                self.assertEqual(self.snapshot(), before)

    def test_both_factories_reject_groups_deleted_after_startup(self):
        """Reject a configured role that disappeared without retaining any diary records."""
        self.other_owners.delete()
        before = self.snapshot()
        for direct in (False, True):
            with self.subTest(direct=direct):
                with self.assertRaisesMessage(ImproperlyConfigured, 'Roles missing from the database: OtherOwners.'):
                    self.create(direct=direct)
                self.assertEqual(self.snapshot(), before)

    def test_new_configuration_is_validated_even_if_no_template_task_uses_the_role(self):
        """Check every currently configured ownership role rather than only template references."""
        with self.settings(DIARY_TASK_OWNER_ROLES=('Owners', 'OtherOwners', 'NewRole')):
            with self.assertRaisesMessage(ImproperlyConfigured, 'NewRole'):
                self.create()
        self.assertFalse(EventCalendar.objects.exists())

    def test_repeated_creation_rechecks_roles_without_changing_existing_diary(self):
        """Reject invalid configuration on retries while preserving the original diary snapshot."""
        original = self.create()
        before = self.snapshot()
        self.member.groups.remove(self.owners)
        for direct in (False, True):
            with self.subTest(direct=direct):
                with self.assertRaisesMessage(ImproperlyConfigured, 'Empty roles'):
                    self.create(direct=direct)
                self.assertEqual(self.snapshot(), before)
        self.member.groups.add(self.owners)
        self.assertEqual(self.create(direct=True).key, original.key)
        self.assertEqual(self.snapshot(), before)

    def test_repairing_membership_allows_creation_without_restarting(self):
        """Read repaired ownership membership on the next creation call."""
        self.member.groups.clear()
        with self.assertRaisesMessage(ImproperlyConfigured, 'Empty roles'):
            self.create()
        self.member.groups.add(self.owners, self.other_owners)
        diary = self.create()
        self.assertTrue(EventCalendar.objects.filter(pk=diary.key).exists())

    def test_denied_caller_cannot_trigger_ownership_validation(self):
        """Check caller permission before exposing ownership configuration details."""
        outsider = Actor('outsider', frozenset())
        with patch('Diary.api._validate_task_owner_roles') as validate:
            with self.assertRaises(PermissionDenied):
                DiaryInstance.create(actor=outsider, event_ref='denied', name='Denied', event_year=2027,
                                     milestone_dates={}, template_version_key=self.version.key)
        validate.assert_not_called()
        self.assertFalse(EventCalendar.objects.exists())

    def test_database_failure_during_validation_leaves_no_diary(self):
        """Reject unavailable ownership checks before writing a diary snapshot."""
        before = self.snapshot()
        with patch('django.db.models.query.QuerySet._fetch_all', side_effect=OperationalError('Unavailable')):
            with self.assertRaisesMessage(ImproperlyConfigured, 'DIARY_TASK_OWNER_ROLES'):
                self.create()
        self.assertEqual(self.snapshot(), before)

    def test_copy_failure_rolls_back_diary_dates_and_earlier_task_copies(self):
        """Keep the entire creation atomic if a later task copy fails after successful validation."""
        before = self.snapshot()
        create_entry = CalendarEntry.objects.create
        copies = []

        def fail_second_copy(*args, **kwargs):
            """Save the first task copy and reject the second to exercise transaction rollback."""
            copies.append(kwargs)

            # The first saved copy must disappear when the second copy causes transaction failure.
            if len(copies) == 2:
                raise ValidationError('Task copy failed.')
            return create_entry(*args, **kwargs)

        with patch.object(CalendarEntry.objects, 'create', side_effect=fail_second_copy):
            with self.assertRaisesMessage(ValidationError, 'Task copy failed.'):
                self.create()
        self.assertEqual(len(copies), 2)
        self.assertEqual(self.snapshot(), before)
