"""Make sure task dates and completion meet DV1-023, DV1-032, and DV1-035 through DV1-038."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone as datetime_timezone
from importlib import import_module
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpResponseForbidden
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import include, path, reverse

from Diary.api import Actor, DiaryAPI, EntrySpec
from Diary.choices import DateKind, OwnerKind
from Diary.models import CalendarEntry, EntryDependency, EventCalendar, TemplateEntry, TemplateVersion
from Diary.tests.test_task_creation import TaskCreationFixtures
from Diary.tests.legacy_dependencies import seed_legacy_dependencies
from Diary.views import ManagerDiaryView, PersonalDiaryView, TaskDetailView


class HostTaskDetailView(TaskDetailView):
    """Supply current permitted diary keys through the test host's trusted policy."""

    def get_success_url(self, *, result):
        return reverse('host-detail-selected', kwargs={'diary_key': result.diary_key, 'entry_key': result.entry_key})

    def get_diary_keys(self):
        """Return trusted diary keys independently of URL or POST values."""
        return settings.EDIT_TEST_KEYS


class HostTaskListScope:
    """Supply the same trusted diary scope and detail route to both task lists."""

    extra_context = {'task_detail_url_name': 'host-detail'}

    def get_diary_keys(self):
        """Return the test host's current permitted diary keys."""
        return settings.EDIT_TEST_KEYS


class HostPersonalTaskView(HostTaskListScope, PersonalDiaryView):
    """Show personal tasks with links to the equally scoped task detail view."""


class HostManagerTaskView(HostTaskListScope, ManagerDiaryView):
    """Show manager tasks with links to the equally scoped task detail view."""


def handler403(request, exception):
    """Return a denial without importing host error-page navigation."""
    return HttpResponseForbidden('Access denied.')


urlpatterns = [path('host/tasks/<uuid:entry_key>/', HostTaskDetailView.as_view(), name='host-detail'),
               path('host/diaries/<uuid:diary_key>/tasks/<uuid:entry_key>/', HostTaskDetailView.as_view(), name='host-detail-selected'),
               path('host/personal/', HostPersonalTaskView.as_view(), name='host-edit-personal'),
               path('host/manager/', HostManagerTaskView.as_view(), name='host-edit-manager'),
               path('diary/', include('Diary.urls'))]


class TaskEditingFixtures(TaskCreationFixtures):
    """Prepare a copied predecessor chain, a personal addition, and two diary snapshots."""

    def setUp(self):
        """Create a self-owned task and authenticated API clients within one permitted diary."""
        super().setUp()
        self.user_actor = Actor(f'user:{self.user.pk}', frozenset({'Participants', 'Helpers'}),
                                frozenset({self.diary.key}))
        self.user_diary = DiaryAPI(actor=self.user_actor).diary(key=self.diary.key)
        self.personal = self.user_diary.add_entry(spec=EntrySpec('Personal target', DateKind.ONCE,
            fixed_date=date(2027, 6, 22), owner_kind=OwnerKind.PERSON, person_ref=self.user_actor.reference))
        scope = override_settings(EDIT_TEST_KEYS=(self.diary.key,))
        scope.enable()
        self.addCleanup(scope.disable)

    def task_url(self, entry_key=None, diary_key=None):
        """Return a scoped host URL, using the personal task when no key is supplied."""
        return reverse('host-detail', kwargs={'entry_key': entry_key or self.personal}) + '?diary_key=' + str(diary_key or self.diary.key)

    def action_data(self, action, entry_key=None, **values):
        """Read the current inspection state and add one explicit action to its submitted fields."""
        page = self.client.get(self.task_url(entry_key))
        self.assertEqual(page.status_code, 200)
        task = page.context['task']
        data = {'action': action, 'revision': task['revision'], 'blocker_token': task['blocker_token']}
        data.update(values)
        return data

    def block_personal(self):
        """Make the personal task depend on the two copied tasks through the final copied task."""
        seed_legacy_dependencies(self.diary.key, ((self.personal, (self.second.entry_key,)),))

    def entry_snapshot(self):
        """Return all stored task fields for mutation, retry, and transaction checks."""
        return list(CalendarEntry.objects.order_by('pk').values())


# DV1-023, DV1-032, DV1-035, DV1-036, DV1-037, DV1-038: HTTP and API checks use PostgreSQL test databases.
@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',),
                   ROOT_URLCONF=__name__)
