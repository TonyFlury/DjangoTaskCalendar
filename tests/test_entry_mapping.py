"""Test entry mapping and ownership validation against PostgreSQL."""
from dataclasses import replace
from datetime import date
from unittest.mock import Mock

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from Diary import api
from Diary.choices import DateKind, OwnerKind, VersionStatus
from Diary.entry_mapping import EntryMapper, validate_entry_owner
from Diary.models import CalendarEntry, CalendarMilestone, CalendarTemplate, EventCalendar, Milestone, TemplateEntry, \
    TemplateVersion


# Verifies DV1-005: Ownership data and assignment checks.
@override_settings(DIARY_MANAGER='Managers', DIARY_USER='Users', DIARY_TASK_OWNER_ROLES=('Owners',))
class EntryMappingTests(TestCase):
    """Verify entry conversion, snapshot isolation, query costs, and ownership checks."""

    def setUp(self):
        """Create matching stored entries with a completed instance record and an unloaded milestone relation."""
        self.milestone = Milestone.objects.create(name='mapping_target', label='Mapping target')
        template = CalendarTemplate.objects.create(name='Mapping template')
        version = TemplateVersion.objects.create(template=template, number=1, created_by_ref='manager')
        self.spec = api.EntrySpec(
            'Preparation', DateKind.RELATIVE, milestone_name='mapping_target', day_offset=-2,
        )
        source = TemplateEntry.objects.create(
            version=version, entry_key=self.spec.entry_key, name=self.spec.name,
            date_kind=DateKind.RELATIVE, milestone=self.milestone, day_offset=-2,
        )
        version.status = VersionStatus.APPROVED
        version.approved_at = timezone.now()
        version.approved_by_ref = 'manager'
        version.save()
        calendar = EventCalendar.objects.create(
            event_ref='mapping:1', name='Mapping diary', event_year=2027,
            template_version=version, created_by_ref='manager',
        )
        CalendarMilestone.objects.create(calendar=calendar, milestone=self.milestone, date=date(2027, 6, 27))
        entry = CalendarEntry.objects.create(
            calendar=calendar, source_entry=source, entry_key=self.spec.entry_key, name=self.spec.name,
            date_kind=DateKind.RELATIVE, milestone=self.milestone, day_offset=-2,
            created_by_ref='manager', completed_at=timezone.now(), completed_by_ref='manager',
        )
        self.template_entry = TemplateEntry.objects.get(pk=source.pk)
        self.diary_entry = CalendarEntry.objects.get(pk=entry.pk)
        self.actor = api.Actor('manager', frozenset({'Managers'}), frozenset({calendar.pk}))

    def test_model_fields_resolve_the_named_milestone_once(self):
        """Convert a milestone specification without altering its input fields."""
        with self.assertNumQueries(1):
            fields = EntryMapper.to_model_fields(self.spec)
        self.assertEqual(fields['milestone'].pk, self.milestone.pk)
        self.assertNotIn('milestone_name', fields)
        self.assertEqual(fields['entry_key'], self.spec.entry_key)
        self.assertEqual(self.spec.milestone_name, 'mapping_target')

    def test_fixed_date_conversion_needs_no_milestone_query(self):
        """Keep annual rules independent of milestone lookup."""
        spec = api.EntrySpec('Annual', DateKind.ANNUAL, month=3, day=1)
        with self.assertNumQueries(0):
            fields = EntryMapper.to_model_fields(spec)
        self.assertIsNone(fields['milestone'])
        self.assertEqual((fields['month'], fields['day']), (3, 1))

    # Verifies DV1-004: Named diary creation and template snapshots.
    def test_snapshots_exclude_history_and_do_not_load_milestones(self):
        """Copy reusable fields without querying relations or copying completion and container records."""
        self.assertNotIn('milestone', self.template_entry._state.fields_cache)
        self.assertNotIn('milestone', self.diary_entry._state.fields_cache)
        with self.assertNumQueries(0):
            template_fields = EntryMapper.snapshot_fields(self.template_entry)
            diary_fields = EntryMapper.snapshot_fields(self.diary_entry)
        self.assertEqual(template_fields, diary_fields)
        self.assertEqual(diary_fields['milestone_id'], self.milestone.pk)
        excluded = {
            'id', 'calendar_id', 'version_id', 'source_entry_id', 'created_at', 'created_by_ref',
            'completed_at', 'completed_by_ref', 'completed_due_date',
        }
        self.assertFalse(excluded & diary_fields.keys())
        self.assertIsNotNone(self.diary_entry.completed_at)
        self.assertEqual(self.diary_entry.completed_due_date, date(2027, 6, 25))

    def test_comparison_uses_ids_and_ignores_completion_metadata(self):
        """Recognize matching payloads and reject changed content with one milestone lookup."""
        with self.assertNumQueries(1):
            self.assertTrue(EntryMapper.matches_spec(self.diary_entry, self.spec))
        changed = replace(self.spec, name='Changed preparation')
        with self.assertNumQueries(1):
            self.assertFalse(EntryMapper.matches_spec(self.diary_entry, changed))
        self.assertNotIn('milestone', self.diary_entry._state.fields_cache)

    def test_repeated_api_additions_do_not_resolve_milestones_twice(self):
        """Verify the template and diary addition paths each perform one milestone lookup."""
        version = api.DiaryTemplateVersion(actor=self.actor, key=self.template_entry.version_id)
        diary = api.DiaryInstance(actor=self.actor, key=self.diary_entry.calendar_id)
        for target in (version, diary):
            with CaptureQueriesContext(connection) as captured:
                self.assertEqual(target.add_entry(spec=self.spec), self.spec.entry_key)

            # Count milestone reads separately from authorization, locks, and transaction statements.
            milestone_queries = [query for query in captured if f'FROM "{Milestone._meta.db_table}"' in query['sql']]
            self.assertEqual(len(milestone_queries), 1)

    def test_person_validation_requires_a_qualified_directory_result(self):
        """Reject unchecked person references and pass configured role names to the directory."""
        person = replace(self.spec, owner_kind=OwnerKind.PERSON, person_ref='user:42')
        with self.assertRaisesMessage(ValidationError, 'owner directory'):
            validate_entry_owner(person)
        directory = Mock()
        directory.person_in_groups.return_value = False
        with self.assertRaisesMessage(ValidationError, 'DiaryUser or DiaryManager'):
            validate_entry_owner(person, directory)
        directory.person_in_groups.return_value = True
        self.assertIsNone(validate_entry_owner(person, directory))
        directory.person_in_groups.assert_called_with('user:42', frozenset({'Managers', 'Users'}))

    def test_role_validation_uses_configured_django_groups(self):
        """Check role configuration and current group existence without a person directory."""
        role = replace(self.spec, owner_kind=OwnerKind.ROLE, role_ref='Owners')
        with self.assertRaisesMessage(ValidationError, 'existing role'):
            validate_entry_owner(role)
        Group.objects.create(name='Owners')
        self.assertIsNone(validate_entry_owner(role))
        with self.settings(DIARY_TASK_OWNER_ROLES=()):
            with self.assertRaisesMessage(ValidationError, 'DIARY_TASK_OWNER_ROLES'):
                validate_entry_owner(role)

    def test_whole_team_validation_needs_no_directory_or_database(self):
        """Leave unassigned whole-team work independent of person and role resolution."""
        with self.assertNumQueries(0):
            self.assertIsNone(validate_entry_owner(self.spec))
