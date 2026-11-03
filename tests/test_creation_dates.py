"""Verify year-free creation and fixed-date calculations. DV1-051."""
from dataclasses import replace
from datetime import date, datetime, timezone as datetime_timezone
from importlib import import_module
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from Diary.api import Actor, DiaryAPI, EntrySpec
from Diary.choices import DateKind
from Diary.date_rules import next_annual_date
from Diary.models import CalendarEntry, EventCalendar


class FixedDateCalculationTests(SimpleTestCase):
    """Check strict date boundaries, leap days, offsets, and calendar limits."""

    def test_next_matching_date_and_offsets(self):
        """Find the next valid date before applying the explicit year offset."""
        cases = (
            (date(2026, 11, 3), 4, 1, 0, date(2027, 4, 1)),
            (date(2026, 3, 31), 4, 1, 0, date(2026, 4, 1)),
            (date(2026, 4, 1), 4, 1, 0, date(2027, 4, 1)),
            (date(2026, 12, 31), 1, 1, 0, date(2027, 1, 1)),
            (date(2026, 11, 3), 2, 29, 0, date(2028, 2, 29)),
            (date(2096, 2, 29), 2, 29, 0, date(2104, 2, 29)),
            (date(2026, 11, 3), 4, 1, -1, date(2026, 4, 1)),
            (date(2026, 11, 3), 4, 1, 1, date(2028, 4, 1)),
            (date(2026, 11, 3), 2, 29, 1, None),
            (date(2026, 11, 3), 4, 31, 0, None),
            (date(9999, 12, 31), 1, 1, 0, None),
            (date(1, 1, 1), 4, 1, -1, None),
        )
        for created, month, day, offset, expected in cases:
            with self.subTest(created=created, month=month, day=day, offset=offset):
                self.assertEqual(next_annual_date(creation_date=created, month=month, day=day,
                                                  year_offset=offset), expected)


@override_settings(DIARY_MANAGER='Managers', DIARY_USER='Users', DIARY_TASK_OWNER_ROLES=(),
                   DIARY_TIME_ZONE='Europe/London', TIME_ZONE='UTC')
class DiaryCreationDateTests(TestCase):
    """Verify stored fixed dates through both public diary creation factories."""

    def setUp(self):
        """Prepare an approved template with one annual task and one milestone task."""
        self.actor = Actor('manager', frozenset({'Managers'}))
        self.api = DiaryAPI(actor=self.actor)
        self.api.define_milestones(definitions={'target': 'Target date'})
        self.version = self.api.create_template(name='Creation dates').create_version(number=1)
        self.fixed = EntrySpec('Fixed April date', DateKind.ANNUAL, month=4, day=1)
        self.version.add_entry(spec=self.fixed)
        self.version.add_entry(spec=EntrySpec('Milestone task', DateKind.SOURCE, milestone_name='target'))
        self.version.approve()

    def create(self, instant, **kwargs):
        """Create a diary at a fixed instant and return its permitted API reference."""
        with patch('django.utils.timezone.now', return_value=instant):
            created = self.api.create_diary(name='Year-free diary', milestone_dates={},
                                            template_version_key=self.version.key, **kwargs)
        actor = replace(self.actor, calendar_keys=frozenset({created.key}))
        return DiaryAPI(actor=actor).diary(key=created.key)

    def test_creation_requires_no_year_or_host_reference(self):
        """Create independent diaries and calculate 1 April 2027 from 3 November 2026."""
        instant = datetime(2026, 11, 3, 12, tzinfo=datetime_timezone.utc)
        first = self.create(instant)
        second = self.create(instant)
        self.assertNotEqual(first.key, second.key)
        self.assertNotIn('event_year', first.read())
        self.assertNotIn('event_year', {field.name for field in EventCalendar._meta.fields})
        entry = CalendarEntry.objects.get(calendar_id=first.key, entry_key=self.fixed.entry_key)
        self.assertEqual(entry.due_date, date(2027, 4, 1))
        self.assertEqual(entry.annual_due_date, date(2027, 4, 1))
        self.assertIsNone(entry.milestone_id)
        self.assertEqual([item['name'] for item in self.version.required_milestones()], ['target'])

    def test_matching_creation_day_uses_the_following_year(self):
        """Use a later occurrence when the template date matches the local creation day."""
        diary = self.create(datetime(2026, 4, 1, 12, tzinfo=datetime_timezone.utc))
        self.assertEqual(CalendarEntry.objects.get(calendar_id=diary.key, entry_key=self.fixed.entry_key).due_date,
                         date(2027, 4, 1))

    def test_creation_uses_diary_zone_and_project_fallback(self):
        """Keep active user zones separate from the configured creation-date time zone."""
        instant = datetime(2026, 3, 31, 23, 30, tzinfo=datetime_timezone.utc)
        with timezone.override('America/Los_Angeles'):
            local = self.create(instant)
            with self.settings(DIARY_TIME_ZONE=None):
                del settings.DIARY_TIME_ZONE
                project = self.create(instant)
        self.assertEqual(CalendarEntry.objects.get(calendar_id=local.key, entry_key=self.fixed.entry_key).due_date,
                         date(2027, 4, 1))
        self.assertEqual(CalendarEntry.objects.get(calendar_id=project.key, entry_key=self.fixed.entry_key).due_date,
                         date(2026, 4, 1))

    def test_reads_retries_and_later_additions_preserve_creation_date(self):
        """Keep saved annual dates stable after time passes or milestone values change."""
        diary = self.create(datetime(2026, 11, 3, 12, tzinfo=datetime_timezone.utc), event_ref='stable-date')
        original = diary.read()['entries']
        with patch('django.utils.timezone.now', return_value=datetime(2028, 5, 1, tzinfo=datetime_timezone.utc)):
            retried = self.api.create_diary(name='Year-free diary', milestone_dates={},
                                            template_version_key=self.version.key, event_ref='stable-date')
            self.assertEqual(retried.key, diary.key)
            self.assertEqual(diary.read()['entries'], original)

            # DV1-043: Rejected milestone changes preserve the annual snapshot.
            with self.assertRaises(ValidationError):
                diary.set_milestone_dates(milestone_dates={'target': date(2030, 5, 1)})
            added = EntrySpec('Later addition', DateKind.ANNUAL, month=4, day=1)
            self.assertEqual(diary.add_entry(spec=added), added.entry_key)
            self.assertEqual(diary.add_entry(spec=added), added.entry_key)
        for entry in CalendarEntry.objects.filter(calendar_id=diary.key, date_kind=DateKind.ANNUAL):
            self.assertEqual(entry.due_date, date(2027, 4, 1))


