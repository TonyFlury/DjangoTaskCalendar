"""DFUT-018: Calendar bounds, counts, privacy, history and host page integration."""
import json
from dataclasses import replace
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseForbidden
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import include, path, reverse

from Diary.api import DiaryAPI, EntrySpec
from Diary.calendar_navigation import calendar_return_state, calendar_return_token, SALT
from Diary.calendar_views import TaskCalendarView, TaskCalendarDataView
from Diary.choices import DateKind, OwnerKind
from Diary.models import CalendarEntry
from Diary.task_calendar import shifted_month
from Diary.tests.test_personal_view import PersonalDiaryFixtures
from Diary.views import DjangoOwnerDirectory, TaskDetailView


class CalendarScope:
    def get_diary_keys(self):
        return settings.CALENDAR_TEST_KEYS


class HostCalendarView(CalendarScope, TaskCalendarView):
    extra_context = {'task_detail_url_name': 'calendar-task'}


class HostCalendarDataView(CalendarScope, TaskCalendarDataView):
    pass


class HostCalendarTaskView(CalendarScope, TaskDetailView):
    pass


def handler403(request, exception):
    return HttpResponseForbidden('Access denied.')


urlpatterns = [
    path('calendar/', HostCalendarView.as_view(), name='calendar'),
    path('calendar/data/', HostCalendarDataView.as_view(), name='calendar-data'),
    path('calendar/task/<uuid:entry_key>/', HostCalendarTaskView.as_view(), name='calendar-task'),
    path('diary/', include('Diary.urls')),
]


@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants',
                   DIARY_TASK_OWNER_ROLES=('Helpers', 'Reviewers'), ROOT_URLCONF=__name__)
