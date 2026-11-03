"""DV1-028: Make sure diary dependency snapshots cannot change after creation."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from importlib import import_module
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from Diary.api import Actor, DiaryAPI
from Diary.models import CalendarEntry, EntryDependency, EventCalendar, TemplateDependency
from Diary.tests.test_task_creation import TaskCreationFixtures


# DV1-028: Both callable and direct database writes must keep the live graph unchanged.
@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',))
class LiveDependencyTests(TaskCreationFixtures, TestCase):
    """Reject dependency additions, removals, replacements, and model bypasses on existing diaries."""

    def graph(self):
        """Return every stored dependency row for complete before-and-after comparisons."""
        return list(EntryDependency.objects.order_by('pk').values())

    def link(self):
        """Return the copied predecessor link in the selected diary."""
        return EntryDependency.objects.get(entry__calendar_id=self.diary.key)

    def assert_database_rejects(self, operation):
        """Require an integrity error inside a savepoint without leaving the test transaction broken."""
        before = self.graph()
        with self.assertRaises(IntegrityError), transaction.atomic():
            operation()
        self.assertEqual(self.graph(), before)

    def test_api_rejects_empty_identical_added_and_replaced_dependencies(self):
        """Reject every manager edit without consuming invalid input or deleting the saved graph."""
        before = self.graph()
        for entry_key, keys in ((self.second.entry_key, ()),
                                (self.second.entry_key, (self.first.entry_key,)),
                                (self.first.entry_key, (self.second.entry_key,)),
                                (self.second.entry_key, (uuid4(),))):
            with self.subTest(entry_key=entry_key, keys=keys):
                with self.assertRaisesMessage(ValidationError, 'V1 does not allow dependency changes'):
                    self.diary.set_predecessors(entry_key=entry_key, predecessor_keys=keys)
                self.assertEqual(self.graph(), before)

    def test_model_save_clean_and_delete_reject_existing_diary_links(self):
        """Reject normal model operations independently of the callable API."""
        link = self.link()
        before = self.graph()
        for operation in (link.clean, link.save, link.delete):
            with self.subTest(operation=operation):
                with self.assertRaisesMessage(ValidationError, 'V1 does not allow dependency changes'):
                    operation()
                self.assertEqual(self.graph(), before)
        with self.assertRaises(ValidationError):
            EntryDependency.objects.create(entry=link.predecessor, predecessor=link.entry)
        self.assertEqual(self.graph(), before)

    def test_queryset_bulk_and_many_to_many_operations_cannot_change_links(self):
        """Prevent SQL-backed bypasses through bulk writes and relationship managers."""
        link = self.link()

        def insert_bulk():
            """Attempt a new dependency with model validation bypassed."""
            EntryDependency.objects.bulk_create([EntryDependency(entry=link.predecessor, predecessor=link.entry)])

        def replace_bulk():
            """Attempt to reverse a stored dependency through bulk update."""
            link.entry_id, link.predecessor_id = link.predecessor_id, link.entry_id
            EntryDependency.objects.bulk_update([link], ('entry', 'predecessor'))

        def queryset_update():
            """Attempt to redirect a copied dependency using a queryset."""
            EntryDependency.objects.filter(pk=link.pk).update(entry_id=link.predecessor_id)

        def queryset_delete():
            """Attempt to delete a copied dependency through a queryset."""
            EntryDependency.objects.filter(pk=link.pk).delete()

        def relation_add():
            """Attempt a dependency addition through the many-to-many manager."""
            link.predecessor.predecessors.add(link.entry)

        def relation_remove():
            """Attempt dependency removal through the many-to-many manager."""
            link.entry.predecessors.remove(link.predecessor)

        def relation_clear():
            """Attempt removal of every predecessor through the many-to-many manager."""
            link.entry.predecessors.clear()

        def relation_set():
            """Attempt replacement of a predecessor selection through the many-to-many manager."""
            link.entry.predecessors.set(())
        for operation in (insert_bulk, queryset_update, queryset_delete, relation_add, relation_remove, relation_clear, relation_set,
                          replace_bulk):
            with self.subTest(operation=operation):
                self.assert_database_rejects(operation)

    def test_locked_graph_cannot_reenter_initialization_or_change_endpoint_identity(self):
        """Reject attempts to unlock a diary or relabel a task referenced by its graph."""
        link = self.link()

        def unlock():
            """Attempt to reopen initialization through a queryset update."""
            EventCalendar.objects.filter(pk=self.diary.key).update(dependencies_locked=False)

        def rename_key():
            """Attempt to change the stable key used by a dependency endpoint."""
            CalendarEntry.objects.filter(pk=link.entry_id).update(entry_key=uuid4())

        def move_task():
            """Attempt to move a referenced task into another diary."""
            CalendarEntry.objects.filter(pk=link.entry_id).update(calendar_id=self.other_diary.key)
        for operation in (unlock, rename_key, move_task):
            with self.subTest(operation=operation):
                self.assert_database_rejects(operation)
        self.assertTrue(EventCalendar.objects.get(pk=self.diary.key).dependencies_locked)

    def test_creation_finishes_initialization_and_retry_preserves_the_same_graph(self):
        """Copy the approved graph once and lock it before returning from creation."""
        self.assertTrue(EventCalendar.objects.get(pk=self.diary.key).dependencies_locked)
        before = self.graph()
        repeated = DiaryAPI(actor=self.actor).create_diary(name='Selected diary', event_ref='creation:selected',
            milestone_dates={'target': date(2027, 6, 20)}, template_version_key=self.version.key)
        self.assertEqual(repeated.key, self.diary.key)
        self.assertEqual(self.graph(), before)
        self.assertEqual(self.diary.task(entry_key=self.second.entry_key)['blockers'][0]['entry_key'], self.first.entry_key)

    def test_initialization_failure_removes_the_partial_diary(self):
        """Roll back a new diary and its copies if initial dependency creation fails."""
        count = EventCalendar.objects.count()
        with patch.object(EntryDependency, 'save', side_effect=ValidationError('Snapshot failed.')):
            with self.assertRaises(ValidationError):
                DiaryAPI(actor=self.actor).create_diary(name='Failed snapshot', event_ref='snapshot:failed',
                    milestone_dates={'target': date(2027, 6, 20)}, template_version_key=self.version.key)
        self.assertEqual(EventCalendar.objects.count(), count)
        self.assertFalse(EventCalendar.objects.filter(event_ref='snapshot:failed').exists())

    def test_permissions_closed_diaries_and_template_drafts_keep_their_boundaries(self):
        """Keep access checks and draft editing while rejecting every closed or live diary edit."""
        user = Actor(f'user:{self.user.pk}', frozenset({'Participants'}), frozenset({self.diary.key}))
        for actor in (user, replace(self.actor, calendar_keys=frozenset())):
            with self.subTest(actor=actor):
                with self.assertRaises(PermissionDenied):
                    DiaryAPI(actor=actor).diary(key=self.diary.key).set_predecessors(
                        entry_key=self.second.entry_key, predecessor_keys=())
        draft = self.template.create_version(number=2)
        draft.add_entry(spec=self.first)
        draft.add_entry(spec=self.second)
        draft.set_predecessors(entry_key=self.second.entry_key, predecessor_keys=(self.first.entry_key,))
        self.assertEqual(TemplateDependency.objects.filter(entry__version_id=draft.key).count(), 1)
        before = self.graph()
        draft.set_predecessors(entry_key=self.second.entry_key, predecessor_keys=())
        draft.approve()
        self.assertEqual(self.graph(), before)
        with self.assertRaises(ValidationError):
            draft.set_predecessors(entry_key=self.second.entry_key, predecessor_keys=(self.first.entry_key,))
        self.diary.close()
        with self.assertRaises(ValidationError):
            self.diary.set_predecessors(entry_key=self.second.entry_key, predecessor_keys=())
        self.assertEqual(self.graph(), before)

    def test_date_changes_and_completion_keep_the_frozen_graph(self):
        """Allow supported task actions without altering their copied dependency links."""
        before = self.graph()
        self.diary.update_due_date(entry_key=self.second.entry_key, due_date=date(2028, 1, 1), expected_revision=0)
        task = self.diary.task(entry_key=self.second.entry_key)
        self.diary.complete(entry_key=self.second.entry_key, expected_revision=1, close_all=True,
                            expected_blockers=task['blocker_token'])
        self.assertEqual(self.graph(), before)

    def test_models_and_migrations_are_consistent(self):
        """Require a migration for every model field in the dependency-freeze change."""
        call_command('makemigrations', 'Diary', check=True, dry_run=True, verbosity=0)

    def test_forged_dependency_action_cannot_use_task_detail_post(self):
        """Reject an unsupported browser action without changing any dependency rows."""
        self.client.force_login(self.manager)
        before = self.graph()
        with self.settings(ROOT_URLCONF='Diary.tests.test_task_editing', EDIT_TEST_KEYS=(self.diary.key,)):
            url = reverse('host-detail', kwargs={'entry_key': self.second.entry_key}) + '?diary_key=' + str(self.diary.key)
            response = self.client.post(url, {'action': 'set_predecessors', 'predecessor_keys': ''})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.graph(), before)


# DV1-028: Independent transactions cannot reopen or edit a completed diary snapshot.
@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',))
class LiveDependencyTransactionTests(TaskCreationFixtures, TransactionTestCase):
    """Make sure unfinished snapshots cannot commit and concurrent edits cannot change a live graph."""

    # Keep cleanup scoped to the tested models and configured identity app.
    available_apps = sorted({'Diary', 'django.contrib.auth', 'django.contrib.contenttypes',
                             'django.contrib.sessions', get_user_model()._meta.app_config.name})

    def test_unfinished_initialization_cannot_commit(self):
        """Reject a new diary that leaves its graph unlocked when its transaction commits."""
        count = EventCalendar.objects.count()
        with self.assertRaises(IntegrityError), transaction.atomic():
            EventCalendar.objects.create(template_version_id=self.version.key, name='Unfinished diary',
                event_ref='snapshot:unfinished', created_by_ref=self.actor.reference, dependencies_locked=False)
        self.assertEqual(EventCalendar.objects.count(), count)

    def test_concurrent_api_and_bulk_edits_leave_the_same_graph(self):
        """Reject a manager edit and a bulk deletion started through independent connections."""
        before = list(EntryDependency.objects.order_by('pk').values())
        start = Barrier(2)

        def edit_api():
            """Attempt an API edit after both callers reach the barrier."""
            close_old_connections()
            try:
                start.wait(timeout=10)
                self.diary.set_predecessors(entry_key=self.second.entry_key, predecessor_keys=())
                return 'saved'
            except ValidationError:
                return 'rejected'
            finally:
                close_old_connections()

        def delete_bulk():
            """Attempt a bulk deletion after both callers reach the barrier."""
            close_old_connections()
            try:
                start.wait(timeout=10)
                with transaction.atomic():
                    EntryDependency.objects.filter(entry__calendar_id=self.diary.key).delete()
                return 'saved'
            except IntegrityError:
                return 'rejected'
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = (pool.submit(edit_api), pool.submit(delete_bulk))
            self.assertEqual([future.result(timeout=30) for future in futures], ['rejected', 'rejected'])
        self.assertEqual(list(EntryDependency.objects.order_by('pk').values()), before)


# DV1-028: Existing graphs become locked without changing historical links or task completion records.
class LiveDependencyMigrationTests(TestCase):
    """Apply the freeze migration to historical tables in an isolated PostgreSQL test schema."""

    def test_existing_links_and_completion_records_are_preserved(self):
        """Keep old rows unchanged and reject dependency writes after the actual migration."""
        from datetime import datetime, timezone

        state = MigrationExecutor(connection).loader.project_state([('Diary', '0005_task_dates_and_completion')])
        migration = import_module('Diary.migrations.0006_freeze_live_dependencies').Migration(
            '0006_freeze_live_dependencies', 'Diary')
        with connection.cursor() as cursor:
            cursor.execute('SHOW search_path')
            original_path = cursor.fetchone()[0]
            cursor.execute('CREATE SCHEMA diary_dependency_freeze_test')
            cursor.execute('SET search_path TO diary_dependency_freeze_test')
        try:
            with transaction.atomic():
                with connection.schema_editor() as editor:
                    for model in state.apps.get_app_config('Diary').get_models():
                        editor.create_model(model)
                template = state.apps.get_model('Diary', 'CalendarTemplate').objects.create(name='Historical template')
                instant = datetime(2026, 10, 1, tzinfo=timezone.utc)
                version = state.apps.get_model('Diary', 'TemplateVersion').objects.create(template=template,
                    number=1, status='approved', created_by_ref='manager', approved_by_ref='manager', approved_at=instant)
                calendar = state.apps.get_model('Diary', 'EventCalendar').objects.create(template_version=version,
                    name='Historical diary', event_ref='historical:freeze', created_by_ref='manager')
                entries = state.apps.get_model('Diary', 'CalendarEntry').objects
                first = entries.create(calendar=calendar, name='Prepare', date_kind='once', fixed_date=date(2026, 9, 30),
                                       created_by_ref='manager')
                second = entries.create(calendar=calendar, name='Review', date_kind='once', fixed_date=date(2026, 10, 1),
                    created_by_ref='manager', completed_at=instant, completed_by_ref='original-actor',
                    completed_due_date=date(2026, 10, 1), completion_action='complete')
                links = state.apps.get_model('Diary', 'EntryDependency').objects
                link = links.create(entry=second, predecessor=first)
                before_entries = list(entries.order_by('pk').values())
                before_links = list(links.order_by('pk').values())
                with connection.cursor() as cursor:
                    cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
                with connection.schema_editor() as editor:
                    current = migration.apply(state, editor)
                self.assertTrue(current.apps.get_model('Diary', 'EventCalendar').objects.get(pk=calendar.pk).dependencies_locked)
                self.assertEqual(list(current.apps.get_model('Diary', 'CalendarEntry').objects.order_by('pk').values()), before_entries)
                current_links = current.apps.get_model('Diary', 'EntryDependency').objects
                self.assertEqual(list(current_links.order_by('pk').values()), before_links)
                with self.assertRaises(IntegrityError), transaction.atomic():
                    current_links.filter(pk=link.pk).delete()
                self.assertEqual(list(current_links.order_by('pk').values()), before_links)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f'SET search_path TO {original_path}')
                cursor.execute('DROP SCHEMA diary_dependency_freeze_test CASCADE')
