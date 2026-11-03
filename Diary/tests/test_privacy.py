"""DV1-031: Verify personal-task privacy across callable, HTTP data, and HTML interfaces."""
import json
from dataclasses import replace
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseForbidden
from django.test import TestCase, override_settings
from django.urls import include, path, reverse

from Diary.api import DiaryAPI
from Diary.models import CalendarEntry, EventCalendar
from Diary.tests.legacy_dependencies import seed_legacy_dependencies
from Diary.tests.test_personal_view import PersonalDiaryFixtures
from Diary.views import DiaryDataView, TaskDetailView


class TrustedPrivacyScope:
    """Supply permitted diary keys from the test host's current access policy."""

    def get_diary_keys(self):
        """Return trusted keys without accepting client-supplied permissions."""
        return settings.PRIVACY_TEST_KEYS


class HostDiaryDataView(TrustedPrivacyScope, DiaryDataView):
    """Expose JSON reads with the test host's trusted diary scope."""


class HostPrivacyTaskView(TrustedPrivacyScope, TaskDetailView):
    """Expose HTML task details with the same trusted diary scope."""


def handler403(request, exception):
    """Return a denial without importing host navigation or task content."""
    return HttpResponseForbidden('Access denied.')


urlpatterns = [
    path('data/diary/', HostDiaryDataView.as_view(), name='privacy-diary'),
    path('data/active/', HostDiaryDataView.as_view(resource='active'), name='privacy-active'),
    path('data/personal/', HostDiaryDataView.as_view(resource='personal'), name='privacy-personal'),
    path('data/search/', HostDiaryDataView.as_view(resource='search'), name='privacy-search'),
    path('data/tasks/<uuid:entry_key>/', HostDiaryDataView.as_view(resource='task'), name='privacy-task'),
    path('data/tasks/<uuid:entry_key>/predecessors/',
         HostDiaryDataView.as_view(resource='predecessors'), name='privacy-predecessors'),
    path('tasks/<uuid:entry_key>/', HostPrivacyTaskView.as_view(), name='privacy-html'),
    path('diary/', include('Diary.urls')),
]


@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants',
                   DIARY_TASK_OWNER_ROLES=('Helpers', 'Reviewers'), ROOT_URLCONF=__name__)
