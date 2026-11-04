"""Requirements follow task usage; hosts may supply the full milestone catalogue."""
from datetime import date, datetime, timezone
from importlib import import_module

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, override_settings

from Diary.api import Actor, DiaryAPI, DiaryInstance, DiaryTemplateVersion, EntrySpec
from Diary.choices import DateKind
from Diary.models import EventCalendar, Milestone, TemplateMilestone, TemplateVersion


@override_settings(DIARY_MANAGER='Managers', DIARY_USER='Users', DIARY_TASK_OWNER_ROLES=())
class TemplateMilestoneTests(TestCase):
    def setUp(self):
        self.actor = Actor('manager', frozenset({'Managers'}))
        self.api = DiaryAPI(actor=self.actor)
        self.api.define_milestones(definitions={'event': 'Event date', 'booking': 'Bookings close', 'other': 'Other'})
        self.template = self.api.create_template(name='Explicit requirements')
        self.version = self.template.create_version(number=1, milestone_names=('event', 'booking'))
        self.task = EntrySpec('Prepare', DateKind.RELATIVE, milestone_name='event', day_offset=-7)

    def create(self, dates, direct=False):
        values = dict(name='Diary', event_ref='requirements:1', milestone_dates=dates,
                      template_version_key=self.version.key)
        return DiaryInstance.create(actor=self.actor, **values) if direct else self.api.create_diary(**values)

    def test_discovery_uses_tasks_not_legacy_declarations(self):
        self.assertEqual(self.version.required_milestones(), ())
        self.version.add_entry(spec=self.task)
        self.assertEqual([item['name'] for item in self.version.required_milestones()], ['event'])
        self.version.approve()
        self.assertEqual([item['name'] for item in self.template.editor_data()['milestones']], ['event'])

    def test_factories_validate_used_dates_and_ignore_all_extras(self):
        self.version.add_entry(spec=self.task)
        self.version.approve()
        for direct in (False, True):
            for dates in ({}, {'event': None}, {'event': '2027-06-01'}, {'event': datetime(2027, 6, 1)}):
                with self.subTest(direct=direct, dates=dates):
                    with self.assertRaises(ValidationError):
                        self.create(dates, direct)
                    self.assertFalse(EventCalendar.objects.exists())
        required = {'event': date(2027, 6, 1)}
        first = self.create({**required, 'booking': None, 'unknown': object()})
        self.assertEqual(self.create({**required, 'booking': 'changed'}, True).key, first.key)
        self.assertEqual(EventCalendar.objects.get(pk=first.key).date_context(), required)
        self.assertEqual(self.create(required).key, first.key)

    def test_empty_template_requires_no_dates(self):
        self.version.approve()
        diary = self.create({'event': None, 'booking': 'ignored'})
        self.assertFalse(EventCalendar.objects.get(pk=diary.key).entries.exists())
        self.assertEqual(EventCalendar.objects.get(pk=diary.key).date_context(), {})

    def test_any_catalogue_task_is_accepted_and_typos_are_rejected(self):
        with self.assertRaises(ObjectDoesNotExist):
            self.version.add_entry(spec=EntrySpec('Typo', DateKind.SOURCE, milestone_name='evnet'))
        self.version.add_entry(spec=EntrySpec('Other source', DateKind.SOURCE, milestone_name='other'))
        self.version.approve()
        self.assertEqual([item['name'] for item in self.version.required_milestones()], ['other'])
        self.assertEqual(Milestone.objects.count(), 3)

    def test_draft_removal_rejects_used_requirement_and_allows_unused_requirement(self):
        self.version.add_entry(spec=self.task)
        with self.assertRaises(ValidationError):
            self.version.set_milestones(names=('booking',))
        self.version.set_milestones(names=('event',))
        self.assertEqual([item['name'] for item in self.version.required_milestones()], ['event'])

    def test_approved_declarations_reject_api_model_and_bulk_changes(self):
        self.version.add_entry(spec=self.task)
        self.version.approve()
        with self.assertRaises(ValidationError):
            self.version.set_milestones(names=())
        declaration = TemplateMilestone.objects.filter(version_id=self.version.key).first()
        with self.assertRaises(ValidationError):
            declaration.delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            TemplateMilestone.objects.filter(pk=declaration.pk).delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            TemplateVersion.objects.get(pk=self.version.key).milestones.add(Milestone.objects.get(name='other'))

    def test_version_save_preserves_unused_requirements_and_can_change_new_version(self):
        self.version.add_entry(spec=self.task)
        self.version.approve()
        newer = self.template.save_version(entries=(self.task,), predecessors={},
                                            expected_version_key=self.version.key)
        self.assertEqual(newer.required_milestones(), self.version.required_milestones())
        latest = self.template.save_version(entries=(self.task,), predecessors={},
            expected_version_key=newer.key, milestone_names=('event',))
        self.assertEqual([item['name'] for item in latest.required_milestones()], ['event'])
        self.assertEqual(len(self.version.required_milestones()), 1)
        empty = self.template.save_version(entries=(), predecessors={}, expected_version_key=latest.key)
        self.assertEqual(empty.required_milestones(), ())
        self.assertEqual([item['name'] for item in latest.required_milestones()], ['event'])

    def test_user_cannot_declare_requirements(self):
        version = DiaryTemplateVersion(actor=Actor('user', frozenset({'Users'})), key=self.version.key)
        with self.assertRaises(PermissionDenied):
            version.set_milestones(names=('other',))