class TaskEditingTests(TaskEditingFixtures, TestCase):
    """Make sure date permissions, private blockers, completion records, and stale forms operate correctly."""

    def test_user_edits_personal_due_date_without_changing_original_rule_or_other_records(self):
        """Change only a personal task's override and revision while keeping source and other diary records."""
        original = CalendarEntry.objects.get(entry_key=self.personal)
        before = self.entry_snapshot()
        payload = self.action_data('save_date', due_date='2027-05-01', name='Forged name', person_ref='user:forged')
        response = self.client.post(self.task_url(), payload)
        self.assertEqual(response.status_code, 302)
        current = CalendarEntry.objects.get(entry_key=self.personal)
        self.assertEqual(current.due_date, date(2027, 5, 1))
        self.assertEqual(current.fixed_date, original.fixed_date)
        self.assertEqual(current.name, original.name)
        self.assertEqual(current.person_ref, self.user_actor.reference)
        self.assertEqual(current.revision, 1)

        # All task records except the selected personal addition must remain unchanged.
        self.assertEqual([item for item in self.entry_snapshot() if item['entry_key'] != self.personal],
                         [item for item in before if item['entry_key'] != self.personal])
        task = self.user_diary.task(entry_key=self.personal)
        self.assertEqual(task['date'], date(2027, 5, 1))
        self.assertTrue(task['can_edit_date'])
        self.assertEqual(TemplateVersion.objects.count(), 1)
        self.assertEqual(TemplateEntry.objects.count(), 2)

    def test_user_cannot_edit_copied_group_team_or_other_person_dates(self):
        """Reject date edits when assignment or visible template content does not grant edit permission."""
        role = self.diary.add_entry(spec=EntrySpec('Group addition', DateKind.ONCE, fixed_date=date(2027, 6, 22),
                                                 owner_kind=OwnerKind.ROLE, role_ref='Helpers'))
        team = self.diary.add_entry(spec=EntrySpec('Team addition', DateKind.ONCE, fixed_date=date(2027, 6, 22)))
        for key in (self.first.entry_key, role, team):
            with self.subTest(key=key):
                page = self.client.get(self.task_url(key))
                self.assertNotContains(page, 'diary-detail-save-date')
                before = self.entry_snapshot()
                self.assertEqual(self.client.post(self.task_url(key), {'action': 'save_date', 'revision': 0,
                                                                      'due_date': '2027-01-01'}).status_code, 403)
                self.assertEqual(self.entry_snapshot(), before)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.task_url()).status_code, 404)
        self.assertEqual(self.client.post(self.task_url(), {'action': 'save_date', 'revision': 0,
                                                          'due_date': '2027-01-01'}).status_code, 404)

    def test_manager_changes_copied_due_date_without_template_revision_or_warning_service(self):
        """Keep template rules, milestones, dependency links, and other diary snapshots after a copied-task date edit."""
        self.client.force_login(self.manager)
        links = list(EntryDependency.objects.values())
        templates = list(TemplateEntry.objects.order_by('pk').values())
        other = list(CalendarEntry.objects.filter(calendar_id=self.other_diary.key).values())
        payload = self.action_data('save_date', self.first.entry_key, due_date='2035-12-31')
        self.assertContains(self.client.get(self.task_url(self.first.entry_key)),
                            'V1 does not warn managers when a due-date change causes a conflict.')
        self.assertEqual(self.client.post(self.task_url(self.first.entry_key), payload).status_code, 302)
        stored = CalendarEntry.objects.get(calendar_id=self.diary.key, entry_key=self.first.entry_key)
        self.assertEqual(stored.due_date, date(2035, 12, 31))
        self.assertEqual(stored.milestone.name, 'target')
        self.assertIsNotNone(stored.source_entry_id)
        self.assertEqual(list(EntryDependency.objects.values()), links)
        self.assertEqual(list(TemplateEntry.objects.order_by('pk').values()), templates)
        self.assertEqual(list(CalendarEntry.objects.filter(calendar_id=self.other_diary.key).values()), other)
        self.assertEqual(TemplateVersion.objects.count(), 1)

    def test_stale_invalid_and_completed_due_date_changes_are_rejected(self):
        """Reject stale forms, nondate input, and all edits after completion without changing the saved record."""
        payload = self.action_data('save_date', due_date='2027-08-01')
        self.user_diary.update_due_date(entry_key=self.personal, due_date=date(2027, 7, 1), expected_revision=0)
        self.assertEqual(self.client.post(self.task_url(), payload).status_code, 400)
        for value in ('', 'invalid', '2027-02-30'):
            with self.subTest(value=value):
                self.assertEqual(self.client.post(self.task_url(), self.action_data('save_date', due_date=value)).status_code, 400)
        with self.assertRaises(ValidationError):
            self.user_diary.update_due_date(entry_key=self.personal, due_date=datetime(2027, 7, 1), expected_revision=1)
        self.user_diary.complete(entry_key=self.personal, expected_revision=1)
        before = self.entry_snapshot()
        self.assertEqual(self.client.post(self.task_url(), self.action_data('save_date', due_date='2027-09-01')).status_code, 400)
        self.assertEqual(self.entry_snapshot(), before)

    def test_normal_completion_saves_effective_due_date_and_is_idempotent(self):
        """Keep one completion actor, time, action, and effective due date across retries."""
        self.user_diary.update_due_date(entry_key=self.personal, due_date=date(2027, 7, 2), expected_revision=0)
        payload = self.action_data('complete')
        self.assertEqual(self.client.post(self.task_url(), payload).status_code, 302)
        stored = CalendarEntry.objects.get(entry_key=self.personal)
        self.assertEqual(stored.completed_due_date, date(2027, 7, 2))
        self.assertEqual(stored.completed_by_ref, self.user_actor.reference)
        self.assertEqual(stored.completion_action, 'complete')
        self.assertEqual(stored.completion_target_key, self.personal)
        self.assertIsNotNone(stored.completed_at)
        before = self.entry_snapshot()
        self.client.force_login(self.manager)
        self.assertEqual(self.client.post(self.task_url(), payload).status_code, 302)
        self.assertEqual(self.entry_snapshot(), before)
        page = self.client.get(self.task_url())
        self.assertContains(page, 'Due date at completion: 2 July 2027')
        self.assertNotContains(page, 'diary-detail-complete"')
        self.assertNotIn(self.personal, {item['entry_key'] for item in self.user_diary.personal_tasks()})
        stored.due_date_override = date(2027, 8, 1)
        with self.assertRaises(ValidationError):
            stored.save()

    def test_completion_does_not_require_a_due_date(self):
        """Complete an undated accessible task independently of the separate required due-date edit field."""
        DiaryAPI(actor=self.actor).define_milestones(definitions={'unset': 'Unset date'})
        key = self.user_diary.add_entry(spec=EntrySpec('Undated task', DateKind.ANNUAL, month=2, day=29, year_offset=1,
                                       owner_kind=OwnerKind.PERSON, person_ref=self.user_actor.reference))
        self.assertEqual(self.client.post(self.task_url(key), self.action_data('complete', key)).status_code, 302)
        entry = CalendarEntry.objects.get(entry_key=key)
        self.assertIsNotNone(entry.completed_at)
        self.assertIsNone(entry.completed_due_date)

    def test_normal_completion_rechecks_indirect_and_direct_blockers(self):
        """List the open blocking chain and reject completion until every blocking task is complete."""
        self.block_personal()
        page = self.client.get(self.task_url())
        self.assertContains(page, 'Prepare')
        self.assertContains(page, 'Review')
        before = self.entry_snapshot()
        self.assertEqual(self.client.post(self.task_url(), self.action_data('complete')).status_code, 400)
        self.assertEqual(self.entry_snapshot(), before)
        self.user_diary.complete(entry_key=self.first.entry_key, expected_revision=0)
        self.user_diary.complete(entry_key=self.second.entry_key, expected_revision=0)
        self.assertEqual(self.client.post(self.task_url(), self.action_data('complete')).status_code, 302)
        self.assertEqual(EntryDependency.objects.filter(entry__calendar_id=self.diary.key).count(), 2)

    def test_close_all_records_comments_and_keeps_existing_completions_and_links(self):
        """Complete the open chain and target atomically while keeping previous completion records."""
        self.block_personal()
        self.user_diary.complete(entry_key=self.first.entry_key, expected_revision=0)
        first = CalendarEntry.objects.get(calendar_id=self.diary.key, entry_key=self.first.entry_key)
        before_first = (first.completed_at, first.completed_by_ref, first.completed_due_date, first.completion_action)
        links = list(EntryDependency.objects.order_by('pk').values())
        self.client.force_login(self.manager)
        self.assertContains(self.client.get(self.task_url()), 'diary-detail-close-all')
        payload = self.action_data('close_all')
        self.assertEqual(self.client.post(self.task_url(), payload).status_code, 302)
        blocker = CalendarEntry.objects.get(calendar_id=self.diary.key, entry_key=self.second.entry_key)
        target = CalendarEntry.objects.get(entry_key=self.personal)
        self.assertEqual(blocker.completion_action, 'forced_predecessor')
        self.assertIn('Close all', blocker.completion_comment)
        self.assertIn(str(self.personal), blocker.completion_comment)
        self.assertEqual(blocker.completion_target_key, self.personal)
        self.assertEqual(blocker.completed_at, target.completed_at)
        self.assertEqual(target.completion_action, 'close_all')
        first.refresh_from_db()
        self.assertEqual((first.completed_at, first.completed_by_ref, first.completed_due_date, first.completion_action), before_first)
        self.assertEqual(list(EntryDependency.objects.order_by('pk').values()), links)
        self.assertFalse(CalendarEntry.objects.filter(calendar_id=self.other_diary.key, completed_at__isnull=False).exists())
        before = self.entry_snapshot()
        self.assertEqual(self.client.post(self.task_url(), payload).status_code, 302)
        self.assertEqual(self.entry_snapshot(), before)

    def test_forced_completion_rejects_users_and_stale_predecessor_inspection(self):
        """Require manager access and another inspection after a predecessor date or state changes."""
        self.block_personal()
        before = self.entry_snapshot()
        self.assertEqual(self.client.post(self.task_url(), self.action_data('close_all')).status_code, 403)
        self.assertEqual(self.entry_snapshot(), before)
        self.client.force_login(self.manager)
        payload = self.action_data('close_all')
        self.diary.update_due_date(entry_key=self.first.entry_key, due_date=date(2028, 1, 1), expected_revision=0)
        before = self.entry_snapshot()
        self.assertEqual(self.client.post(self.task_url(), payload).status_code, 400)
        self.assertEqual(self.entry_snapshot(), before)
        payload = self.action_data('close_all')
        self.diary.complete(entry_key=self.first.entry_key, expected_revision=1)
        self.assertEqual(self.client.post(self.task_url(), payload).status_code, 400)

    def test_failure_during_close_all_rolls_back_every_completion(self):
        """Undo all predecessor records when saving the selected task fails."""
        self.block_personal()
        before = self.entry_snapshot()
        original = CalendarEntry.save

        def fail_target(entry, *args, **kwargs):
            """Save predecessors normally and simulate a target write failure after their saves."""

            # The final target save fails after predecessor changes entered the same transaction.
            if entry.entry_key == self.personal:
                raise ValidationError('Target save failed.')
            return original(entry, *args, **kwargs)
        self.client.force_login(self.manager)
        payload = self.action_data('close_all')
        with patch.object(CalendarEntry, 'save', fail_target):
            self.assertContains(self.client.post(self.task_url(), payload), 'Target save failed.', status_code=400)
        self.assertEqual(self.entry_snapshot(), before)

    def test_private_blockers_and_completion_audit_do_not_disclose_private_target_keys(self):
        """Keep private blocker details and later forced-completion references outside another user's results."""
        private = self.diary.add_entry(spec=EntrySpec('<Secret blocker>', DateKind.ONCE, fixed_date=date(2020, 5, 1),
            owner_kind=OwnerKind.PERSON, person_ref=f'user:{self.other.pk}'), directory=self.owner_directory())
        target = CalendarEntry.objects.get(entry_key=self.personal)
        blocker = CalendarEntry.objects.get(entry_key=private)

        # A legacy link exercises privacy even when current creation rules exclude private additions as predecessors.
        seed_legacy_dependencies(self.diary.key, ((target.entry_key, (blocker.entry_key,)),))
        page = self.client.get(self.task_url())
        self.assertContains(page, 'One or more private predecessors remain open.')
        self.assertNotContains(page, 'Secret blocker')
        self.assertNotContains(page, str(private))
        self.assertNotIn(str(private), repr(self.user_diary.task(entry_key=self.personal)))
        self.assertTrue(self.user_diary.task(entry_key=self.personal)['blocked_late'])
        self.client.force_login(self.manager)
        self.assertContains(self.client.get(self.task_url()), '&lt;Secret blocker&gt;')
        self.assertEqual(self.client.post(self.task_url(), self.action_data('close_all')).status_code, 302)
        private_target = self.diary.add_entry(spec=EntrySpec('Manager private target', DateKind.ONCE,
            fixed_date=date(2027, 7, 1), owner_kind=OwnerKind.PERSON, person_ref=f'user:{self.manager.pk}'),
            directory=self.owner_directory())
        seed_legacy_dependencies(self.diary.key, ((private_target, (self.second.entry_key,)),))
        inspected = self.diary.task(entry_key=private_target)
        self.diary.complete(entry_key=private_target, expected_revision=0, close_all=True,
                            expected_blockers=inspected['blocker_token'])
        public = self.user_diary.task(entry_key=self.second.entry_key)
        self.assertIsNone(public['completion_target_key'])
        self.assertNotIn(str(private_target), repr(public))
        self.assertIn('inaccessible task', public['completion_comment'])

    @staticmethod
    def owner_directory():
        """Return the configured Django person directory for manager assignment tests."""
        from Diary.views import DjangoOwnerDirectory
        return DjangoOwnerDirectory()

    def test_scope_closed_diary_membership_csrf_and_invalid_actions(self):
        """Keep direct task requests within current access and reject writes to closed diaries."""
        self.assertEqual(self.client.get(self.task_url(diary_key=self.other_diary.key)).status_code, 403)
        self.assertEqual(self.client.get(self.task_url(uuid4())).status_code, 404)
        self.assertEqual(self.client.get(reverse('host-detail', kwargs={'entry_key': self.personal})).status_code, 400)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(strict.post(self.task_url(), self.action_data('complete')).status_code, 403)
        before = self.entry_snapshot()
        self.assertEqual(self.client.post(self.task_url(), {'action': 'unknown'}).status_code, 400)
        self.assertEqual(self.entry_snapshot(), before)
        self.diary.close()
        self.assertContains(self.client.get(self.task_url()), 'This diary is closed.')
        self.assertNotContains(self.client.get(self.task_url()), 'diary-detail-date-form')
        self.assertEqual(self.client.post(self.task_url(), self.action_data('complete')).status_code, 400)
        self.assertEqual(self.client.post(self.task_url(), {'action': 'save_date', 'revision': 0,
                                                          'due_date': '2027-09-01'}).status_code, 400)
        self.user.groups.clear()
        self.assertEqual(self.client.get(self.task_url()).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.task_url()).status_code, 302)

    def test_no_missing_migration_and_full_or_embedded_documents(self):
        """Keep model changes in migrations and render one complete document or reusable task content."""
        from django.template import engines
        call_command('makemigrations', 'Diary', check=True, dry_run=True, verbosity=0)
        before = self.entry_snapshot()
        page = self.client.get(self.task_url())
        self.assertEqual(page.content.lower().count(b'<!doctype html>'), 1)
        self.assertNotContains(page, 'style=')
        context = {name: page.context[name] for name in ('task', 'due_form', 'completion_form')}
        fragment = engines['django'].from_string('{% include "Diary/partials/task_detail.html" %}').render(context)
        self.assertNotIn('<!doctype', fragment.lower())
        self.assertEqual(self.entry_snapshot(), before)

    def test_task_links_keep_host_scope_and_states_refresh_after_edits_and_completion(self):
        """Keep selected diary links and calculate fresh list states after each task action."""
        url = reverse('host-edit-personal')
        page = self.client.get(url)
        self.assertContains(page, reverse('host-detail', kwargs={'entry_key': self.personal}))
        self.user_diary.update_due_date(entry_key=self.personal, due_date=date(2020, 1, 1), expected_revision=0)
        self.assertContains(self.client.get(url), 'diary-task-late')
        self.user_diary.complete(entry_key=self.personal, expected_revision=1)
        self.assertNotContains(self.client.get(url), 'Personal target')
        self.client.force_login(self.manager)
        manager = self.client.get(reverse('host-edit-manager'), {'diary_key': self.diary.key,
                                                               'include_completed': 'on'})
        self.assertContains(manager, 'Personal target')
        self.assertContains(manager, 'diary-manager-task-completed')

    def test_detail_highlights_use_direct_blockers_and_give_late_tasks_priority(self):
        """Use amber only for a late direct blocker and give the selected task's own lateness red priority."""
        self.block_personal()
        self.diary.update_due_date(entry_key=self.first.entry_key, due_date=date(2020, 1, 1), expected_revision=0)
        page = self.client.get(self.task_url())
        self.assertNotContains(page, 'diary-detail-blocked-late')
        self.diary.update_due_date(entry_key=self.second.entry_key, due_date=date(2020, 1, 2), expected_revision=0)
        self.assertContains(self.client.get(self.task_url()), 'diary-detail-blocked-late')
        self.user_diary.update_due_date(entry_key=self.personal, due_date=date(2020, 1, 3), expected_revision=0)
        page = self.client.get(self.task_url())
        self.assertContains(page, 'diary-detail-late')
        self.assertNotContains(page, 'diary-detail-blocked-late')
        self.user_diary.complete(entry_key=self.first.entry_key, expected_revision=1)
        self.user_diary.complete(entry_key=self.second.entry_key, expected_revision=1)
        self.assertTrue(self.client.get(self.task_url()).context['task']['ready'])


