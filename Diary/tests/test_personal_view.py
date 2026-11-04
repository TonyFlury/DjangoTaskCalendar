"""Verify personal task selection, host scope, display filters, and private predecessors."""
from dataclasses import replace
from datetime import date, datetime, timezone as datetime_timezone
from itertools import product
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.test import RequestFactory, TestCase, override_settings
from django.urls import include, path, reverse

from Diary.api import Actor, DiaryAPI, EntrySpec
from Diary.choices import DateKind, OwnerKind
from Diary.models import CalendarEntry, EntryDependency, EventCalendar
from Diary.tests.legacy_dependencies import seed_legacy_dependencies
from Diary.views import DjangoOwnerDirectory, PersonalDiaryView


class HostPersonalDiaryView(PersonalDiaryView):
    """Supply a test host's current permitted keys through trusted context."""

    def get_context_data(self, **kwargs):
        """Read permitted keys and an optional selector from test host settings."""
        context = super().get_context_data(**kwargs)
        context['permitted_diary_keys'] = settings.PERSONAL_TEST_KEYS
        context['diary_key'] = getattr(settings, 'PERSONAL_TEST_CONTEXT_KEY', None)
        return context


def handler403(request, exception):
    """Keep denied requests independent of host error-page navigation."""
    return HttpResponseForbidden('Access denied.')


urlpatterns = [
    path('host-personal/', HostPersonalDiaryView.as_view(), name='host-personal'),
    path('diary/', include('Diary.urls')),
]


