"""Make sure task creation meets DV1-029, DV1-030, and DV1-033."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from dataclasses import replace
from datetime import date
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseForbidden
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import include, path, reverse

from Diary.api import Actor, DiaryAPI, DiaryTemplate, EntrySpec
from Diary.choices import DateKind, OwnerKind, VersionStatus
from Diary.models import CalendarEntry, EventCalendar, TemplateEntry, TemplateVersion
from Diary.views import DjangoOwnerDirectory, TaskCreateView


class HostTaskCreateView(TaskCreateView):
    """Supply trusted diary scope independently of browser input."""

    def get_success_url(self, *, result):
        return reverse('host-create-selected', kwargs={'diary_key': result.diary_key})

    def get_diary_keys(self):
        """Return the test host's current permitted diary keys."""
        return settings.CREATION_TEST_KEYS


def handler403(request, exception):
    """Return a permission response without host error-page dependencies."""
    return HttpResponseForbidden('Access denied.')


urlpatterns = [path('host-create/', HostTaskCreateView.as_view(), name='host-create'),
               path('host-create/<uuid:diary_key>/', HostTaskCreateView.as_view(), name='host-create-selected'),
               path('diary/', include('Diary.urls'))]


class TaskCreationFixtures:
    """Prepare authenticated owners and independent diary snapshots for creation tests."""

    def setUp(self):
        """Create eligible owners, two diary snapshots, and a template dependency graph."""
        model = get_user_model()
        self.user = model._default_manager.create_user(**{model.USERNAME_FIELD: 'creator@example.test'})
        self.other = model._default_manager.create_user(**{model.USERNAME_FIELD: 'assignee@example.test'})
        self.manager = model._default_manager.create_user(**{model.USERNAME_FIELD: 'planner@example.test'})
        self.outsider = model._default_manager.create_user(**{model.USERNAME_FIELD: 'outsider@example.test'})
        users = Group.objects.create(name='Participants')
        managers = Group.objects.create(name='Planners')
        helpers = Group.objects.create(name='Helpers')
        self.user.groups.add(users, helpers)
        self.other.groups.add(users)
        self.manager.groups.add(managers)
        actor = Actor(f'user:{self.manager.pk}', frozenset({'Planners'}))
        api = DiaryAPI(actor=actor)
        api.define_milestones(definitions={'target': 'Target'})
        self.template = api.create_template(name='Creation template')
        self.version = self.template.create_version(number=1, milestone_names=('target',))
        self.first = EntrySpec('Prepare', DateKind.SOURCE, milestone_name='target')
        self.second = EntrySpec('Review', DateKind.RELATIVE, milestone_name='target', day_offset=1)
        self.version.add_entry(spec=self.first)
        self.version.add_entry(spec=self.second)
        self.version.set_predecessors(entry_key=self.second.entry_key, predecessor_keys=[self.first.entry_key])
        self.version.approve()
        self.diary = api.create_diary(name='Selected diary', event_ref='creation:selected',
                                     milestone_dates={'target': date(2027, 6, 20)}, template_version_key=self.version.key)
        self.other_diary = api.create_diary(name='Other diary', event_ref='creation:other',
                                     milestone_dates={'target': date(2027, 6, 21)}, template_version_key=self.version.key)
        self.actor = replace(actor, calendar_keys=frozenset({self.diary.key}))
        self.diary = DiaryAPI(actor=self.actor).diary(key=self.diary.key)
        scope = override_settings(CREATION_TEST_KEYS=(self.diary.key,))
        scope.enable()
        self.addCleanup(scope.disable)
        self.client.force_login(self.user)

    def url(self, key=None):
        """Return the host creation URL with one explicit selected diary."""
        return reverse('host-create') + '?diary_key=' + str(key or self.diary.key)

    def payload(self, **values):
        """Return valid personal task input with a stable key for safe retries."""
        data = {'entry_key': str(uuid4()), 'name': '<New task>', 'description': 'Task description',
                'date_kind': DateKind.ONCE, 'fixed_date': '2027-06-22'}
        data.update(values)
        return data

    def manager_payload(self, **values):
        """Return manager input with an explicit owner and template base version."""
        data = self.payload(owner_kind=OwnerKind.PERSON, person_ref=f'user:{self.other.pk}',
                            expected_version_key=str(self.version.key))
        data.update(values)
        return data

    def combined_payload(self, **values):
        """Select an annual future rule independently of the diary's exact date."""
        data = self.manager_payload(add_to_template='on', **{'future-date_kind': DateKind.ANNUAL,
                                                           'future-month': '7', 'future-day': '3'})
        data.update(values)
        return data

    def snapshot(self):
        """Return diary and template records for rollback and no-write checks."""
        return (list(CalendarEntry.objects.order_by('pk').values()),
                list(TemplateVersion.objects.order_by('pk').values()),
                list(TemplateEntry.objects.order_by('pk').values()))