class PersonalEntryPrivacyTests(PersonalDiaryFixtures, TestCase):
    """Keep another person's diary additions outside every supported read interface."""

    def setUp(self):
        """Prepare private content, historical private dependencies, and trusted HTTP scope."""
        super().setUp()
        self.secret = 'Confidential description marker'
        CalendarEntry.objects.filter(calendar_id=self.keys[0], entry_key=self.private).update(description=self.secret)
        seed_legacy_dependencies(self.keys[0], ((self.blocked, (self.private,)),))
        scope = override_settings(PRIVACY_TEST_KEYS=tuple(self.keys[:3]))
        scope.enable()
        self.addCleanup(scope.disable)
        self.api = DiaryAPI(actor=self.user_actor)
        self.diary = self.api.diary(key=self.keys[0])

    def url(self, resource, entry_key=None):
        """Return one test-host route with an optional task identifier."""
        kwargs = {}

        # Only task-specific routes need a task identifier.
        if entry_key is not None:
            kwargs['entry_key'] = entry_key
        return reverse('privacy-' + resource, kwargs=kwargs)

    def read_data(self, resource, entry_key=None, **params):
        """Read one JSON resource with the selected permitted diary as the default."""
        values = {'diary_key': str(self.keys[0]), **params}
        return self.client.get(self.url(resource, entry_key), values)

    def assert_private_absent(self, data):
        """Check names, descriptions, and identifiers across the complete serialized result."""
        text = json.dumps(data, default=str)
        for value in ('<Private blocker>', self.secret, str(self.private)):
            self.assertNotIn(value, text)

    def test_callable_search_filters_before_matching_names_and_descriptions(self):
        """Return empty results for private text while matching visible names and descriptions."""
        for query in ('private blocker', self.secret, '  CONFIDENTIAL  '):
            self.assertEqual(self.diary.search_tasks(query=query), ())
            self.assertEqual(self.api.search_tasks(query=query), ())
        CalendarEntry.objects.filter(calendar_id=self.keys[0], entry_key=self.ready).update(description='Visible matching description')
        self.assertEqual([item['entry_key'] for item in self.diary.search_tasks(query='MATCHING')], [self.ready])
        self.assertEqual([item['entry_key'] for item in self.api.search_tasks(query='my READY')], [self.ready])
        self.assertEqual(len(self.api.search_tasks(query='Other owner predecessor')), 3)
        self.assert_private_absent(self.api.search_tasks())

    def test_search_retains_scope_history_and_explicit_selector_errors(self):
        """Include visible completion history and closed diaries without expanding the host scope."""
        results = self.api.search_tasks()
        self.assertIn(self.done, {item['entry_key'] for item in results})
        self.assertEqual({item['diary_key'] for item in results}, set(self.keys[:3]))
        with self.assertRaises(PermissionDenied):
            self.api.search_tasks(diary_key=self.keys[3])
        missing = uuid4()
        missing_api = DiaryAPI(actor=replace(self.user_actor, calendar_keys=frozenset({missing})))
        with self.assertRaises(EventCalendar.DoesNotExist):
            missing_api.search_tasks(diary_key=missing)
        self.assertEqual(DiaryAPI(actor=replace(self.user_actor, calendar_keys=frozenset())).search_tasks(), ())
        for query in (None, 7, 'x' * 257):
            with self.assertRaises(ValidationError):
                self.api.search_tasks(query=query)
            with self.assertRaises(ValidationError):
                self.diary.search_tasks(query=query)

    def test_http_lists_search_and_predecessors_remove_all_private_content(self):
        """Apply visibility to every JSON collection, including related task references."""
        for resource, key in (('diary', None), ('active', None), ('personal', None),
                              ('search', None), ('predecessors', self.ready)):
            response = self.read_data(resource, key)
            self.assertEqual(response.status_code, 200)
            self.assert_private_absent(response.json())
            self.assertIn('private', response.headers['Cache-Control'])
            self.assertIn('no-store', response.headers['Cache-Control'])
            self.assertIn('Cookie', response.headers['Vary'])
        for query in ('private blocker', self.secret):
            self.assertEqual(self.read_data('search', q=query).json(), {'data': []})
        self.assertEqual(self.read_data('search', q='x' * 257).status_code, 400)

    def test_private_and_unknown_keys_have_identical_json_and_html_errors(self):
        """Prevent guessed task identifiers from confirming a private task's existence."""
        for resource in ('task', 'predecessors', 'html'):
            hidden = self.read_data(resource, self.private)
            unknown = self.read_data(resource, uuid4())
            self.assertEqual(hidden.status_code, 404)
            self.assertEqual(unknown.status_code, 404)
            self.assertEqual(hidden.content, unknown.content)
            self.assertNotIn(self.secret.encode(), hidden.content)

    def test_private_blockers_preserve_state_without_names_counts_or_keys(self):
        """Keep private blocking effective while returning only the generic detail marker."""
        task = self.diary.task(entry_key=self.blocked)
        self.assertFalse(task['ready'])
        self.assertEqual(task['blockers'], ({'private': True},))
        self.assertEqual(task['predecessors'], ())
        self.assert_private_absent(task)
        response = self.read_data('task', self.blocked)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['blockers'], [{'private': True}])
        self.assert_private_absent(response.json())

        # The selected visible task must remain blocked even when its private predecessor is omitted.
        self.assertFalse(next(item for item in self.read_data('active').json()['data']
                              if item['entry_key'] == str(self.blocked))['ready'])

    def test_completion_history_masks_private_targets_in_reads_and_search(self):
        """Keep forced-completion comments from disclosing a private target's name or identifier."""
        seed_legacy_dependencies(self.keys[0], ((self.blocked, ()), (self.private, (self.ready,))))
        detail = self.first.task(entry_key=self.private)
        self.first.complete(entry_key=self.private, expected_revision=detail['revision'], close_all=True,
                                 expected_blockers=detail['blocker_token'])
        for data in (self.diary.read(), self.diary.search_tasks(), self.api.search_tasks(),
                     self.diary.task(entry_key=self.ready), self.read_data('diary').json(),
                     self.read_data('search').json(), self.read_data('task', self.ready).json()):
            self.assert_private_absent(data)
        task = self.diary.task(entry_key=self.ready)
        self.assertIsNone(task['completion_target_key'])
        self.assertEqual(task['completion_comment'], 'Close all completed this predecessor for an inaccessible task.')
        manager_task = self.first.task(entry_key=self.ready)
        self.assertIn('<Private blocker>', manager_task['completion_comment'])

    def test_owner_and_scoped_manager_can_read_private_tasks(self):
        """Allow the current owner and permitted managers without granting access to other diaries."""
        for person in (self.other_user, self.manager):
            self.client.force_login(person)
            response = self.read_data('task', self.private)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['data']['description'], self.secret)
            self.assertEqual(len(self.read_data('search', q=self.secret).json()['data']), 1)
            self.assertEqual(self.read_data('diary', diary_key=str(self.keys[3])).status_code, 403)
        self.assertEqual(self.client.get(reverse('Diary:data-diary'), {'diary_key': str(self.keys[0])}).status_code, 403)

    def test_role_and_scope_changes_apply_on_the_next_http_request(self):
        """Avoid cached manager permission or diary scope after membership or host-policy changes."""
        self.client.force_login(self.manager)
        self.assertEqual(self.read_data('task', self.private).status_code, 200)
        self.manager.groups.remove(self.manager_group)
        self.manager.groups.add(self.user_group)
        self.assertEqual(self.read_data('task', self.private).status_code, 404)
        with override_settings(PRIVACY_TEST_KEYS=()):
            self.assertEqual(self.read_data('task', self.ready).status_code, 403)
            self.assertEqual(self.client.get(self.url('search')).json(), {'data': []})
        self.manager.groups.clear()
        self.assertEqual(self.read_data('search').status_code, 403)

    def test_selectors_authentication_and_http_methods_cannot_expand_access(self):
        """Reject malformed selectors, unsupported writes, and forged identity inputs without mutation."""
        before = list(CalendarEntry.objects.order_by('pk').values())
        for resource in ('diary', 'active', 'task', 'predecessors'):

            # Task-specific routes need a task key but must still reject an absent diary selector.
            key = self.ready if resource in ('task', 'predecessors') else None
            self.assertEqual(self.client.get(self.url(resource, key)).status_code, 400)
        for value in ('', 'invalid'):
            self.assertEqual(self.read_data('search', diary_key=value).status_code, 400)
        self.assertEqual(self.client.get(self.url('search'),
            {'diary_key': [str(self.keys[0]), str(self.keys[1])]}).status_code, 400)
        self.assertEqual(self.read_data('search', diary_key=str(self.keys[3])).status_code, 403)
        with override_settings(PRIVACY_TEST_KEYS=(uuid4(),)):
            missing = settings.PRIVACY_TEST_KEYS[0]
            self.assertEqual(self.read_data('diary', diary_key=str(missing)).status_code, 404)
        self.assert_private_absent(self.read_data('search', groups='Planners',
            person_ref=f'user:{self.other_user.pk}', permitted_diary_keys=str(self.keys[3])).json())
        for method in ('post', 'put', 'patch', 'delete'):
            self.assertEqual(getattr(self.client, method)(self.url('search')).status_code, 405)
        head = self.client.head(self.url('search'))
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b'')
        self.assertEqual(list(CalendarEntry.objects.order_by('pk').values()), before)
        self.client.logout()
        self.assertEqual(self.read_data('search').status_code, 302)
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        self.client.force_login(self.user)
        self.assertEqual(self.read_data('search').status_code, 302)

    def test_template_editor_never_includes_private_diary_additions(self):
        """Keep the manager template editor limited to reusable template records."""
        url = reverse('Diary:template-edit', kwargs={'template_name': 'Personal template'})
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.manager)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.secret)
        self.assertNotContains(response, str(self.private))
        self.assertContains(response, 'Other owner predecessor')