class PersonalDiaryFixtures:
    """Prepare owned tasks, private blockers, multiple roles, and separate diary scopes."""

    def setUp(self):
        """Create two permitted open diaries, a closed diary, and an unpermitted diary."""
        self.clock = patch('django.utils.timezone.now', return_value=datetime(2027, 6, 12, 12, tzinfo=datetime_timezone.utc))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        model = get_user_model()
        self.user = model._default_manager.create_user(**{model.USERNAME_FIELD: 'owner@example.test'})
        self.other_user = model._default_manager.create_user(**{model.USERNAME_FIELD: 'other@example.test'})
        self.manager = model._default_manager.create_user(**{model.USERNAME_FIELD: 'planner@example.test'})
        self.user_group = Group.objects.create(name='Participants')
        self.manager_group = Group.objects.create(name='Planners')
        self.helpers = Group.objects.create(name='Helpers')
        self.reviewers = Group.objects.create(name='Reviewers')
        self.user.groups.add(self.user_group, self.helpers, self.reviewers)
        self.other_user.groups.add(self.user_group)
        self.manager.groups.add(self.manager_group)
        self.manager_actor = Actor(f'user:{self.manager.pk}', frozenset({'Planners'}))
        self.user_ref = f'user:{self.user.pk}'
        client = DiaryAPI(actor=self.manager_actor)
        client.define_milestones(definitions={'target': 'Target', 'unset': 'Unset', 'blocker': 'Template blocker'})
        self.version = client.create_template(name='Personal template').create_version(number=1, milestone_names=('target', 'blocker'))
        self.role_spec = EntrySpec('Shared group task', DateKind.SOURCE, milestone_name='target',
                                  owner_kind=OwnerKind.ROLE, role_ref='Helpers')
        self.version.add_entry(spec=self.role_spec)
        self.blocker_spec = EntrySpec('Other owner predecessor', DateKind.SOURCE, milestone_name='blocker',
            owner_kind=OwnerKind.PERSON, person_ref=f'user:{self.other_user.pk}')
        self.version.add_entry(spec=self.blocker_spec, directory=DjangoOwnerDirectory())
        self.version.approve()
        self.keys = []
        for index in range(4):
            diary = client.create_diary(name='Same diary name', event_ref=f'personal:{index}',
                                        milestone_dates={'target': date(2027, 6, 20), 'blocker': date(2027, 6, 10)},
                                        template_version_key=self.version.key)
            self.keys.append(diary.key)
        self.manager_actor = replace(self.manager_actor, calendar_keys=frozenset(self.keys))
        self.first = DiaryAPI(actor=self.manager_actor).diary(key=self.keys[0])
        self.closed = DiaryAPI(actor=self.manager_actor).diary(key=self.keys[2])
        self.ready = self.add_task('My ready task', date(2027, 6, 20))
        self.late = self.add_task('My late task', date(2027, 6, 11))
        self.blocked = self.add_task('My blocked task', date(2027, 6, 21))
        self.blocked_late = self.add_task('My late blocked task', date(2027, 6, 12))
        self.private = self.add_task('<Private blocker>', date(2027, 6, 10), person=f'user:{self.other_user.pk}')
        seed_legacy_dependencies(self.keys[0], (
            (self.blocked, (self.blocker_spec.entry_key,)),
            (self.blocked_late, (self.blocker_spec.entry_key,)),
        ))
        self.undated = self.add_task('My undated task', None)
        self.done = self.add_task('My completed task', date(2027, 6, 1))
        completed = CalendarEntry.objects.get(calendar_id=self.keys[0], entry_key=self.done)
        completed.completed_at = datetime(2027, 6, 2, tzinfo=datetime_timezone.utc)
        completed.completed_by_ref = self.user_ref
        completed.save()
        self.team = self.first.add_entry(spec=EntrySpec('Whole-team task', DateKind.ONCE, fixed_date=date(2027, 6, 20)))
        self.role_task = self.first.add_entry(spec=EntrySpec('Second role task', DateKind.ONCE, fixed_date=date(2027, 6, 20),
                                                          owner_kind=OwnerKind.ROLE, role_ref='Reviewers'))
        self.closed.close()
        self.user_actor = Actor(self.user_ref, frozenset({'Participants', 'Helpers', 'Reviewers'}),
                                frozenset(self.keys[:3]))
        self.client.force_login(self.user)
        self.scope = override_settings(PERSONAL_TEST_KEYS=tuple(self.keys[:3]))
        self.scope.enable()
        self.addCleanup(self.scope.disable)

    def add_task(self, name, due, person=None):
        """Add a person-owned task through the manager's validated owner directory."""
        kind = DateKind.ONCE
        values = {'fixed_date': due}

        # An unset milestone supplies an undated task without an invalid one-time rule.
        if due is None:
            kind = DateKind.ANNUAL
            values = {'month': 2, 'day': 29, 'year_offset': 1}
        return self.first.add_entry(spec=EntrySpec(name, kind, owner_kind=OwnerKind.PERSON,
                                                   person_ref=person or self.user_ref, **values),
                                    directory=DjangoOwnerDirectory())

    def page(self, **params):
        """Read the test host's personal route with optional GET filters."""
        return self.client.get(reverse('host-personal'), params)

    @staticmethod
    def names(response):
        """Return displayed task names across every rendered diary group."""
        return [task['name'] for group in response.context['task_groups'] for task in group['tasks']]


# DV1-020, DV1-021, DV1-031, DV1-049: Personal selection and privacy across the callable API and HTML view.
@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers', 'Reviewers'),
                   DIARY_TIME_ZONE='Europe/London', ROOT_URLCONF=__name__)