class DiaryYearMigrationTests(TestCase):
    """Verify the actual migration against historical tables in an isolated PostgreSQL schema."""

    def test_migration_preserves_existing_dates_and_completion_records(self):
        """Remove the old year while retaining valid, invalid, and completed annual dates."""
        self.assertEqual(connection.vendor, 'postgresql')
        state = MigrationExecutor(connection).loader.project_state([('Diary', '0003_calendar_closure')])
        migration = import_module('Diary.migrations.0004_milestone_dates_without_diary_year').Migration(
            '0004_milestone_dates_without_diary_year', 'Diary',
        )
        with connection.cursor() as cursor:
            cursor.execute('SHOW search_path')
            original_path = cursor.fetchone()[0]
            cursor.execute('CREATE SCHEMA diary_year_migration_test')
            cursor.execute('SET search_path TO diary_year_migration_test')
        try:
            with connection.schema_editor() as editor:
                for model in state.apps.get_app_config('Diary').get_models():
                    editor.create_model(model)
            templates = state.apps.get_model('Diary', 'CalendarTemplate')
            versions = state.apps.get_model('Diary', 'TemplateVersion')
            calendars = state.apps.get_model('Diary', 'EventCalendar')
            entries = state.apps.get_model('Diary', 'CalendarEntry')
            template = templates.objects.create(name='Old template')
            instant = datetime(2026, 11, 3, tzinfo=datetime_timezone.utc)
            version = versions.objects.create(template=template, number=1, status='approved',
                                               created_by_ref='manager', approved_by_ref='manager', approved_at=instant)
            calendar = calendars.objects.create(template_version=version, event_ref='legacy', name='Old diary',
                                                  event_year=2027, created_by_ref='manager')
            normal = entries.objects.create(calendar=calendar, name='April', date_kind='annual', month=4, day=1,
                                              created_by_ref='manager')
            missing = entries.objects.create(calendar=calendar, name='Invalid leap day', date_kind='annual',
                                               month=2, day=29, created_by_ref='manager')
            completed = entries.objects.create(calendar=calendar, name='Completed', date_kind='annual',
                                                 month=12, day=1, year_offset=-1, created_by_ref='manager',
                                                 completed_at=instant, completed_by_ref='manager',
                                                 completed_due_date=date(2026, 12, 1))
            with connection.cursor() as cursor:
                cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            with connection.schema_editor() as editor:
                migrated = migration.apply(state, editor)
            current = migrated.apps.get_model('Diary', 'CalendarEntry')
            self.assertEqual(current.objects.get(pk=normal.pk).annual_due_date, date(2027, 4, 1))
            self.assertIsNone(current.objects.get(pk=missing.pk).annual_due_date)
            saved = current.objects.get(pk=completed.pk)
            self.assertEqual(saved.annual_due_date, date(2026, 12, 1))
            self.assertEqual(saved.completed_due_date, date(2026, 12, 1))
            self.assertEqual(saved.completed_at, instant)
            self.assertEqual(saved.completed_by_ref, 'manager')
            self.assertNotIn('event_year', {
                field.name for field in migrated.apps.get_model('Diary', 'EventCalendar')._meta.fields
            })
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f'SET search_path TO {original_path}')
                cursor.execute('DROP SCHEMA diary_year_migration_test CASCADE')