# DV1-029, DV1-030, DV1-033: HTTP and callable checks use a separate PostgreSQL test database.
@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',),
                   ROOT_URLCONF=__name__)
class TaskCreationTests(TaskCreationFixtures, TestCase):
    """Make sure personal ownership, manager assignments, revision safety, and form errors operate correctly."""

    def test_user_creates_self_owned_private_task_and_safe_retry(self):
        """Use server ownership, keep the exact date, and create no template revision."""
        data = self.payload()
        response = self.client.post(self.url(), data)
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(response.url), 'Task added.')
        task = CalendarEntry.objects.get(calendar_id=self.diary.key, entry_key=data['entry_key'])
        self.assertEqual((task.owner_kind, task.person_ref, task.role_ref),
                         (OwnerKind.PERSON, f'user:{self.user.pk}', ''))
        self.assertEqual(task.fixed_date, date(2027, 6, 22))
        self.assertIsNone(task.source_entry_id)
        self.assertEqual(self.client.post(self.url(), data).status_code, 302)
        self.assertEqual(CalendarEntry.objects.filter(entry_key=data['entry_key']).count(), 1)
        self.assertEqual(TemplateVersion.objects.count(), 1)
        other_actor = Actor(f'user:{self.other.pk}', frozenset({'Participants'}), frozenset({self.diary.key}))
        entries = DiaryAPI(actor=other_actor).diary(key=self.diary.key).read()['entries']
        self.assertNotIn(task.entry_key, {entry['entry_key'] for entry in entries})
        data['name'] = 'Changed retry'
        self.assertEqual(self.client.post(self.url(), data).status_code, 400)
        task.refresh_from_db()
        self.assertEqual(task.name, '<New task>')

    def test_user_cannot_forge_owner_or_template_selection(self):
        """Reject all modified ownership and template fields without saving any records."""
        before = self.snapshot()
        for values in ({'person_ref': f'user:{self.other.pk}'}, {'owner_kind': OwnerKind.ROLE, 'role_ref': 'Helpers'},
                       {'owner_kind': OwnerKind.TEAM}, {'add_to_template': 'on'},
                       {'expected_version_key': str(self.version.key)}, {'role_ref': 'Helpers'}):
            with self.subTest(values=values):
                self.assertEqual(self.client.post(self.url(), self.payload(**values)).status_code, 400)
                self.assertEqual(self.snapshot(), before)
        page = self.client.get(self.url())
        self.assertNotContains(page, 'Template for future diaries')
        self.assertNotContains(page, 'type="checkbox"')

    def test_manager_assigns_person_role_and_team_without_revising_template(self):
        """Resolve current eligible people and configured roles for all manager owner types."""
        self.client.force_login(self.manager)
        for index, owner in enumerate(({'owner_kind': OwnerKind.PERSON, 'person_ref': f'user:{self.other.pk}'},
                                       {'owner_kind': OwnerKind.ROLE, 'person_ref': '', 'role_ref': 'Helpers'},
                                       {'owner_kind': OwnerKind.TEAM, 'person_ref': ''})):
            data = self.manager_payload(name=f'Manager task {index}', **owner)
            with self.subTest(owner=owner):
                self.assertEqual(self.client.post(self.url(), data).status_code, 302)
                stored = CalendarEntry.objects.get(entry_key=data['entry_key'])
                self.assertEqual(stored.owner_kind, owner['owner_kind'])
        self.assertEqual(TemplateVersion.objects.count(), 1)
        before = self.snapshot()
        for owner in ({'person_ref': f'user:{self.outsider.pk}'}, {'person_ref': 'user:invalid'},
                      {'owner_kind': OwnerKind.ROLE, 'role_ref': 'Planners'},
                      {'owner_kind': OwnerKind.ROLE, 'role_ref': 'Missing'}):
            with self.subTest(owner=owner):
                self.assertEqual(self.client.post(self.url(), self.manager_payload(**owner)).status_code, 400)
                self.assertEqual(self.snapshot(), before)
        self.other.groups.clear()
        self.assertEqual(self.client.post(self.url(), self.manager_payload()).status_code, 400)

    def test_combined_save_preserves_snapshots_graph_and_future_creation(self):
        """Create one approved revision with a shared task key while keeping existing diary records."""
        self.client.force_login(self.manager)
        before_other = list(CalendarEntry.objects.filter(calendar_id=self.other_diary.key).order_by('pk').values())
        before_selected = list(CalendarEntry.objects.filter(calendar_id=self.diary.key).order_by('pk').values())
        data = self.combined_payload()
        response = self.client.post(self.url(), data)
        self.assertEqual(response.status_code, 302)
        latest = self.template.latest_version().read()
        self.assertEqual(latest['number'], 2)
        self.assertEqual(latest['status'], VersionStatus.APPROVED)
        task = CalendarEntry.objects.get(calendar_id=self.diary.key, entry_key=data['entry_key'])
        template_task = TemplateEntry.objects.get(version_id=latest['key'], entry_key=task.entry_key)
        self.assertEqual((task.date_kind, task.fixed_date), (DateKind.ONCE, date(2027, 6, 22)))
        self.assertEqual((template_task.date_kind, template_task.month, template_task.day), (DateKind.ANNUAL, 7, 3))
        self.assertEqual(template_task.person_ref, task.person_ref)
        self.assertIsNone(task.source_entry_id)

        # The existing review task must keep its predecessor in the new template version.
        review = next(entry for entry in latest['entries'] if entry['entry_key'] == self.second.entry_key)
        self.assertEqual(review['predecessors'], (self.first.entry_key,))
        self.assertEqual(list(CalendarEntry.objects.filter(calendar_id=self.other_diary.key).order_by('pk').values()), before_other)
        self.assertEqual(list(CalendarEntry.objects.filter(calendar_id=self.diary.key).exclude(pk=task.pk).order_by('pk').values()), before_selected)
        self.assertEqual(EventCalendar.objects.get(pk=self.diary.key).template_version_id, self.version.key)
        future = DiaryAPI(actor=self.actor).create_diary(name='Future diary', event_ref='creation:future',
                    template_name='Creation template', milestone_dates={'target': date(2028, 6, 20)})
        self.assertEqual(CalendarEntry.objects.filter(calendar_id=future.key, entry_key=task.entry_key).count(), 1)
        before_retry = self.snapshot()
        self.assertEqual(self.client.post(self.url(), data).status_code, 400)
        self.assertEqual(self.snapshot(), before_retry)

    def test_future_rule_is_explicit_and_validated_before_any_write(self):
        """Require a reusable rule and keep submitted task data after a rejected combined save."""
        self.client.force_login(self.manager)
        before = self.snapshot()
        for future_values in ({'future-date_kind': ''}, {'future-date_kind': DateKind.ONCE},
                              {'future-month': '2', 'future-day': '30'},
                              {'future-date_kind': DateKind.SOURCE, 'future-milestone_name': 'missing'}):
            data = self.combined_payload(**future_values)
            with self.subTest(values=future_values):
                response = self.client.post(self.url(), data)
                self.assertEqual(response.status_code, 400)
                self.assertContains(response, '&lt;New task&gt;', status_code=400)
                self.assertEqual(self.snapshot(), before)
        page = self.client.get(self.url())
        self.assertFalse(page.context['creation_form']['add_to_template'].value())
        self.assertNotContains(page, 'name="future-date_kind" required')
        self.assertContains(page, 'diary-create-template-review')
        self.assertContains(page, '(approved)')

    def test_milestone_rules_and_latest_revision_are_preserved(self):
        """Keep newer template tasks and calculate diary offsets independently from future offsets."""
        self.client.force_login(self.manager)
        newer = EntrySpec('Added after diary creation', DateKind.ANNUAL, month=8, day=1)
        latest = self.template.save_version(entries=(self.first, self.second, newer),
            predecessors={self.second.entry_key: (self.first.entry_key,)}, expected_version_key=self.version.key)
        for kind, future_offset in ((DateKind.SOURCE, 0), (DateKind.RELATIVE, -3)):
            data = self.combined_payload(name=f'New {kind} task', date_kind=DateKind.RELATIVE,
                        milestone_name='target', day_offset='2', expected_version_key=str(latest.key),
                        **{'future-date_kind': kind, 'future-milestone_name': 'target',
                           'future-day_offset': str(future_offset)})
            with self.subTest(kind=kind):
                self.assertEqual(self.client.post(self.url(), data).status_code, 302)
                latest = self.template.latest_version()
                stored = CalendarEntry.objects.get(entry_key=data['entry_key'])
                self.assertEqual(stored.due_date, date(2027, 6, 22))
                future = TemplateEntry.objects.get(version_id=latest.key, entry_key=stored.entry_key)
                self.assertEqual(future.date_kind, kind)
                self.assertEqual(future.day_offset, future_offset)
                self.assertTrue(TemplateEntry.objects.filter(version_id=latest.key, entry_key=newer.entry_key).exists())
                self.assertFalse(CalendarEntry.objects.filter(calendar_id=self.diary.key, entry_key=newer.entry_key).exists())

    def test_documents_fragments_and_invalid_dates_preserve_input(self):
        """Render accessible creation content and reject missing or impossible dates without storage changes."""
        from django.template import engines

        before = self.snapshot()
        page = self.client.get(self.url())
        self.assertEqual(page.content.lower().count(b'<!doctype html>'), 1)
        self.assertNotContains(page, 'style=')
        context = {name: page.context[name] for name in ('diary_data', 'creation_form', 'creation_manager', 'future_form')}
        fragment = engines['django'].from_string('{% include "Diary/partials/task_create.html" %}').render(context)
        self.assertNotIn('<!doctype', fragment.lower())
        self.assertIn('diary-create-save', fragment)
        for values in ({'fixed_date': ''}, {'date_kind': DateKind.ANNUAL, 'month': '2', 'day': '30'},
                       {'date_kind': DateKind.SOURCE, 'milestone_name': ''}):
            with self.subTest(values=values):
                response = self.client.post(self.url(), self.payload(**values))
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.snapshot(), before)

    def test_stale_template_and_storage_failure_roll_back_both_additions(self):
        """Reject a stale editor base and undo the diary addition if template saving fails."""
        self.client.force_login(self.manager)
        data = self.combined_payload()
        self.template.save_version(entries=(self.first, self.second),
            predecessors={self.second.entry_key: (self.first.entry_key,)}, expected_version_key=self.version.key)
        before = self.snapshot()
        response = self.client.post(self.url(), data)
        self.assertContains(response, 'This template changed.', status_code=400)
        self.assertEqual(self.snapshot(), before)
        data['expected_version_key'] = str(self.template.latest_version().key)
        with patch.object(DiaryTemplate, 'save_version', side_effect=ValidationError('Template save failed.')):
            self.assertContains(self.client.post(self.url(), data), 'Template save failed.', status_code=400)
        self.assertEqual(self.snapshot(), before)
        with patch('Diary.api.DiaryTemplateVersion.approve', side_effect=ValidationError('Approval failed.')):
            self.assertContains(self.client.post(self.url(), data), 'Approval failed.', status_code=400)
        self.assertEqual(self.snapshot(), before)

    def test_permissions_scope_closed_diary_and_read_only_chooser(self):
        """Reject unauthorized targets and closed diaries while keeping GET requests free from writes."""
        before = self.snapshot()
        self.assertContains(self.client.get(reverse('host-create')), 'Selected diary')
        self.assertNotContains(self.client.get(reverse('host-create')), 'Other diary')
        self.assertEqual(self.client.post(reverse('host-create'), self.payload()).status_code, 400)
        self.assertEqual(self.client.get(self.url(self.other_diary.key)).status_code, 403)
        self.assertEqual(self.client.post(self.url(self.other_diary.key), self.payload()).status_code, 403)
        missing = uuid4()
        with self.settings(CREATION_TEST_KEYS=(missing,)):
            self.assertEqual(self.client.get(self.url(missing)).status_code, 404)
        for value in ('', 'invalid'):
            with self.subTest(value=value):
                self.assertEqual(self.client.get(reverse('host-create') + '?diary_key=' + value).status_code, 400)
        default = reverse('Diary:task-create')
        self.assertEqual(self.client.get(default, {'diary_key': str(self.diary.key),
                             'permitted_diary_keys': str(self.diary.key)}).status_code, 403)
        self.assertEqual(self.snapshot(), before)
        self.diary.close()
        self.assertContains(self.client.get(self.url()), 'This diary is closed.')
        self.assertEqual(self.client.post(self.url(), self.payload()).status_code, 400)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url()).status_code, 302)

    def test_csrf_and_current_membership_protect_direct_posts(self):
        """Require a CSRF token and current access membership before task writes."""
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(strict.post(self.url(), self.payload()).status_code, 403)
        self.client.force_login(self.manager)
        self.manager.groups.clear()
        self.assertEqual(self.client.post(self.url(), self.combined_payload()).status_code, 403)

    def test_api_rejects_template_escalation_and_mismatched_combined_specs(self):
        """Apply manager permissions and shared identity rules below the HTML interface."""
        actor = Actor(f'user:{self.user.pk}', frozenset({'Participants'}), frozenset({self.diary.key}))
        diary = DiaryAPI(actor=actor).diary(key=self.diary.key)
        spec = EntrySpec('API task', DateKind.ONCE, fixed_date=date(2027, 6, 22),
                         owner_kind=OwnerKind.PERSON, person_ref=actor.reference)
        reusable = replace(spec, date_kind=DateKind.ANNUAL, fixed_date=None, month=7, day=3)
        before = self.snapshot()
        with self.assertRaises(PermissionDenied):
            diary.create_task(spec=spec, template_spec=reusable, expected_version_key=self.version.key)
        for invalid in (spec, replace(reusable, entry_key=uuid4()), replace(reusable, name='Different task'),
                        replace(reusable, person_ref=f'user:{self.other.pk}')):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    self.diary.create_task(spec=spec, template_spec=invalid, expected_version_key=self.version.key,
                                           directory=DjangoOwnerDirectory())
        self.assertEqual(self.snapshot(), before)