class TaskCalendarTests(PersonalDiaryFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.api = DiaryAPI(actor=self.user_actor)
        scope = override_settings(CALENDAR_TEST_KEYS=tuple(self.keys[:3]))
        scope.enable()
        self.addCleanup(scope.disable)

    def period(self, **kwargs):
        return self.api.task_period(anchor_date=date(2027, 6, 20), **kwargs)

    def test_period_boundaries_adjacent_months_and_leap_dates(self):
        week = self.period()
        self.assertEqual((week['start'], week['end']), (date(2027, 6, 14), date(2027, 6, 21)))
        for anchor, days in ((date(2021, 2, 15), 28), (date(2026, 11, 10), 42), (date(2028, 2, 29), 35)):
            month = self.api.task_period(view='month', anchor_date=anchor)
            self.assertEqual(len(month['days']), days)
            self.assertEqual(month['days'][0]['date'].weekday(), 0)
        self.assertEqual(shifted_month(date(2028, 1, 31), 1), date(2028, 2, 29))
        with override_settings(DIARY_WEEK_START=6):
            self.assertEqual(self.period()['start'], date(2027, 6, 20))
        start_task = self.add_task('Period start', week['start'])
        end_task = self.add_task('Next period start', week['end'])
        data = self.period()
        keys = {row['entry_key'] for day in data['days'] for row in day['tasks']}
        self.assertIn(start_task, keys)
        self.assertNotIn(end_task, keys)

    def test_counts_attention_and_private_predecessors_use_same_filtered_selection(self):
        month = self.period(view='month')
        visible = {row['entry_key'] for day in month['days'] for row in day['tasks']}
        self.assertNotIn(self.private, visible)
        self.assertNotIn(self.team, visible)
        self.assertEqual(month['undated']['count'], 1)
        self.assertEqual(month['late']['count'], 0, 'Visible month tasks must not repeat in the late panel')
        future = self.period()
        self.assertGreater(future['late']['count'], 0)
        self.assertTrue(all(not future['start'] <= row['date'] < future['end'] for row in future['late']['tasks']))
        with_team = self.period(include_whole_team=True)
        self.assertGreater(with_team['count'], future['count'])
        blocked = self.api.task_period(anchor_date=date(2027, 6, 21), query='My blocked task')
        card = next(row for day in blocked['days'] for row in day['tasks'])
        self.assertEqual(card['state'], 'blocked')
        self.assertTrue(card['blocked_late'], 'An earlier predecessor still affects this week')
        self.assertEqual(self.api.task_period(anchor_date=date(2027, 6, 21), query='My blocked task', show_blocked=False)['count'], 0)

    @override_settings(DIARY_CALENDAR_WEEK_PREVIEW=2, DIARY_CALENDAR_PAGE_SIZE=2)
    def test_full_counts_and_bounded_day_and_undated_pages(self):
        for number in range(7):
            self.add_task(f'Busy day {number}', date(2027, 6, 20))
        data = self.period(query='Busy day', selected_day=date(2027, 6, 20), page=2)
        day = next(item for item in data['days'] if item['date'] == date(2027, 6, 20))
        self.assertEqual((day['count'], len(day['tasks']), day['more']), (7, 2, 5))
        self.assertEqual((data['day']['count'], data['day']['page'], data['day']['pages']), (7, 2, 4))
        self.assertEqual(len(data['day']['tasks']), 2)
        self.assertEqual(self.period(query='Busy day', selected_day=date(2027, 6, 20), page=100)['day']['page'], 4)

    def test_completed_history_and_closed_diary_are_not_repeated_or_rescheduled(self):
        data = self.period(view='month', include_completed=True)
        done = [(day['date'], row) for day in data['days'] for row in day['tasks'] if row['entry_key'] == self.done]
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0][0], date(2027, 6, 1))
        self.assertEqual(done[0][1]['state'], 'completed')
        manager = DiaryAPI(actor=replace(self.manager_actor, calendar_keys=frozenset(self.keys[:3])))
        archive = manager.task_period(diary_key=self.keys[2], mode='manager', anchor_date=date(2027, 6, 20),
                                     directory=DjangoOwnerDirectory())
        self.assertTrue(archive['diary']['closed'])
        self.assertGreater(archive['count'] + archive['late']['count'] + archive['undated']['count'], 0)
        self.assertEqual(self.api.task_period(diary_key=self.keys[2], anchor_date=date(2027, 6, 20))['count'], 0)

    def test_manager_orphans_owner_filter_and_query_count_do_not_depend_on_day_cells(self):
        self.user.groups.remove(self.helpers)
        api = DiaryAPI(actor=self.manager_actor)
        data = api.task_period(diary_key=self.keys[0], mode='manager', anchor_date=date(2027, 6, 20),
                               owner='role:Helpers', directory=DjangoOwnerDirectory())
        rows = [row for day in data['days'] for row in day['tasks']]
        self.assertTrue(rows)
        self.assertTrue(all(row['orphaned'] for row in rows))
        self.assertTrue(all(row['role_ref'] == 'Helpers' for row in rows))
        with CaptureQueriesContext(connection) as week_queries:
            self.period()
        with CaptureQueriesContext(connection) as month_queries:
            self.period(view='month')
        self.assertEqual(len(week_queries), len(month_queries))
        self.assertLess(len(month_queries), 40)

    def test_signed_calendar_link_survives_task_write_and_filters_survive_navigation(self):
        page = self.client.get(reverse('calendar'), {'date': '2027-06-20', 'view': 'month', 'query': 'My ready task'})
        row = next(task for day in page.context['calendar']['days'] for task in day['tasks'])
        detail = self.client.get(row['detail_url'])
        self.assertEqual(detail.status_code, 200)
        token = detail.context['calendar_return_token']
        response = self.client.post(reverse('calendar-task', kwargs={'entry_key': self.ready}) + '?diary_key=' + str(self.keys[0]),
            {'action': 'add_note', 'note_key': str(uuid4()), 'text': 'Return from write', 'calendar_return': token})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith(reverse('calendar-task', kwargs={'entry_key': self.ready})))
        refreshed = self.client.get(response['Location'])
        self.assertEqual(refreshed.status_code, 200)
        returned = self.client.get(refreshed.context['calendar_return_url'])
        self.assertEqual(returned.status_code, 200)
        self.assertEqual(returned.context['calendar']['day']['date'], date(2027, 6, 20))
        self.assertEqual(returned.context['calendar_form'].cleaned_data['query'], 'My ready task')

    def test_local_dst_week_has_exactly_seven_dates(self):
        for stamp in (datetime(2027, 3, 28, 0, 30, tzinfo=timezone.utc), datetime(2027, 3, 28, 2, 30, tzinfo=timezone.utc)):
            with patch('django.utils.timezone.now', return_value=stamp), override_settings(DIARY_TIME_ZONE='Europe/London'):
                data = self.api.task_period(anchor_date=date(2027, 3, 28))
                self.assertEqual(len(data['days']), 7)
                self.assertEqual(data['today'], date(2027, 3, 28))

    def test_same_task_key_in_multiple_diaries_remains_two_cards(self):
        source = EntrySpec('Same identity', DateKind.ANNUAL, month=6, day=20)
        manager = DiaryAPI(actor=self.manager_actor)
        template = manager.create_template(name='Calendar shared key')
        version = template.save_version(entries=[source], predecessors={}, expected_version_key=None)
        diaries = [manager.create_diary(name=f'Copy {index}', template_version_key=version.key) for index in range(2)]
        api = DiaryAPI(actor=replace(self.user_actor, calendar_keys=frozenset(item.key for item in diaries)))
        data = api.task_period(anchor_date=date(2027, 6, 20), include_whole_team=True)
        rows = [row for day in data['days'] for row in day['tasks']]
        self.assertEqual({(row['diary_key'], row['entry_key']) for row in rows},
                         {(diary.key, source.entry_key) for diary in diaries})

    def test_dates_use_diary_zone_and_preserve_zero_and_negative_offsets(self):
        with patch('django.utils.timezone.now', return_value=datetime(2027, 6, 13, 0, 30, tzinfo=timezone.utc)):
            with override_settings(DIARY_TIME_ZONE='America/Los_Angeles'):
                self.assertEqual(self.period()['today'], date(2027, 6, 12))
            with override_settings(DIARY_TIME_ZONE='Europe/London'):
                self.assertEqual(self.period()['today'], date(2027, 6, 13))
        source = self.add_task('Offset source', date(2027, 6, 20))
        manager = DiaryAPI(actor=replace(self.manager_actor, calendar_keys=frozenset(self.keys[:3]))).diary(key=self.keys[0])
        for days in (0, -1):
            spec = EntrySpec(f'Offset {days}', DateKind.TASK, source_task_key=source, day_offset=days,
                             owner_kind=OwnerKind.PERSON, person_ref=self.user_ref)
            manager.add_entry(spec=spec, directory=DjangoOwnerDirectory())
        source_row = CalendarEntry.objects.get(calendar_id=self.keys[0], entry_key=source)
        manager.update_due_date(entry_key=source, due_date=date(2027, 6, 25), expected_revision=source_row.revision)
        data = self.period(query='Offset')
        placed = {row['name']: day['date'] for day in data['days'] for row in day['tasks']}
        self.assertEqual(placed, {'Offset 0': date(2027, 6, 20), 'Offset -1': date(2027, 6, 19)})

    def test_invalid_selectors_filters_and_permissions_are_rejected(self):
        for args in ({'view': 'year'}, {'mode': 'all'}, {'page': 0}, {'query': 42},
                     {'show_blocked': 'false'}, {'owner': 'team'}, {'selected_day': date(2028, 1, 1)}):
            with self.subTest(args=args), self.assertRaises(ValidationError):
                self.period(**args)
        with self.assertRaises(PermissionDenied):
            self.period(mode='manager', diary_key=self.keys[0])
        with self.assertRaises(PermissionDenied):
            self.period(diary_key=self.keys[3])
        with self.assertRaises(ValidationError):
            self.api.task_period(anchor_date=date(9999, 12, 31), view='month')

    def test_page_json_day_links_and_signed_return_flow(self):
        self.client.force_login(self.user)
        kwargs = {'date': '2027-06-20', 'view': 'month'}
        response = self.client.get(reverse('calendar'), kwargs)
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertContains(response, 'diary-calendar-month')
        self.assertContains(response, 'Calendar filters')
        self.assertNotContains(response, '&lt;Private blocker&gt;')
        json_response = self.client.get(reverse('calendar-data'), kwargs)
        self.assertEqual(json_response.status_code, 200)
        self.assertEqual(json_response.json()['data']['count'], response.context['calendar']['count'])
        day = next(day for day in response.context['calendar']['days'] if day['date'] == date(2027, 6, 20))
        expanded = self.client.get(day['url'])
        self.assertEqual(expanded.status_code, 200)
        self.assertContains(expanded, 'diary-calendar-day-panel')
        token = response.context['calendar_return_token']
        with override_settings(ROOT_URLCONF=__name__):
            request = RequestFactory().get('/', {'calendar_return': token})
            request.user = self.user
            self.assertEqual(calendar_return_state(request)[1], reverse('calendar') + '?view=month&period=month&date=2027-06-20&mode=personal')
            request.user = self.other_user
            self.assertEqual(calendar_return_state(request), ('', ''))
        for params in ({'date': 'bad'}, {'view': 'year'}, {'view': ['week', 'month']}, {'mode': 'manager'}):
            self.assertEqual(self.client.get(reverse('calendar'), params).status_code, 400 if params.get('mode') != 'manager' else 403)

    def test_return_token_cannot_redirect_to_external_or_cross_user_location(self):
        request = RequestFactory().get('/')
        request.user = self.user
        for url in ('https://example.test/', '//example.test/', '/\\example.test/'):
            token = signing.dumps({'url': url, 'user': str(self.user.pk)}, salt=SALT)
            request.GET = request.GET.copy()
            request.GET['calendar_return'] = token
            self.assertEqual(calendar_return_state(request), ('', ''))
