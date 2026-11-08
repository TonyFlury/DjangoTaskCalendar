"""DFUT-014: Task-relative dates are validated and snapshotted, never rescheduled."""
import json
from dataclasses import replace
from datetime import date, datetime, timezone as datetime_timezone
from io import StringIO
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from Diary.api import Actor, DiaryAPI, EntrySpec
from Diary.choices import DateKind, OwnerKind
from Diary.date_rules import task_date_order, task_relative_date
from Diary.models import CalendarEntry, CalendarTemplate, EventCalendar, TemplateEntry
from Diary.tests.test_task_creation import TaskCreationFixtures


class TaskDateGraphTests(SimpleTestCase):
    def test_signed_offsets_leap_days_and_calendar_limits(self):
        self.assertEqual(task_relative_date(date(2028, 2, 28), 1), date(2028, 2, 29))
        self.assertEqual(task_relative_date(date(2028, 3, 1), -1), date(2028, 2, 29))
        self.assertEqual(task_relative_date(date(2027, 1, 1), 0), date(2027, 1, 1))
        for source, offset in ((None, 1), (date.max, 1), (date.min, -1), (date.today(), 2147483647)):
            with self.subTest(source=source, offset=offset), self.assertRaises(ValidationError):
                task_relative_date(source, offset)

    def test_long_date_chain_is_not_limited_by_recursion_or_completion_graph(self):
        entries = [EntrySpec('Root', DateKind.ANNUAL, month=1, day=1)]
        for index in range(1200):
            entries.append(EntrySpec(str(index), DateKind.TASK, source_task_key=entries[-1].entry_key))
        self.assertEqual(task_date_order(reversed(entries)), [entry.entry_key for entry in entries])


class TaskRelativeDateMigrationTests(TestCase):
    def test_migration_preserves_existing_dates_completion_and_notes(self):
        state = MigrationExecutor(connection).loader.project_state([('Diary', '0012_task_notes')])
        migration = import_module('Diary.migrations.0013_task_relative_due_dates').Migration(
            '0013_task_relative_due_dates', 'Diary')
        with connection.cursor() as cursor:
            cursor.execute('SHOW search_path')
            original_path = cursor.fetchone()[0]
            cursor.execute('CREATE SCHEMA diary_relative_date_migration_test')
            cursor.execute('SET search_path TO diary_relative_date_migration_test')
        try:
            with connection.schema_editor() as editor:
                for model in state.apps.get_app_config('Diary').get_models():
                    editor.create_model(model)
            calendar = state.apps.get_model('Diary', 'EventCalendar').objects.create(
                name='Historical diary', event_ref='historical-dates', created_by_ref='manager')
            entries = state.apps.get_model('Diary', 'CalendarEntry')
            stamp = datetime(2026, 11, 1, tzinfo=datetime_timezone.utc)
            once = entries.objects.create(calendar=calendar, name='Completed historical task', date_kind='once',
                fixed_date=date(2026, 10, 20), due_date_override=date(2026, 10, 21), created_by_ref='manager',
                completed_at=stamp, completed_by_ref='manager', completed_due_date=date(2026, 10, 21))
            entries.objects.create(calendar=calendar, name='Annual historical task', date_kind='annual', month=6, day=1,
                                   annual_due_date=date(2027, 6, 1), created_by_ref='manager')
            notes = state.apps.get_model('Diary', 'TaskNote')
            notes.objects.create(entry=once, author_ref='manager', text='Retained note')
            before = list(entries.objects.order_by('pk').values())
            old_notes = list(notes.objects.values())
            with connection.cursor() as cursor:
                cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            with connection.schema_editor() as editor:
                migrated = migration.apply(state, editor)
            current = migrated.apps.get_model('Diary', 'CalendarEntry')
            self.assertEqual(list(current.objects.order_by('pk').values(*before[0].keys())), before)
            self.assertFalse(current.objects.exclude(task_due_date=None, source_task_key=None).exists())
            self.assertEqual(list(migrated.apps.get_model('Diary', 'TaskNote').objects.values()), old_notes)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f'SET search_path TO {original_path}')
                cursor.execute('DROP SCHEMA diary_relative_date_migration_test CASCADE')


@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',),
                   ROOT_URLCONF='Diary.tests.test_task_editing')
