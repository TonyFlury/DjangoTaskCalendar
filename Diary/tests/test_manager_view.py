"""Verify manager diary selectors, task filters, and completion history on PostgreSQL."""
from dataclasses import replace
from datetime import date, datetime, timezone as datetime_timezone
from itertools import product
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseForbidden, HttpResponseNotFound
from django.shortcuts import render
from django.template import engines
from django.test import RequestFactory, TestCase, override_settings
from django.urls import include, path, reverse

from Diary.api import Actor, DiaryAPI, EntrySpec
from Diary.choices import DateKind, OwnerKind
from Diary.models import CalendarEntry, EventCalendar
from Diary.tests.legacy_dependencies import seed_legacy_dependencies
from Diary.views import ManagerDiaryView


class HostManagerDiaryView(ManagerDiaryView):
    """Supply a test host's explicit permitted keys through trusted view context."""

    def get_context_data(self, **kwargs):
        """Read the test host scope from settings instead of request input."""
        context = super().get_context_data(**kwargs)
        context['permitted_diary_keys'] = settings.MANAGER_TEST_KEYS
        context['diary_key'] = getattr(settings, 'MANAGER_TEST_CONTEXT_KEY', None)
        return context


urlpatterns = [
    path('host-manager/', HostManagerDiaryView.as_view(), name='host-manager'),
    path('diary/', include('Diary.urls')),
]


def handler403(request, exception):
    """Keep isolated test errors independent of host error-page navigation."""
    return HttpResponseForbidden('Access denied.')


def handler404(request, exception):
    """Return an isolated missing-selection response without host template dependencies."""
    return HttpResponseNotFound('Diary not found.')


# DV1-013, DV1-018, DV1-019, DV1-022, DV1-039, DV1-041, DV1-042, DV1-044, DV1-052.
@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=(),
                   DIARY_TIME_ZONE='Europe/London', ROOT_URLCONF=__name__)