# DV1-033: PostgreSQL locks serialize combined saves and duplicate requests.
@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',),
                   ROOT_URLCONF=__name__)
class TaskCreationConcurrencyTests(TaskCreationFixtures, TransactionTestCase):
    """Make sure simultaneous additions cannot duplicate tasks or overwrite a template revision."""

    # Limit transaction cleanup to tested apps while including the configured user model.
    available_apps = sorted({'Diary', 'django.contrib.auth', 'django.contrib.contenttypes',
                             'django.contrib.sessions', get_user_model()._meta.app_config.name})

    def race(self, specs):
        """Run two combined saves from the same template base on independent database connections."""
        self.assertEqual(connection.vendor, 'postgresql')
        start = Barrier(2)

        def save(spec):
            """Attempt one combined save after both callers reach the transaction boundary."""
            close_old_connections()
            try:
                start.wait(timeout=10)
                reusable = replace(spec, date_kind=DateKind.ANNUAL, fixed_date=None, month=7, day=3)
                self.diary.create_task(spec=spec, template_spec=reusable,
                                       expected_version_key=self.version.key, directory=DjangoOwnerDirectory())
                return 'saved'
            except ValidationError:
                return 'rejected'
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(save, spec) for spec in specs]
            self.assertCountEqual([result.result(timeout=20) for result in results], ['saved', 'rejected'])
        self.assertEqual(TemplateVersion.objects.count(), 2)
        self.assertEqual(CalendarEntry.objects.filter(calendar_id=self.diary.key).count(), 3)
        self.assertEqual(TemplateEntry.objects.filter(version__number=2).count(), 3)

    def test_concurrent_different_tasks_reject_the_stale_revision(self):
        """Keep one winner and roll back the task from the stale combined save."""
        self.race(tuple(EntrySpec(name, DateKind.ONCE, fixed_date=date(2027, 6, 22))
                        for name in ('Concurrent first', 'Concurrent second')))

    def test_concurrent_retries_create_one_task_and_one_revision(self):
        """Reject a duplicate request after the first transaction commits its shared key."""
        spec = EntrySpec('Concurrent retry', DateKind.ONCE, fixed_date=date(2027, 6, 22))
        self.race((spec, spec))