# DV1-032, DV1-036, DV1-037, DV1-044: Races use independent connections to a separate PostgreSQL test database.
@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',),
                   ROOT_URLCONF=__name__)
class TaskEditingConcurrencyTests(TaskEditingFixtures, TransactionTestCase):
    """Make sure date edits, completion, and diary closure cannot overwrite each other."""

    # Scoped cleanup includes the configured user model and avoids unrelated host table dependencies.
    available_apps = sorted({'Diary', 'django.contrib.auth', 'django.contrib.contenttypes',
                             'django.contrib.sessions', get_user_model()._meta.app_config.name})

    def race(self, operations):
        """Start two authorized operations together and return whether each operation saved or was rejected."""
        self.assertEqual(connection.vendor, 'postgresql')
        start = Barrier(2)

        def run(operation):
            """Run one operation through an independent connection after both callers reach the barrier."""
            close_old_connections()
            try:
                start.wait(timeout=10)
                operation()
                return 'saved'
            except ValidationError:
                return 'rejected'
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, operation) for operation in operations]
            return [future.result(timeout=30) for future in futures]

    def edit_date(self):
        """Attempt one date change from the task's initial revision."""
        self.user_diary.update_due_date(entry_key=self.personal, due_date=date(2028, 1, 1), expected_revision=0)

    def complete_task(self):
        """Attempt normal completion from the same initial revision."""
        self.user_diary.complete(entry_key=self.personal, expected_revision=0)

    def test_simultaneous_date_edits_allow_only_one_initial_revision(self):
        """Reject the second date save instead of replacing a concurrently saved date."""
        self.assertCountEqual(self.race((self.edit_date, self.edit_date)), ['saved', 'rejected'])
        self.assertEqual(CalendarEntry.objects.get(entry_key=self.personal).revision, 1)

    def test_date_edit_and_completion_use_one_consistent_task_revision(self):
        """Allow one of a date edit and completion, keeping a completed date consistent with the winning state."""
        self.assertCountEqual(self.race((self.edit_date, self.complete_task)), ['saved', 'rejected'])
        entry = CalendarEntry.objects.get(entry_key=self.personal)
        self.assertEqual(entry.revision, 1)

        # A winning completion must record the original date because the competing edit was rejected.
        if entry.completed_at is not None:
            self.assertEqual(entry.completed_due_date, date(2027, 6, 22))

    def test_simultaneous_completion_retries_keep_one_completion_record(self):
        """Allow safe repeated completion without changing the first completion record."""
        self.assertEqual(self.race((self.complete_task, self.complete_task)), ['saved', 'saved'])
        entry = CalendarEntry.objects.get(entry_key=self.personal)
        self.assertEqual(entry.revision, 1)
        self.assertIsNotNone(entry.completed_at)

    def test_diary_closure_and_completion_leave_no_write_after_closure(self):
        """Serialize closure with completion so the result is either a completed task or a rejected task write."""
        results = self.race((self.diary.close, self.complete_task))
        self.assertEqual(results[0], 'saved')
        self.assertIn(results[1], ('saved', 'rejected'))
        self.assertIsNotNone(EventCalendar.objects.get(pk=self.diary.key).closed_at)
        before = self.entry_snapshot()
        with self.assertRaises(ValidationError):
            self.complete_task()
        self.assertEqual(self.entry_snapshot(), before)

    def test_close_all_and_predecessor_date_edit_reject_one_stale_operation(self):
        """Keep one consistent chain when a manager's forced completion races with a predecessor date edit."""
        self.block_personal()
        inspected = self.diary.task(entry_key=self.personal)

        def force_chain():
            """Complete the inspected blocking chain from its original revision and fingerprint."""
            self.diary.complete(entry_key=self.personal, expected_revision=0, close_all=True,
                                expected_blockers=inspected['blocker_token'])

        def edit_predecessor():
            """Change one copied predecessor date from its original revision."""
            self.diary.update_due_date(entry_key=self.first.entry_key, due_date=date(2028, 2, 1), expected_revision=0)
        results = self.race((force_chain, edit_predecessor))
        self.assertCountEqual(results, ['saved', 'rejected'])
        target = CalendarEntry.objects.get(entry_key=self.personal)

        # A winning forced completion must commit the entire chain, without a partial completion.
        if target.completed_at is not None:
            self.assertEqual(CalendarEntry.objects.filter(calendar_id=self.diary.key, completed_at__isnull=False).count(), 3)

        # A winning predecessor edit must leave every completion field unset.
        else:
            self.assertFalse(CalendarEntry.objects.filter(calendar_id=self.diary.key, completed_at__isnull=False).exists())


