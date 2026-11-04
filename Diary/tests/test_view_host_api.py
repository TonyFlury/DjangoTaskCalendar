"""Exercise host response hooks and form targeting without dispatch overrides."""
from dataclasses import FrozenInstanceError, asdict
from datetime import date
from unittest.mock import patch
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.test import TestCase, override_settings
from django.urls import include, path

from Diary.models import CalendarEntry, TemplateVersion
from Diary.tests.test_task_editing import TaskEditingFixtures
from Diary.view_api import DiarySuccessMixin, DiaryViewResult
from Diary.views import TaskCreateView, TaskDetailView


class HostPolicy:
    success_url = '/host/work/'

    def get_diary_keys(self):
        return settings.HOST_API_KEYS

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(settings.HOST_API_SELECTION)
        context['host_marker'] = 'Host context retained'
        return context


class HostCreate(HostPolicy, TaskCreateView):
    pass


class HostDetail(HostPolicy, TaskDetailView):
    pass


urlpatterns = [path('host/create/', HostCreate.as_view()), path('host/detail/', HostDetail.as_view()),
               path('diary/', include('Diary.urls'))]


@override_settings(ROOT_URLCONF=__name__, DIARY_MANAGER='Planners', DIARY_USER='Participants',
                   DIARY_TASK_OWNER_ROLES=('Helpers',))
class HostAPITests(TaskEditingFixtures, TestCase):
    def setUp(self):
        super().setUp()
        selection = override_settings(HOST_API_KEYS=(self.diary.key,),
                                      HOST_API_SELECTION={'diary_key': self.diary.key, 'entry_key': self.personal})
        selection.enable()
        self.addCleanup(selection.disable)

    def detail_payload(self, action='save_date', **changes):
        page = self.client.get('/host/detail/')
        self.assertEqual(page.status_code, 200)
        task = page.context['task']
        payload = {'action': action, 'revision': task['revision'], 'blocker_token': task['blocker_token'],
                   'diary_target': page.context['diary_target'], 'due_date': '2027-05-01'}
        payload.update(changes)
        return payload

    def test_fixed_detail_returns_immutable_identifiers_and_clean_url(self):
        payload = self.detail_payload()
        order = []
        def notify(view, *, result):
            self.assertEqual(CalendarEntry.objects.get(entry_key=self.personal).due_date, date(2027, 5, 1))
            self.assertIsInstance(result.diary_key, UUID)
            self.assertEqual(result, DiaryViewResult('task_date_updated', self.diary.key, self.personal))
            with self.assertRaises(FrozenInstanceError):
                result.operation = 'changed'
            order.append('notify')
        def destination(view, *, result):
            order.append('destination')
            return '/host/work/'
        with patch.object(HostDetail, 'on_success', notify), patch.object(HostDetail, 'get_success_url', destination):
            response = self.client.post('/host/detail/', payload)
        self.assertEqual(response['Location'], '/host/work/')
        self.assertEqual(order, ['notify', 'destination'])

    def test_invalid_date_keeps_context_target_and_input_without_callback(self):
        payload = self.detail_payload(due_date='not-a-date')
        with patch.object(HostDetail, 'on_success') as notify:
            response = self.client.post('/host/detail/', payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.context['host_marker'], 'Host context retained')
        self.assertEqual(response.context['due_form']['due_date'].value(), 'not-a-date')
        self.assertContains(response, 'action="/host/detail/"', status_code=400)
        self.assertTrue(response.context['diary_target'])
        notify.assert_not_called()

    def test_signed_target_rejects_tampering_missing_token_and_changed_selection(self):
        payload = self.detail_payload()
        for token in (None, payload['diary_target'] + 'tampered'):
            data = dict(payload)
            if token is None:
                data.pop('diary_target')
            else:
                data['diary_target'] = token
            self.assertEqual(self.client.post('/host/detail/', data).status_code, 400)
        with override_settings(HOST_API_SELECTION={'diary_key': self.diary.key, 'entry_key': self.first.entry_key}):
            self.assertEqual(self.client.post('/host/detail/', payload).status_code, 400)
        with override_settings(HOST_API_SELECTION={'diary_key': self.other_diary.key, 'entry_key': self.personal}):
            self.assertEqual(self.client.post('/host/detail/', payload).status_code, 400)
        self.assertEqual(CalendarEntry.objects.get(entry_key=self.personal).revision, 0)

    def test_signed_target_is_user_bound_and_scope_is_rechecked(self):
        payload = self.detail_payload()
        self.client.force_login(self.other)
        self.assertEqual(self.client.post('/host/detail/', payload).status_code, 400)
        self.client.force_login(self.user)
        with override_settings(HOST_API_KEYS=()):
            self.assertEqual(self.client.post('/host/detail/', payload).status_code, 403)
        self.assertEqual(CalendarEntry.objects.get(entry_key=self.personal).revision, 0)

    def test_hook_exception_is_not_presented_as_failed_diary_validation(self):
        payload = self.detail_payload()
        with patch.object(HostDetail, 'on_success', side_effect=ValidationError('Host hook failed')):
            with self.assertRaisesMessage(ValidationError, 'Host hook failed'):
                self.client.post('/host/detail/', payload)
        self.assertEqual(CalendarEntry.objects.get(entry_key=self.personal).due_date, date(2027, 5, 1))

    def test_custom_success_response_can_return_json(self):
        payload = self.detail_payload(action='complete')
        def respond(view, *, result):
            view.on_success(result=result)
            return JsonResponse(asdict(result))
        with patch.object(HostDetail, 'success_response', respond), patch.object(HostDetail, 'on_success') as notify:
            response = self.client.post('/host/detail/', payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['operation'], 'task_completed')
        self.assertEqual(response.json()['entry_key'], str(self.personal))
        notify.assert_called_once()

    def test_creation_uses_same_contract_and_does_not_change_host_session_selection(self):
        page = self.client.get('/host/create/')
        payload = self.payload(diary_target=page.context['diary_target'])
        with patch.object(HostCreate, 'on_success') as notify:
            response = self.client.post('/host/create/', payload)
        self.assertEqual(response['Location'], '/host/work/')
        result = notify.call_args.kwargs['result']
        self.assertEqual(result, DiaryViewResult('task_created', self.diary.key, UUID(payload['entry_key'])))
        self.assertEqual(dict(self.client.session).keys(), {'_auth_user_id', '_auth_user_backend', '_auth_user_hash'})

    def test_combined_creation_reports_the_saved_template_version(self):
        self.client.force_login(self.manager)
        page = self.client.get('/host/create/')
        with patch.object(HostCreate, 'on_success') as notify:
            response = self.client.post('/host/create/', self.combined_payload(diary_target=page.context['diary_target']))
        self.assertEqual(response.status_code, 302)
        result = notify.call_args.kwargs['result']
        self.assertEqual(result.template_name, 'Creation template')
        self.assertNotEqual(result.template_version_key, self.version.key)
        self.assertTrue(TemplateVersion.objects.filter(pk=result.template_version_key, number=2).exists())

    def test_default_success_destinations_have_no_query_parameters(self):
        view = DiarySuccessMixin()
        for operation in ('task_created', 'task_completed', 'task_chain_completed', 'task_date_updated',
                          'task_owner_updated', 'template_created', 'template_saved', 'template_applied'):
            result = DiaryViewResult(operation, self.diary.key, self.personal, 'Creation template', self.version.key)
            self.assertNotIn('?', view.get_success_url(result=result))
