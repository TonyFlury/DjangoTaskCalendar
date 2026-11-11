"""One host URL per diary role; the package owns presentation, filters and preferences."""
from datetime import date
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.core.exceptions import BadRequest
from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import redirect
from django.test import TestCase, override_settings
from django.urls import include, path, reverse
from django.views import View

from Diary.api import DiaryAPI
from Diary.calendar_navigation import carry_calendar_return
from Diary.presentation import SESSION_KEY
from Diary.tests.test_personal_view import PersonalDiaryFixtures, HostPersonalDiaryView
from Diary.tests.test_manager_view import HostManagerDiaryView
from Diary.views import DiaryScopeMixin, ManagerDiaryView, PersonalDiaryView, TaskDetailView


class QueryFreeContext:
    """Mirror a host that keeps current diary/task selection out of browser URLs."""

    uses_task = False

    def get_context_data(self, **kwargs):
        if {'diary_key', 'entry_key', 'event_id', 'template_name'}.intersection(self.request.GET):
            raise BadRequest('Identifiers are not accepted in URLs.')
        context = super().get_context_data(**kwargs)
        key = settings.PRESENTATION_DIARY_KEY
        context.update(diary_key=key, permitted_diary_keys=(key,), diary_base_template='Diary/base.html',
            diary_ui={'trusted_scope': True, 'selection_url': reverse('query-free-select'),
                      'task_detail_url': reverse('query-free-task'), 'form_fields': {'host_event_id': 'current-event'}})
        if self.uses_task and self.request.method == 'GET':
            context['entry_key'] = self.request.session.get('host_task_key')
        return context


class QueryFreePersonalView(QueryFreeContext, PersonalDiaryView):
    pass


class QueryFreeManagerView(QueryFreeContext, ManagerDiaryView):
    pass


class QueryFreeTaskView(QueryFreeContext, TaskDetailView):
    uses_task = True

    def get_success_url(self, *, result):
        """An existing host success hook knows nothing about calendar presentations."""
        return reverse('query-free-task')


class QueryFreeSelectionView(QueryFreeContext, DiaryScopeMixin, View):
    access_roles = ('manager', 'user')
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        if request.POST.get('host_event_id') != 'current-event':
            raise BadRequest('The current event changed.')
        key = request.POST['entry_key']
        DiaryAPI(actor=self.actor).diary(key=self.selected_key()).task(entry_key=key)
        request.session['host_task_key'] = key
        return redirect('query-free-task')


def handler403(request, exception):
    return HttpResponseForbidden('Access denied.')


urlpatterns = [
    path('personal/', HostPersonalDiaryView.as_view(), name='personal'),
    path('manager/', HostManagerDiaryView.as_view(), name='manager'),
    path('fixed/personal/', QueryFreePersonalView.as_view(), name='query-free-personal'),
    path('fixed/manager/', QueryFreeManagerView.as_view(), name='query-free-manager'),
    path('fixed/task/', QueryFreeTaskView.as_view(), name='query-free-task'),
    path('fixed/select/', QueryFreeSelectionView.as_view(), name='query-free-select'),
    path('diary/', include('Diary.urls')),
]


@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers', 'Reviewers'),
                   ROOT_URLCONF=__name__)