class ManagerDiaryTests(TestCase):
    """Exercise the production view with independent manager, person, and ownership groups."""

    def setUp(self):
        """Create two diaries and tasks spanning completion, blocking, and lateness states."""
        self.clock = patch('django.utils.timezone.now',
                           return_value=datetime(2027, 6, 12, 12, tzinfo=datetime_timezone.utc))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        model = get_user_model()
        self.manager = model._default_manager.create_user(**{model.USERNAME_FIELD: 'manager@example.test'})
        self.manager.groups.add(Group.objects.create(name='Planners'))
        self.user = model._default_manager.create_user(**{model.USERNAME_FIELD: 'participant@example.test'})
        self.user.groups.add(Group.objects.create(name='Participants'))
        self.role = Group.objects.create(name='Helpers')
        self.user.groups.add(self.role)
        self.actor = Actor(f'user:{self.manager.pk}', frozenset({'Planners'}))
        self.api = DiaryAPI(actor=self.actor)
        self.version = self.api.create_template(name='Manager template').create_version(number=1)
        self.version.add_entry(spec=EntrySpec('Template task', DateKind.ANNUAL, month=12, day=1))
        self.api.define_milestones(definitions={'manager_late': 'Late task', 'manager_future': 'Future task'})
        self.version.set_milestones(names=('manager_late', 'manager_future'))
        late_spec = EntrySpec('Late ready', DateKind.SOURCE, milestone_name='manager_late')
        future_spec = EntrySpec('Future ready', DateKind.SOURCE, milestone_name='manager_future')
        self.version.add_entry(spec=late_spec)
        self.version.add_entry(spec=future_spec)
        self.version.approve()
        dates = {'manager_late': date(2027, 6, 11), 'manager_future': date(2027, 6, 20)}
        self.diary = self.api.create_diary(name='<Selected diary>', milestone_dates=dates, event_ref='manager:1',
                                           template_version_key=self.version.key)
        self.other = self.api.create_diary(name='Other diary', milestone_dates=dates, event_ref='manager:2',
                                           template_version_key=self.version.key)
        self.actor = replace(self.actor, calendar_keys=frozenset({self.diary.key}))
        self.bound = DiaryAPI(actor=self.actor).diary(key=self.diary.key)
        self.late = late_spec.entry_key
        self.blocked_late = self.add_task('Late blocked', date(2027, 6, 12))
        self.future = future_spec.entry_key
        self.blocked = self.add_task('Future blocked by late', date(2027, 6, 21))
        self.ordinary_blocked = self.add_task('Future blocked', date(2027, 6, 22))
        self.undated = self.add_task('Undated', None)
        self.done = self.add_task('Completed history', date(2027, 6, 1))
        seed_legacy_dependencies(self.diary.key, (
            (self.blocked_late, (self.late,)), (self.blocked, (self.late,)),
            (self.ordinary_blocked, (self.future,)),
        ))
        completed = CalendarEntry.objects.get(calendar_id=self.diary.key, entry_key=self.done)
        completed.completed_at = datetime(2027, 6, 2, 10, tzinfo=datetime_timezone.utc)
        completed.completed_by_ref = f'user:{self.manager.pk}'
        completed.save()
        self.client.force_login(self.manager)
        self.scope = override_settings(MANAGER_TEST_KEYS=(self.diary.key,))
        self.scope.enable()
        self.addCleanup(self.scope.disable)

    def add_task(self, name, due):
        """Add a diary task with a one-time date or an unset milestone date."""
        kind = DateKind.ONCE
        values = {'fixed_date': due}

        # An unset source date provides a valid undated task without an invalid one-time rule.
        if due is None:
            self.api.define_milestones(definitions={'unset': 'Unset date'})
            kind = DateKind.ANNUAL
            values = {'month': 2, 'day': 29, 'year_offset': 1}
        return self.bound.add_entry(spec=EntrySpec(name, kind, **values))

    def page(self, **params):
        """Read the host route with a selected permitted diary and optional filters."""
        return self.client.get(reverse('host-manager'), {'diary_key': str(self.diary.key), **params})

    def test_get_and_trusted_context_select_the_same_diary(self):
        """Use GET input, extra context, view attributes, and dynamic host context consistently."""
        response = self.page()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['diary_data']['key'], self.diary.key)
        self.assertContains(response, '&lt;Selected diary&gt;')
        self.assertNotContains(response, 'Other diary')
        with self.settings(MANAGER_TEST_CONTEXT_KEY=self.diary.key):
            context_response = self.client.get(reverse('host-manager'))
        self.assertEqual(context_response.context['tasks'], response.context['tasks'])
        request = RequestFactory().get('/embedded-manager/')
        request.user = self.manager
        for options in (
            {'diary_key': self.diary.key, 'permitted_diary_keys': (self.diary.key,)},
            {'extra_context': {'diary_key': self.diary.key, 'permitted_diary_keys': (self.diary.key,)}},
        ):
            with self.subTest(options=options), patch('Diary.views.render', wraps=render) as renderer:
                direct = ManagerDiaryView.as_view(**options)(request)
                self.assertEqual(direct.status_code, 200)
                self.assertEqual(renderer.call_args.args[2]['diary_data']['key'], self.diary.key)

    def test_conflicting_malformed_repeated_and_unknown_selectors(self):
        """Reject conflicting or invalid inputs without falling back to another diary."""
        for value in ('', 'bad-key', '123'):
            with self.subTest(value=value):
                self.assertEqual(self.page(diary_key=value).status_code, 400)
        response = self.client.get(reverse('host-manager'), {'diary_key': [self.diary.key, self.other.key]})
        self.assertEqual(response.status_code, 400)
        same = self.client.get(reverse('host-manager'), {'diary_key': [self.diary.key, str(self.diary.key).upper()]})
        self.assertEqual(same.status_code, 200)
        # DV1-019, DEC-001: Conflicting URL and trusted context require a diagnostic without selector values.
        with self.settings(MANAGER_TEST_CONTEXT_KEY=self.other.key), self.assertLogs('Diary.views', level='WARNING') as logs:
            self.assertEqual(self.page().status_code, 400)
        self.assertIn('selector=diary_key', logs.output[0])
        self.assertIn('status=400', logs.output[0])
        self.assertNotIn(str(self.diary.key), logs.output[0])
        missing = uuid4()
        with self.settings(MANAGER_TEST_KEYS=(missing,)):
            self.assertEqual(self.page(diary_key=missing).status_code, 404)

    def test_scope_is_required_and_never_taken_from_the_query(self):
        """Reject unpermitted selectors through either input source and ignore forged scope parameters."""
        self.assertEqual(self.page(diary_key=self.other.key).status_code, 403)
        with self.settings(MANAGER_TEST_CONTEXT_KEY=self.other.key):
            self.assertEqual(self.client.get(reverse('host-manager')).status_code, 403)
        response = self.client.get(reverse('Diary:manager-diary'), {
            'diary_key': self.diary.key, 'permitted_diary_keys': str(self.diary.key),
        })
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, 'Late ready', status_code=403)

    def test_anonymous_ordinary_inactive_and_changed_membership_are_denied(self):
        """Require current manager membership for every read and reject all writes."""
        self.client.logout()
        self.assertEqual(self.page().status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.page().status_code, 403)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.post(reverse('host-manager'), {'diary_key': self.diary.key}).status_code, 405)
        self.manager.groups.clear()
        self.assertEqual(self.page().status_code, 403)
        self.manager.groups.add(Group.objects.get(name='Planners'))
        self.manager.is_active = False
        request = RequestFactory().get('/manager/', {'diary_key': self.diary.key})
        request.user = self.manager
        with self.assertRaises(PermissionDenied):
            ManagerDiaryView.as_view(permitted_diary_keys=(self.diary.key,))(request)

    def test_default_and_every_filter_combination(self):
        """Show all incomplete tasks by default and apply selected exclusions together."""
        for include_completed, exclude_blocked, exclude_non_late in product((False, True), repeat=3):
            values = {'include_completed': include_completed, 'exclude_blocked': exclude_blocked,
                      'exclude_non_late': exclude_non_late}

            # An absent checkbox is clear in a normal browser GET request.
            query = {name: 'on' for name, selected in values.items() if selected}
            with self.subTest(**values):
                response = self.page(**query)
                expected = {'Template task', 'Late ready', 'Late blocked', 'Future ready', 'Future blocked by late',
                            'Future blocked', 'Undated'}

                # The history option adds completed tasks before the exclusions apply.
                if include_completed:
                    expected.add('Completed history')

                # Blocked tasks are incomplete tasks with open predecessors.
                if exclude_blocked:
                    expected -= {'Late blocked', 'Future blocked by late', 'Future blocked'}

                # The late-only option excludes completed and undated tasks.
                if exclude_non_late:
                    expected &= {'Late ready', 'Late blocked'}
                self.assertEqual({task['name'] for task in response.context['tasks']}, expected)
                for name, selected in values.items():
                    self.assertEqual(response.context['filters'][name].value(), selected)
        default = self.page()
        dates = [task['date'] or date.max for task in default.context['tasks']]
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(default.content.lower().count(b'<!doctype html>'), 1)
        self.assertContains(default, 'type="checkbox"', count=3)

    def test_completion_history_preserves_actor_time_and_due_date(self):
        """Render the completing person, timestamp, preserved due date, and completion state."""
        response = self.page(include_completed='on')
        task = next(task for task in response.context['tasks'] if task['entry_key'] == self.done)
        self.assertEqual(task['date'], date(2027, 6, 1))
        self.assertTrue(task['completed'])
        self.assertFalse(task['late'])
        self.assertFalse(task['blocked'])
        self.assertContains(response, 'diary-manager-completion-time')
        self.assertContains(response, 'Due date at completion: 1 June 2027')
        self.assertContains(response, self.manager.get_username())

    def test_current_owners_private_entries_and_escaping(self):
        """Show permitted private entries and resolve current people and group members safely."""
        own = EntrySpec('<Private task>', DateKind.ONCE, fixed_date=date(2027, 6, 20),
                        owner_kind=OwnerKind.PERSON, person_ref=f'user:{self.user.pk}')
        user = Actor(f'user:{self.user.pk}', frozenset({'Participants'}), frozenset({self.diary.key}))
        DiaryAPI(actor=user).diary(key=self.diary.key).add_entry(spec=own)
        with self.settings(DIARY_TASK_OWNER_ROLES=('Helpers',)):
            self.bound.add_entry(spec=EntrySpec('Role task', DateKind.ONCE, fixed_date=date(2027, 6, 20),
                                               owner_kind=OwnerKind.ROLE, role_ref='Helpers'))
        response = self.page()
        self.assertContains(response, '&lt;Private task&gt;')
        self.assertNotContains(response, '<Private task>')
        person = next(task for task in response.context['tasks'] if task['entry_key'] == own.entry_key)
        self.assertEqual(person['owner_label'], self.user.get_username())
        self.assertContains(response, 'Current members:')
        self.assertContains(response, 'Whole team')
        self.user.groups.remove(self.role)
        self.assertContains(self.page(), 'No current members.')

    def test_empty_selection_empty_results_closed_diary_and_reads_without_writes(self):
        """Keep empty and closed views explicit and preserve every stored task record during reads."""
        before = list(CalendarEntry.objects.order_by('pk').values())
        self.assertContains(self.client.get(reverse('host-manager')), 'Select a permitted diary')
        CalendarEntry.objects.filter(calendar_id=self.diary.key, completed_at__isnull=True).update(
            completed_at=datetime(2027, 6, 12, tzinfo=datetime_timezone.utc), completed_by_ref='manager',
        )
        self.assertContains(self.page(), 'No tasks match these filters.')
        self.bound.close()
        closed = self.page(include_completed='on')
        self.assertContains(closed, 'Closed diary')
        self.assertContains(closed, 'Completed history')
        self.assertEqual(EventCalendar.objects.count(), 2)
        self.assertEqual(CalendarEntry.objects.count(), len(before))
        records = list(CalendarEntry.objects.order_by('pk').values())
        self.page()
        self.page(include_completed='on')
        self.assertEqual(list(CalendarEntry.objects.order_by('pk').values()), records)

    def test_late_boundary_uses_diary_zone_and_project_default(self):
        """Use the configured local day independently of the active user time zone."""
        instant = datetime(2027, 6, 11, 23, 30, tzinfo=datetime_timezone.utc)
        with patch('django.utils.timezone.now', return_value=instant):
            local = self.page(exclude_non_late='on')
            with self.settings(DIARY_TIME_ZONE=None, TIME_ZONE='America/Los_Angeles'):
                del settings.DIARY_TIME_ZONE
                project = self.page(exclude_non_late='on')
        self.assertIn('Late blocked', {task['name'] for task in local.context['tasks']})
        self.assertNotIn('Late blocked', {task['name'] for task in project.context['tasks']})

    def test_highlights_and_fragment_use_stable_styling_classes(self):
        """Give late tasks red priority and support embedding without another document."""
        response = self.page()
        self.assertContains(response, 'diary-manager-task-late', count=2)
        self.assertContains(response, 'diary-manager-task-blocked-late', count=1)
        self.assertContains(response, 'diary-manager-task-blocked"', count=1)
        context = {name: response.context[name] for name in ('diary_data', 'filters', 'tasks')}
        fragment = engines['django'].from_string('{% include "Diary/partials/manager_diary.html" %}').render(context)
        self.assertNotIn('<!doctype', fragment.lower())
        self.assertNotIn('style=', fragment)
        self.assertIn('diary-manager-filter-include-completed', fragment)