class TemplateMilestoneMigrationTests(TestCase):
    def test_backfill_preserves_versions_and_live_diaries(self):
        """Apply the real migration in an isolated PostgreSQL schema to legacy data."""
        state = MigrationExecutor(connection).loader.project_state([('Diary', '0007_freeze_live_milestones')])
        migration = import_module('Diary.migrations.0008_template_milestones').Migration(
            '0008_template_milestones', 'Diary')
        with connection.cursor() as cursor:
            cursor.execute('SHOW search_path')
            original_path = cursor.fetchone()[0]
            cursor.execute('CREATE SCHEMA diary_requirement_migration_test')
            cursor.execute('SET search_path TO diary_requirement_migration_test')
        try:
            with connection.schema_editor() as editor:
                for model in state.apps.get_app_config('Diary').get_models():
                    editor.create_model(model)
            template = state.apps.get_model('Diary', 'CalendarTemplate').objects.create(name='Legacy')
            version_model = state.apps.get_model('Diary', 'TemplateVersion')
            version = version_model.objects.create(template=template, number=1, created_by_ref='manager',
                status='approved', approved_by_ref='manager', approved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
            empty = version_model.objects.create(template=template, number=2, created_by_ref='manager')
            milestone = state.apps.get_model('Diary', 'Milestone').objects.create(name='event', label='Event')
            entries = state.apps.get_model('Diary', 'TemplateEntry')
            for name in ('First', 'Second'):
                entries.objects.create(version=version, name=name, date_kind='source', milestone=milestone)
            calendars = state.apps.get_model('Diary', 'EventCalendar')
            calendar = calendars.objects.create(template_version=version, name='Old diary', event_ref='old',
                                                created_by_ref='manager')
            dates = state.apps.get_model('Diary', 'CalendarMilestone')
            dates.objects.create(calendar=calendar, milestone=milestone, date=None)
            before = list(calendars.objects.values()), list(dates.objects.values())
            with connection.cursor() as cursor:
                cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            with connection.schema_editor() as editor:
                new_state = migration.apply(state, editor)
            declarations = new_state.apps.get_model('Diary', 'TemplateMilestone')
            self.assertEqual(list(declarations.objects.values_list('version_id', 'milestone_id')),
                             [(version.pk, milestone.pk)])
            self.assertFalse(declarations.objects.filter(version_id=empty.pk).exists())
            self.assertEqual((list(calendars.objects.values()), list(dates.objects.values())), before)
            # Simulate an old approved version with an explicit unused requirement.
            unused = state.apps.get_model('Diary', 'Milestone').objects.create(name='unused', label='Unused')
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE "Diary_templatemilestone" DISABLE TRIGGER diary_template_milestone_write_guard')
            declarations.objects.create(version_id=version.pk, milestone_id=unused.pk)
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE "Diary_templatemilestone" ENABLE TRIGGER diary_template_milestone_write_guard')
                cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            derived = import_module('Diary.migrations.0011_derive_template_milestones').Migration(
                '0011_derive_template_milestones', 'Diary')
            with connection.schema_editor() as editor:
                derived.apply(new_state, editor)
            self.assertEqual(list(declarations.objects.values_list('version_id', 'milestone_id')),
                             [(version.pk, milestone.pk)])
            self.assertEqual((list(calendars.objects.values()), list(dates.objects.values())), before)
            with self.assertRaises(IntegrityError), transaction.atomic():
                declarations.objects.filter(version_id=version.pk).delete()
        finally:
            with connection.cursor() as cursor:
                cursor.execute('SET search_path TO ' + original_path)
                cursor.execute('DROP SCHEMA diary_requirement_migration_test CASCADE')