class TaskRelativeDateTests(TaskCreationFixtures, TestCase):
    def relative_template(self, *, root=None):
        self.root = root or replace(self.first, name='Z root')
        self.review = EntrySpec('Review', DateKind.TASK, source_task_key=self.root.entry_key, day_offset=3)
        self.submit = EntrySpec('A submit', DateKind.TASK, source_task_key=self.review.entry_key, day_offset=2)
        self.zero = EntrySpec('Same day', DateKind.TASK, source_task_key=self.root.entry_key)
        self.before = EntrySpec('Earlier', DateKind.TASK, source_task_key=self.submit.entry_key, day_offset=-4)
        self.specs = (self.submit, self.before, self.zero, self.review, self.root)
        self.relative_version = self.template.save_version(entries=self.specs, predecessors={},
                                                           expected_version_key=self.version.key)
        return self.relative_version

    def create_relative(self, **kwargs):
        options = dict(name='Calculated dates', event_ref='relative:1',
                       template_version_key=self.relative_version.key,
                       milestone_dates={'target': date(2027, 6, 20)})
        options.update(kwargs)
        diary = DiaryAPI(actor=self.actor).create_diary(**options)
        actor = replace(self.actor, calendar_keys=frozenset({diary.key}))
        return DiaryAPI(actor=actor).diary(key=diary.key)

    def dates(self, diary):
        return {entry['entry_key']: entry['date'] for entry in diary.read()['entries']}

    def test_creation_resolves_out_of_order_chains_zero_and_negative_offsets(self):
        self.relative_template()
        diary = self.create_relative()
        self.assertEqual(self.dates(diary), {self.root.entry_key: date(2027, 6, 20),
            self.review.entry_key: date(2027, 6, 23), self.submit.entry_key: date(2027, 6, 25),
            self.zero.entry_key: date(2027, 6, 20), self.before.entry_key: date(2027, 6, 21)})
        self.assertTrue(all(entry['ready'] for entry in diary.read()['entries']))
        self.assertFalse(CalendarEntry.objects.filter(calendar_id=diary.key, predecessors__isnull=False).exists())
        stored = CalendarEntry.objects.get(calendar_id=diary.key, entry_key=self.review.entry_key)
        self.assertEqual((stored.source_task_key, stored.task_due_date), (self.root.entry_key, date(2027, 6, 23)))

    def test_source_lateness_completion_manual_changes_and_retries_do_not_move_dates(self):
        self.relative_template()
        diary = self.create_relative()
        expected = self.dates(diary)
        diary.update_due_date(entry_key=self.root.entry_key, due_date=date(2027, 7, 1), expected_revision=0)
        with patch('django.utils.timezone.now', return_value=datetime(2027, 7, 10, tzinfo=datetime_timezone.utc)):
            diary.complete(entry_key=self.root.entry_key, expected_revision=1)
        self.assertEqual(self.dates(diary)[self.review.entry_key], expected[self.review.entry_key])
        self.assertEqual(self.create_relative().key, diary.key)
        self.assertEqual(self.dates(diary)[self.submit.entry_key], expected[self.submit.entry_key])
        # An explicit edit affects only that task; downstream dates still keep their snapshots.
        diary.update_due_date(entry_key=self.review.entry_key, due_date=date(2027, 8, 1), expected_revision=0)
        self.assertEqual(self.dates(diary)[self.submit.entry_key], date(2027, 6, 25))
        diary.complete(entry_key=self.submit.entry_key, expected_revision=0)
        self.assertEqual(diary.task(entry_key=self.submit.entry_key)['completed_due_date'], date(2027, 6, 25))

    def test_annual_source_uses_original_diary_creation_date_on_later_application(self):
        self.relative_template(root=EntrySpec('Annual root', DateKind.ANNUAL, month=2, day=29))
        with patch('django.utils.timezone.now', return_value=datetime(2026, 1, 1, tzinfo=datetime_timezone.utc)):
            empty = DiaryAPI(actor=self.actor).create_diary(name='Empty', without_template=True)
        actor = replace(self.actor, calendar_keys=frozenset({empty.key}))
        diary = DiaryAPI(actor=actor).diary(key=empty.key)
        personal = diary.add_entry(spec=EntrySpec('Personal', DateKind.ONCE, fixed_date=date(2026, 5, 1)))
        with patch('django.utils.timezone.now', return_value=datetime(2029, 1, 1, tzinfo=datetime_timezone.utc)):
            diary.apply_template(template_version_key=self.relative_version.key, milestone_dates={})
        self.assertEqual(self.dates(diary)[self.root.entry_key], date(2028, 2, 29))
        self.assertEqual(self.dates(diary)[self.review.entry_key], date(2028, 3, 3))
        self.assertEqual(self.dates(diary)[personal], date(2026, 5, 1))
        diary.apply_template(template_version_key=self.relative_version.key, milestone_dates={})
        self.assertEqual(self.dates(diary)[self.review.entry_key], date(2028, 3, 3))

    def test_date_references_and_completion_dependencies_are_independent(self):
        self.relative_template()
        self.relative_version = self.template.save_version(entries=self.specs,
            predecessors={self.root.entry_key: [self.review.entry_key]}, expected_version_key=self.relative_version.key)
        diary = self.create_relative()
        self.assertFalse(diary.task(entry_key=self.root.entry_key)['ready'])
        self.assertTrue(diary.task(entry_key=self.review.entry_key)['ready'])
        diary.complete(entry_key=self.review.entry_key, expected_revision=0)
        self.assertTrue(diary.task(entry_key=self.root.entry_key)['ready'])

    def test_invalid_sources_self_links_cycles_and_removed_sources_leave_no_version(self):
        root = self.first
        one = EntrySpec('One', DateKind.TASK, source_task_key=root.entry_key)
        two = EntrySpec('Two', DateKind.TASK, source_task_key=one.entry_key)
        count = self.template.latest_version().read()['number']
        for entries in ((one,), (replace(one, source_task_key=None), root),
                        (replace(one, source_task_key=one.entry_key), root),
                        (replace(one, source_task_key=two.entry_key), two, root),
                        (replace(one, source_task_key=uuid4()), root),
                        (replace(root, source_task_key=one.entry_key), one)):
            with self.subTest(entries=entries), self.assertRaises(ValidationError):
                self.template.save_version(entries=entries, predecessors={}, expected_version_key=self.version.key)
            self.assertEqual(self.template.latest_version().read()['number'], count)

    def test_incremental_draft_allows_forward_references_but_approval_rejects_missing_source(self):
        draft = self.template.create_version(number=2)
        dependent = EntrySpec('Forward reference', DateKind.TASK, source_task_key=self.first.entry_key)
        draft.add_entry(spec=dependent)
        with self.assertRaises(ValidationError):
            draft.approve()
        draft.add_entry(spec=self.first)
        draft.approve()
        self.assertEqual(draft.read()['status'], 'approved')

    def test_unresolvable_dates_and_overflow_roll_back_creation_and_template_application(self):
        self.relative_template(root=EntrySpec('Invalid annual occurrence', DateKind.ANNUAL,
                                            month=2, day=29, year_offset=1))
        before = EventCalendar.objects.count()
        with self.assertRaises(ValidationError):
            self.create_relative()
        self.assertEqual(EventCalendar.objects.count(), before)
        empty = DiaryAPI(actor=self.actor).create_diary(name='Empty', without_template=True)
        diary = DiaryAPI(actor=replace(self.actor, calendar_keys=frozenset({empty.key}))).diary(key=empty.key)
        with self.assertRaises(ValidationError):
            diary.apply_template(template_version_key=self.relative_version.key, milestone_dates={})
        self.assertIsNone(diary.read()['template_version_key'])
        self.assertEqual(diary.read()['entries'], ())

    def test_snapshot_and_provenance_are_protected_but_explicit_override_is_allowed(self):
        self.relative_template()
        diary = self.create_relative()
        query = CalendarEntry.objects.filter(calendar_id=diary.key, entry_key=self.review.entry_key)
        for change in (dict(task_due_date=date(2027, 9, 1)), dict(source_task_key=self.zero.entry_key),
                       dict(day_offset=9)):
            entry = query.get()
            for key, value in change.items():
                setattr(entry, key, value)
            with self.assertRaises(ValidationError):
                entry.save()
            with self.assertRaises(IntegrityError), transaction.atomic():
                query.update(**change)
        diary.update_due_date(entry_key=self.review.entry_key, due_date=date(2027, 9, 1), expected_revision=0)
        self.assertEqual(query.get().task_due_date, date(2027, 6, 23))

    def test_direct_api_addition_resolves_once_and_hides_private_source_provenance(self):
        source = EntrySpec('Private source', DateKind.ONCE, fixed_date=date(2027, 1, 1),
                           owner_kind=OwnerKind.PERSON, person_ref=f'user:{self.user.pk}')
        from Diary.views import DjangoOwnerDirectory
        self.diary.add_entry(spec=source, directory=DjangoOwnerDirectory())
        child = EntrySpec('Public child', DateKind.TASK, source_task_key=str(source.entry_key), day_offset=2)
        self.diary.add_entry(spec=child)
        self.diary.add_entry(spec=child)
        actor = Actor(f'user:{self.other.pk}', frozenset({'Participants'}), frozenset({self.diary.key}))
        other = DiaryAPI(actor=actor).diary(key=self.diary.key)
        self.assertIsNone(other.task(entry_key=child.entry_key)['date_rule']['source_task_key'])
        self.assertEqual(other.task(entry_key=child.entry_key)['source_task_name'], 'Unavailable source task')
        personal = replace(child, entry_key=uuid4(), name='Forbidden date lookup',
                           owner_kind=OwnerKind.PERSON, person_ref=actor.reference)
        with self.assertRaises(ObjectDoesNotExist):
            other.add_entry(spec=personal)
        self.assertEqual(self.diary.task(entry_key=child.entry_key)['date'], date(2027, 1, 3))

    def test_fixture_round_trip_dry_run_and_invalid_date_reference(self):
        self.relative_template()
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'tasks.json'
            call_command('transfer_diary_templates', 'export', str(path), template=['Creation template'], stdout=StringIO())
            payload = json.loads(path.read_text())
            for record in payload:
                if record['model'] == CalendarTemplate._meta.label_lower:
                    record['fields']['name'] = 'Portable task dates'
            path.write_text(json.dumps(payload))
            call_command('transfer_diary_templates', 'import', str(path), dry_run=True, stdout=StringIO())
            self.assertFalse(CalendarTemplate.objects.filter(name='Portable task dates').exists())
            call_command('transfer_diary_templates', 'import', str(path), stdout=StringIO())
            imported = DiaryAPI(actor=self.actor).template(name='Portable task dates').latest_version()
            child = next(entry for entry in imported.read()['entries'] if entry['entry_key'] == self.review.entry_key)
            self.assertEqual(child['source_task_key'], self.root.entry_key)
            self.assertNotEqual(imported.key, self.relative_version.key)
            for record in payload:
                if record['model'] == TemplateEntry._meta.label_lower and record['fields']['date_kind'] == 'task':
                    record['fields']['source_task_key'] = str(uuid4())
                    break
            path.write_text(json.dumps(payload))
            with self.assertRaises(CommandError):
                call_command('transfer_diary_templates', 'import', str(path), new_version=True, stdout=StringIO())

    def template_payload(self):
        values = {'name': 'Creation template', 'description': '', 'expected_version_key': str(self.version.key),
                  'tasks-TOTAL_FORMS': '2', 'tasks-INITIAL_FORMS': '2',
                  'tasks-MIN_NUM_FORMS': '0', 'tasks-MAX_NUM_FORMS': '200', 'action': 'save'}
        for index, spec in enumerate((self.first, self.second)):
            for key, value in dict(entry_key=spec.entry_key, name=spec.name, date_kind='source',
                                   milestone_name='target', owner_kind='team').items():
                values[f'tasks-{index}-{key}'] = str(value)
        values.update({'tasks-1-date_kind': 'task', 'tasks-1-source_task_key': str(self.first.entry_key),
                       'tasks-1-day_offset': '3'})
        return values

    def test_template_editor_saves_relative_date_and_rejects_deleted_source_without_javascript(self):
        self.client.force_login(self.manager)
        url = reverse('Diary:template-edit', kwargs={'template_name': 'Creation template'})
        values = self.template_payload()
        values['tasks-0-DELETE'] = 'on'
        self.assertEqual(self.client.post(url, values).status_code, 400)
        values.pop('tasks-0-DELETE')
        self.assertEqual(self.client.post(url, values).status_code, 302)
        latest = self.template.latest_version()
        source = TemplateEntry.objects.get(version_id=latest.key, entry_key=self.second.entry_key)
        self.assertEqual((source.date_kind, source.source_task_key, source.day_offset),
                         ('task', self.first.entry_key, 3))
        self.relative_version = latest
        diary = self.create_relative()
        self.assertEqual(self.dates(diary)[self.second.entry_key], date(2027, 6, 23))

    @override_settings(ROOT_URLCONF='Diary.tests.test_task_creation')
    def test_diary_task_form_and_future_template_rule_use_separate_source_offsets(self):
        values = self.payload(date_kind='task', source_task_key=str(self.first.entry_key), day_offset='3')
        self.assertEqual(self.client.post(self.url(), values).status_code, 302)
        personal = CalendarEntry.objects.get(calendar_id=self.diary.key, entry_key=values['entry_key'])
        self.assertEqual(personal.due_date, date(2027, 6, 23))
        self.client.force_login(self.manager)
        values = self.combined_payload(name='Future relative addition', date_kind='task', source_task_key=str(self.first.entry_key), day_offset='2',
            **{'future-date_kind': 'task', 'future-source_task_key': str(self.first.entry_key), 'future-day_offset': '5'})
        self.assertEqual(self.client.post(self.url(), values).status_code, 302)
        live = CalendarEntry.objects.get(calendar_id=self.diary.key, entry_key=values['entry_key'])
        future = TemplateEntry.objects.get(version_id=self.template.latest_version().key, entry_key=values['entry_key'])
        self.assertEqual((live.task_due_date, future.source_task_key, future.day_offset),
                         (date(2027, 6, 22), self.first.entry_key, 5))