class DiaryPresentationTests(PersonalDiaryFixtures, TestCase):
    def setUp(self):
        super().setUp()
        scope = override_settings(MANAGER_TEST_KEYS=tuple(self.keys[:3]), PRESENTATION_DIARY_KEY=self.keys[0])
        scope.enable()
        self.addCleanup(scope.disable)

    def test_existing_personal_endpoint_selects_and_remembers_presentations(self):
        url = reverse('personal')
        initial = self.client.get(url)
        self.assertTemplateUsed(initial, 'Diary/personal_diary.html')
        for view in ('day', 'week', 'month'):
            page = self.client.get(url, {'view': view, 'date': '2027-06-20'})
            self.assertEqual(page.status_code, 200)
            self.assertTemplateUsed(page, f'Diary/partials/calendar_{view}.html')
            self.assertEqual(page.context['calendar']['view'], view)
            self.assertEqual(self.client.session[SESSION_KEY]['personal'], view)
        recalled = self.client.get(url, {'date': '2027-06-20'})
        self.assertEqual(recalled.context['calendar']['view'], 'month')
        explicit = self.client.get(url, {'view': 'list'})
        self.assertTemplateUsed(explicit, 'Diary/personal_diary.html')
        self.assertEqual(self.client.session[SESSION_KEY]['personal'], 'list')

    def test_user_and_role_preferences_are_isolated_and_do_not_grant_access(self):
        self.client.get(reverse('personal'), {'view': 'month', 'date': '2027-06-20'})
        self.client.force_login(self.other_user)
        self.assertTemplateUsed(self.client.get(reverse('personal')), 'Diary/personal_diary.html')
        self.client.force_login(self.manager)
        self.client.get(reverse('personal'), {'view': 'week', 'date': '2027-06-20'})
        manager = self.client.get(reverse('manager'), {'diary_key': self.keys[0]})
        self.assertTemplateUsed(manager, 'Diary/manager_diary.html')
        monthly = self.client.get(reverse('manager'), {'diary_key': self.keys[0], 'view': 'month', 'date': '2027-06-20'})
        self.assertEqual(monthly.status_code, 200)
        self.assertEqual(self.client.session[SESSION_KEY]['personal'], 'week')
        self.assertEqual(self.client.session[SESSION_KEY]['manager'], 'month')
        with override_settings(MANAGER_TEST_KEYS=()):
            self.assertEqual(self.client.get(reverse('manager'), {'diary_key': self.keys[0]}).status_code, 403)

    def test_personal_filters_are_identical_across_all_presentations(self):
        url = reverse('personal')
        params = {'date': '2027-06-20', 'task_status': 'all', 'include_whole_team': '1'}
        listed = self.client.get(url, {**params, 'view': 'list'})
        expected = {(task['diary_key'], task['entry_key']) for group in listed.context['task_groups']
                    for task in group['tasks'] if task['date'] == date(2027, 6, 20)}
        for view in ('day', 'week', 'month'):
            page = self.client.get(url, {**params, 'view': view})
            self.assertEqual(page.status_code, 200)
            self.assertEqual(set(field.name for field in page.context['calendar_filters']),
                             set(listed.context['filters'].fields))
            rows = page.context['calendar']['day']['tasks']
            self.assertEqual({(row['diary_key'], row['entry_key']) for row in rows}, expected)
        for category in ('late', 'ready', 'blocked'):
            params = {'view': 'month', 'date': '2027-06-20', 'task_status': category}
            page = self.client.get(url, params)
            self.assertTrue(all(('late' if row['late'] else row['state']) == category
                for day in page.context['calendar']['days'] for row in day['tasks']))

    def test_manager_filters_are_identical_across_presentations(self):
        self.client.force_login(self.manager)
        params = {'diary_key': str(self.keys[0]), 'date': '2027-06-12', 'include_completed': '1',
                  'exclude_blocked': '1', 'exclude_non_late': '1'}
        listed = self.client.get(reverse('manager'), {**params, 'view': 'list'})
        expected = {row['entry_key'] for row in listed.context['tasks']}
        month = self.client.get(reverse('manager'), {**params, 'view': 'month'})
        self.assertEqual(month.status_code, 200)
        self.assertEqual({row['entry_key'] for day in month.context['calendar']['days'] for row in day['tasks']}, expected)
        self.assertEqual(set(field.name for field in month.context['calendar_filters']), set(listed.context['filters'].fields))

    def test_query_free_host_uses_existing_post_selection_and_preserves_calendar_return(self):
        response = self.client.get(reverse('query-free-personal'),
                                   {'view': 'month', 'date': '2027-06-20', 'show_blocked': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'form="diary-select-task"')
        self.assertNotContains(response, 'name="diary_key"')
        self.assertNotContains(response, 'diary_key=')
        for tab in response.context['calendar_tabs']:
            self.assertEqual(urlsplit(tab['url']).path, reverse('query-free-personal'))
        token = response.context['calendar_return_token']
        selected = self.client.post(reverse('query-free-select'), {'selection': 'task', 'entry_key': str(self.ready),
            'host_event_id': 'current-event', 'calendar_return': token})
        self.assertEqual(selected.status_code, 302)
        self.assertNotIn('diary_key', selected['Location'])
        self.assertIn('calendar_return=', selected['Location'])
        details = self.client.get(selected['Location'])
        self.assertEqual(details.status_code, 200)
        self.assertEqual(details.context['calendar_return_token'], token)
        saved = self.client.post(reverse('query-free-task'), {'action': 'add_note', 'text': 'Same host URL',
            'note_key': '860c74ce-dd1a-4208-b9dd-555a25ce2a71', 'calendar_return': token,
            'diary_target': details.context['diary_target']})
        self.assertEqual(saved.status_code, 302)
        self.assertIn('calendar_return=', saved['Location'])
        details = self.client.get(saved['Location'])
        returned = self.client.get(details.context['calendar_return_url'])
        self.assertEqual(returned.status_code, 200)
        self.assertEqual(returned.context['calendar']['view'], 'month')
        self.assertTrue(returned.context['calendar_form'].is_valid())
        self.assertEqual(self.client.get(reverse('query-free-personal'), {'diary_key': self.keys[0]}).status_code, 400)

    def test_invalid_view_does_not_replace_preference_and_scope_is_rechecked(self):
        url = reverse('personal')
        self.client.get(url, {'view': 'week', 'date': '2027-06-20'})
        for value in ('year', ['month', 'day']):
            self.assertEqual(self.client.get(url, {'view': value}).status_code, 400)
        self.assertEqual(self.client.session[SESSION_KEY]['personal'], 'week')
        self.assertEqual(self.client.get(url, {'diary_key': self.keys[3]}).status_code, 403)

    def test_return_handoff_preserves_host_query_values(self):
        page = self.client.get(reverse('query-free-personal'), {'view': 'month', 'date': '2027-06-20'})
        token = page.context['calendar_return_token']
        from django.test import RequestFactory
        request = RequestFactory().post('/fixed/select/', {'calendar_return': token})
        request.user = self.user
        response = carry_calendar_return(request, HttpResponseRedirect('/fixed/task/?filter=a&filter=b&empty='))
        query = parse_qs(urlsplit(response['Location']).query, keep_blank_values=True)
        self.assertEqual(query['filter'], ['a', 'b'])
        self.assertEqual(query['empty'], [''])
        self.assertEqual(query['calendar_return'], [token])