# DV1-032, DV1-038: The PostgreSQL migration keeps existing task and completion data.
class TaskCompletionMigrationTests(TestCase):
    """Make sure the completion migration keeps historical data in an isolated PostgreSQL schema."""

    def test_existing_dates_and_completion_records_remain_unchanged(self):
        """Add nullable date and audit fields without changing historical task dates or completion records."""
        self.assertEqual(connection.vendor, 'postgresql')
        state = MigrationExecutor(connection).loader.project_state([('Diary', '0004_milestone_dates_without_diary_year')])
        migration = import_module('Diary.migrations.0005_task_dates_and_completion').Migration(
            '0005_task_dates_and_completion', 'Diary')
        with connection.cursor() as cursor:
            cursor.execute('SHOW search_path')
            original_path = cursor.fetchone()[0]
            cursor.execute('CREATE SCHEMA diary_task_completion_migration_test')
            cursor.execute('SET search_path TO diary_task_completion_migration_test')
        try:
            with transaction.atomic():
                with connection.schema_editor() as editor:
                    for model in state.apps.get_app_config('Diary').get_models():
                        editor.create_model(model)
                template = state.apps.get_model('Diary', 'CalendarTemplate').objects.create(name='Historical template')
                instant = datetime(2026, 10, 1, tzinfo=datetime_timezone.utc)
                version = state.apps.get_model('Diary', 'TemplateVersion').objects.create(
                    template=template, number=1, status='approved', created_by_ref='manager',
                    approved_by_ref='manager', approved_at=instant)
                calendar = state.apps.get_model('Diary', 'EventCalendar').objects.create(
                    template_version=version, event_ref='historical', name='Historical diary', created_by_ref='manager')
                entries = state.apps.get_model('Diary', 'CalendarEntry').objects
                completed = entries.create(calendar=calendar, name='Completed task', date_kind='once',
                    fixed_date=date(2026, 9, 30), completed_due_date=date(2026, 9, 30),
                    completed_at=instant, completed_by_ref='original-actor', created_by_ref='manager')
                annual = entries.create(calendar=calendar, name='Annual task', date_kind='annual', month=12, day=1,
                                        annual_due_date=date(2026, 12, 1), created_by_ref='manager')
                with connection.cursor() as cursor:
                    cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
                with connection.schema_editor() as editor:
                    migrated = migration.apply(state, editor)
                current = migrated.apps.get_model('Diary', 'CalendarEntry').objects
                saved = current.get(pk=completed.pk)
                self.assertEqual(saved.completed_at, instant)
                self.assertEqual(saved.completed_by_ref, 'original-actor')
                self.assertEqual(saved.completed_due_date, date(2026, 9, 30))
                self.assertIsNone(saved.due_date_override)
                self.assertEqual(saved.revision, 0)
                self.assertEqual(saved.completion_action, '')
                self.assertEqual(saved.completion_comment, '')
                self.assertIsNone(saved.completion_target_key)
                self.assertEqual(current.get(pk=annual.pk).annual_due_date, date(2026, 12, 1))
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f'SET search_path TO {original_path}')
                cursor.execute('DROP SCHEMA diary_task_completion_migration_test CASCADE')