class PersonalDiaryTests(PersonalDiaryFixtures, TestCase):
    """Verify personal selectors, ownership, display defaults, and related-task privacy."""

    def test_default_shows_owned_ready_tasks_grouped_by_name_and_key(self):
        """Exclude blocked, completed, closed-diary, unowned, and unpermitted tasks by default."""
        response = self.page()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(self.names(response)), {'My ready task', 'My late task', 'My undated task',
                                                    'Shared group task', 'Second role task'})
        self.assertEqual(len(response.context['task_groups']), 2)
        self.assertEqual({group['key'] for group in response.context['task_groups']}, set(self.keys[:2]))
        self.assertContains(response, 'My Diary')
        self.assertContains(response, 'type="checkbox"', count=2)
        self.assertEqual(response.content.lower().count(b'<!doctype html>'), 1)
        self.assertNotContains(response, str(self.keys[3]))

    def test_both_selector_methods_and_trusted_context_variants(self):
        """Apply GET, view attributes, extra context, and dynamic context to the same permitted diary."""
        response = self.page(diary_key=self.keys[0])
        self.assertEqual(len(response.context['task_groups']), 1)
        self.assertEqual(response.context['diary_data']['key'], self.keys[0])
        with self.settings(PERSONAL_TEST_CONTEXT_KEY=self.keys[0]):
            trusted = self.page()
        self.assertEqual(self.names(response), self.names(trusted))
        request = RequestFactory().get('/embedded/')
        request.user = self.user
        for options in ({'diary_key': self.keys[0], 'permitted_diary_keys': self.keys[:1]},
                        {'extra_context': {'diary_key': self.keys[0], 'permitted_diary_keys': self.keys[:1]}}):
            with self.subTest(options=options), patch('Diary.views.render', wraps=render) as renderer:
                self.assertEqual(PersonalDiaryView.as_view(**options)(request).status_code, 200)
                self.assertEqual(renderer.call_args.args[2]['diary_data']['key'], self.keys[0])

    def test_invalid_conflicting_unknown_and_unauthorized_selectors(self):
        """Reject unsafe selectors without falling back to a broader scope."""
        for selector in ('', 'not-a-uuid'):
            with self.subTest(selector=selector):
                self.assertEqual(self.page(diary_key=selector).status_code, 400)
        self.assertEqual(self.page(diary_key=[self.keys[0], self.keys[1]]).status_code, 400)
        self.assertEqual(self.page(diary_key=[self.keys[0], self.keys[0]]).status_code, 200)
        with self.settings(PERSONAL_TEST_CONTEXT_KEY=self.keys[1]):
            self.assertEqual(self.page(diary_key=self.keys[0]).status_code, 400)
        self.assertEqual(self.page(diary_key=self.keys[3]).status_code, 403)
        missing = uuid4()
        with self.settings(PERSONAL_TEST_KEYS=(missing,)):
            self.assertEqual(self.page(diary_key=missing).status_code, 404)
        default = self.client.get(reverse('Diary:personal-diary'), {'permitted_diary_keys': self.keys[0]})
        self.assertContains(default, 'No tasks match these filters.')
        self.assertEqual(self.client.get(reverse('Diary:personal-diary'), {'diary_key': self.keys[0],
                              'permitted_diary_keys': self.keys[0]}).status_code, 403)

    def test_checkbox_and_status_filter_combinations(self):
        """Apply display choices while keeping Late, Ready, and Blocked categories separate."""
        for show_blocked, include_team, status in product((False, True), (False, True), ('all', 'late', 'ready', 'blocked')):
            query = {'diary_key': self.keys[0], 'task_status': status}

            # Normal browsers omit a clear checkbox from GET input.
            if show_blocked:
                query['show_blocked'] = 'on'

            # Whole-team work needs an explicit request in every status category.
            if include_team:
                query['include_whole_team'] = 'on'
            with self.subTest(show_blocked=show_blocked, include_team=include_team, status=status):
                names = set(self.names(self.page(**query)))
                expected = {'Shared group task', 'Second role task', 'My ready task', 'My late task', 'My undated task'}

                # The checkbox changes only the general open-task display.
                if show_blocked:
                    expected |= {'My blocked task', 'My late blocked task'}

                # Team tasks remain separate from the user's personal and role assignments.
                if include_team:
                    expected.add('Whole-team task')

                # A specific status selects its exact category regardless of the blocked checkbox.
                if status == 'late':
                    expected = {'My late task', 'My late blocked task'}
                elif status == 'blocked':
                    expected = {'My blocked task'}
                elif status == 'ready':
                    expected.discard('My late task')
                    expected -= {'My blocked task', 'My late blocked task'}
                self.assertEqual(names, expected)
        self.assertEqual(self.page(task_status='invalid').status_code, 400)

    def test_private_entries_and_template_blockers_preserve_state(self):
        """Protect private entries while template predecessors determine blocking and warning state."""
        diary = DiaryAPI(actor=self.user_actor).diary(key=self.keys[0])
        data = diary.read()
        self.assertNotIn(self.private, {entry['entry_key'] for entry in data['entries']})
        task = next(entry for entry in data['entries'] if entry['entry_key'] == self.blocked)
        self.assertFalse(task['ready'])
        self.assertEqual(task['predecessors'], (self.blocker_spec.entry_key,))
        self.assertEqual(task['blocking_predecessors'], (self.blocker_spec.entry_key,))
        self.assertNotIn(self.private, {entry['entry_key'] for entry in diary.available_predecessors(entry_key=self.ready)})
        with self.assertRaises(CalendarEntry.DoesNotExist):
            diary.available_predecessors(entry_key=self.private)
        tasks = DiaryAPI(actor=self.user_actor).personal_tasks(diary_key=self.keys[0])
        blocked = next(task for task in tasks if task['entry_key'] == self.blocked)
        self.assertTrue(blocked['blocked_late'])
        self.assertEqual(blocked['state'], 'blocked')
        response = self.page(show_blocked='on')
        self.assertNotContains(response, 'Private blocker')
        self.assertNotContains(response, str(self.private))
        self.assertContains(response, 'diary-task-blocked-late')
        completed = CalendarEntry.objects.get(calendar_id=self.keys[0], entry_key=self.blocker_spec.entry_key)
        completed.completed_at = datetime(2027, 6, 12, tzinfo=datetime_timezone.utc)
        completed.completed_by_ref = f'user:{self.other_user.pk}'
        completed.save()
        self.assertIn('My blocked task', self.names(self.page()))
        self.assertIn('My late blocked task', self.names(self.page()))

    def test_role_membership_changes_and_manager_personal_selection(self):
        """Use current role membership without exposing other people's tasks to a manager's personal view."""
        self.user.groups.remove(self.helpers)
        self.assertNotIn('Shared group task', self.names(self.page()))
        self.assertIn('Second role task', self.names(self.page()))
        self.client.force_login(self.manager)
        self.assertEqual(self.names(self.page()), [])
        data = self.first.read()
        self.assertIn(self.private, {entry['entry_key'] for entry in data['entries']})

    def test_blockers_owned_by_another_group_and_template_person_visibility(self):
        """Keep unrelated group work outside the personal list while it blocks owned tasks."""
        role = Group.objects.create(name='OutsideRole')
        self.other_user.groups.add(role)
        stored = CalendarEntry.objects.get(calendar_id=self.keys[0], entry_key=self.blocker_spec.entry_key)
        stored.name = 'Other group work'
        stored.owner_kind = OwnerKind.ROLE
        stored.role_ref = 'OutsideRole'
        stored.person_ref = ''
        stored.save()
        blocker = stored.entry_key
        owned = self.add_task('Blocked by other group', date(2027, 6, 20))
        seed_legacy_dependencies(self.keys[0], ((owned, (blocker,)),))
        self.assertNotIn('Blocked by other group', self.names(self.page()))
        expanded = self.page(show_blocked='on', include_whole_team='on')
        self.assertIn('Blocked by other group', self.names(expanded))
        self.assertNotIn('Other group work', self.names(expanded))
        copied = CalendarEntry.objects.get(calendar_id=self.keys[0], entry_key=self.role_spec.entry_key)
        copied.owner_kind = OwnerKind.PERSON
        copied.role_ref = ''
        copied.person_ref = f'user:{self.other_user.pk}'
        copied.save()
        user_diary = DiaryAPI(actor=self.user_actor).diary(key=self.keys[0])
        self.assertIn(copied.entry_key, {entry['entry_key'] for entry in user_diary.read()['entries']})
        self.assertNotIn(copied.entry_key, {entry['entry_key'] for entry in user_diary.personal_tasks()})

    def test_permissions_no_writes_and_closed_diary_context(self):
        """Require current access membership and keep personal reads free from mutation."""
        before = list(CalendarEntry.objects.order_by('pk').values())
        self.assertContains(self.page(diary_key=self.keys[2]), 'Closed diary')
        self.assertEqual(self.names(self.page(diary_key=self.keys[2])), [])
        self.assertEqual(self.client.post(reverse('host-personal'), {}).status_code, 405)
        self.page(show_blocked='on', include_whole_team='on')
        self.assertEqual(list(CalendarEntry.objects.order_by('pk').values()), before)
        self.assertEqual(EventCalendar.objects.count(), 4)
        self.client.logout()
        self.assertEqual(self.page().status_code, 302)
        self.client.force_login(self.other_user)
        self.other_user.groups.clear()
        self.assertEqual(self.page().status_code, 403)
        self.user.is_active = False
        request = RequestFactory().get('/personal/')
        request.user = self.user
        with self.assertRaises(PermissionDenied):
            PersonalDiaryView.as_view(permitted_diary_keys=self.keys)(request)

    def test_api_metadata_scope_ownership_and_lateness_boundary(self):
        """Return each owned task once with its diary identity and one shared local comparison date."""
        client = DiaryAPI(actor=self.user_actor)
        tasks = client.personal_tasks()
        identities = [(task['diary_key'], task['entry_key']) for task in tasks]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertEqual({task['diary_key'] for task in tasks}, set(self.keys[:2]))
        self.assertTrue(all(task['diary_name'] == 'Same diary name' for task in tasks))
        self.assertNotIn(self.team, {task['entry_key'] for task in tasks})
        self.assertIn(self.team, {task['entry_key'] for task in client.personal_tasks(include_whole_team=True)})
        with self.assertRaises(PermissionDenied):
            client.personal_tasks(diary_key=self.keys[3])
        instant = datetime(2027, 6, 11, 23, 30, tzinfo=datetime_timezone.utc)
        with patch('django.utils.timezone.now', return_value=instant):
            local = client.personal_tasks()
            with self.settings(DIARY_TIME_ZONE=None, TIME_ZONE='America/Los_Angeles'):
                del settings.DIARY_TIME_ZONE
                project = client.personal_tasks()
        self.assertTrue(next(task for task in local if task['entry_key'] == self.blocked_late)['late'])
        self.assertFalse(next(task for task in project if task['entry_key'] == self.blocked_late)['late'])

    def test_status_links_preserve_scope_and_counts_do_not_overlap(self):
        """Keep the selected diary in count links and make every count match its status selection."""
        response = self.page(diary_key=self.keys[0])
        for link in response.context['status_links']:
            self.assertIn(str(self.keys[0]), link['url'])
            selected = self.client.get(reverse('host-personal') + link['url'])
            self.assertEqual(len(self.names(selected)), link['count'])
        self.assertEqual({link['category']: link['count'] for link in response.context['status_links']},
                         {'late': 2, 'ready': 4, 'blocked': 1})

    # DV1-053: Predecessor eligibility depends on template provenance, not the creator's role.
    def test_non_template_predecessors_are_excluded_and_rejected_atomically(self):
        """Reject user and manager diary additions through API and normal model saves."""
        user_diary = DiaryAPI(actor=self.user_actor).diary(key=self.keys[0])
        user_key = user_diary.add_entry(spec=EntrySpec('User addition', DateKind.ONCE,
            fixed_date=date(2027, 6, 20), owner_kind=OwnerKind.PERSON, person_ref=self.user_ref))
        choices = {entry['entry_key'] for entry in self.first.available_predecessors(entry_key=self.ready)}
        self.assertNotIn(user_key, choices)
        self.assertNotIn(self.late, choices)
        self.assertIn(self.blocker_spec.entry_key, choices)
        before = tuple(EntryDependency.objects.filter(entry__calendar_id=self.keys[0]).values_list('entry_id', 'predecessor_id'))
        for key in (user_key, self.late):
            with self.subTest(key=key):
                with self.assertRaisesMessage(ValidationError, 'V1 does not allow dependency changes'):
                    self.first.set_predecessors(entry_key=self.blocked,
                        predecessor_keys=[self.blocker_spec.entry_key, key])
                with self.assertRaisesMessage(ValidationError, 'V1 does not allow dependency changes'):
                    EntryDependency.objects.create(
                        entry=CalendarEntry.objects.get(calendar_id=self.keys[0], entry_key=self.ready),
                        predecessor=CalendarEntry.objects.get(calendar_id=self.keys[0], entry_key=key))
        self.assertEqual(tuple(EntryDependency.objects.filter(entry__calendar_id=self.keys[0]).values_list('entry_id', 'predecessor_id')), before)
        copied = CalendarEntry.objects.get(calendar_id=self.keys[0], entry_key=self.blocker_spec.entry_key)
        copied.source_entry = None
        with self.assertRaisesMessage(ValidationError, 'cannot change its template source'):
            copied.save()
