"""Live manager graph preserves host scope, status semantics and existing navigation."""
from datetime import date
from unittest.mock import patch
from dataclasses import replace

from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings
from django.urls import reverse

from Diary.api import DiaryAPI, EntrySpec
from Diary.choices import DateKind
from Diary.models import CalendarEntry
from Diary.presentation import SESSION_KEY
from Diary.tests.test_personal_view import PersonalDiaryFixtures
from Diary.views import DjangoOwnerDirectory


@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers', 'Reviewers'),
                   ROOT_URLCONF='Diary.tests.test_diary_presentations')
class DiaryGraphTests(PersonalDiaryFixtures, TestCase):
    def setUp(self):
        super().setUp()
        scope = override_settings(PRESENTATION_DIARY_KEY=self.keys[0], MANAGER_TEST_KEYS=tuple(self.keys[:3]))
        scope.enable()
        self.addCleanup(scope.disable)
        self.client.force_login(self.manager)

    def graph(self, **kwargs):
        return self.first.graph(directory=DjangoOwnerDirectory(), **kwargs)

    def test_status_precedence_and_full_graph_before_filters(self):
        graph = self.graph(include_completed=True)
        tasks = {node['entry_key']: node for node in graph['nodes'] if node['kind'] == 'task'}
        self.assertEqual(tasks[self.done]['state'], 'completed')
        self.assertFalse(tasks[self.done]['late'])
        self.assertEqual(tasks[self.ready]['state'], 'ready')
        self.assertEqual(tasks[self.blocked]['state'], 'blocked-late')
        self.assertEqual(tasks[self.blocked_late]['state'], 'late')
        self.assertTrue(tasks[self.blocked_late]['blocked'])
        self.assertIn('Due today', tasks[self.blocked_late]['status_label'])
        self.assertTrue(tasks[self.undated]['undated'])
        filtered = self.graph(exclude_non_late=True)
        self.assertNotIn(self.blocked, [node.get('entry_key') for node in filtered['nodes']])
        self.assertNotIn(self.done, [node.get('entry_key') for node in filtered['nodes']])
        self.assertEqual({node['entry_key'] for node in self.graph(exclude_blocked=True)['nodes'] if node['kind'] == 'task'},
                         {key for key, node in tasks.items() if not node['blocked'] and not node['completed']})

    def test_hidden_completed_predecessor_does_not_leak_or_block(self):
        CalendarEntry.objects.filter(calendar_id=self.keys[0], entry_key=self.blocker_spec.entry_key).update(completed_at='2027-06-11T12:00:00Z', completed_by_ref=self.user_ref, completed_due_date=date(2027, 6, 10))
        graph = self.graph()
        task = next(node for node in graph['nodes'] if node.get('entry_key') == self.blocked)
        self.assertEqual(task['state'], 'ready')
        self.assertTrue(task['context_outside_view'])
        encoded = str(graph)
        self.assertNotIn(str(self.blocker_spec.entry_key), encoded)
        self.assertNotIn('Other owner predecessor', encoded)
        visible = {node['key'] for node in graph['nodes']}
        self.assertTrue(all(edge['source'] in visible and edge['target'] in visible for edge in graph['edges']))

    def test_milestones_scoped_identities_and_fixed_snapshots(self):
        child = self.first.add_entry(spec=EntrySpec('Snapshot child', DateKind.TASK, source_task_key=self.ready, day_offset=2))
        initial = next(node for node in self.graph()['nodes'] if node.get('entry_key') == child)
        CalendarEntry.objects.filter(calendar_id=self.keys[0], entry_key=self.ready).update(due_date_override=date(2027, 7, 1))
        graph = self.graph()
        current = next(node for node in graph['nodes'] if node.get('entry_key') == child)
        self.assertEqual(initial['date'], current['date'])
        self.assertEqual(current['date'], date(2027, 6, 22))
        self.assertTrue(any(node['kind'] == 'milestone' and node['date'] == date(2027, 6, 20) for node in graph['nodes']))
        second = DiaryAPI(actor=self.manager_actor).diary(key=self.keys[1]).graph(directory=DjangoOwnerDirectory())
        self.assertTrue(set(node['key'] for node in graph['nodes']).isdisjoint(node['key'] for node in second['nodes']))
        self.assertTrue(any('snapshot stays fixed' in edge['description'] for edge in graph['edges']))

    def test_access_is_manager_only_and_scope_is_rechecked(self):
        with self.assertRaises(PermissionDenied):
            DiaryAPI(actor=self.user_actor).diary(key=self.keys[0]).graph(directory=DjangoOwnerDirectory())
        actor = replace(self.manager_actor, calendar_keys=frozenset({self.keys[1]}))
        with self.assertRaises(PermissionDenied):
            DiaryAPI(actor=actor).diary(key=self.keys[0]).graph()
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('query-free-manager'), {'view': 'graph'}).status_code, 403)
        self.assertEqual(self.client.get(reverse('query-free-personal'), {'view': 'graph'}).status_code, 400)

    def test_existing_host_endpoint_wrapper_filters_preference_and_post_navigation(self):
        response = self.client.get(reverse('query-free-manager'), {'view':'graph', 'include_completed':'1', 'date':'1900-01-01'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'Diary/manager_graph.html')
        self.assertTrue(any(node.get('entry_key') == self.done for node in response.context['graph_data']['nodes']))
        self.assertEqual(self.client.session[SESSION_KEY]['manager'], 'graph')
        self.assertNotContains(response, 'name="diary_key"')
        self.assertNotIn('diary_key=', response.context['graph_refresh_url'])
        saved = self.client.get(reverse('query-free-manager'))
        self.assertTemplateUsed(saved, 'Diary/manager_graph.html')
        token = response.context['calendar_return_token']
        selected = self.client.post(reverse('query-free-select'), {'entry_key':str(self.ready), 'host_event_id':'current-event', 'calendar_return':token}, follow=True)
        self.assertContains(selected, 'My ready task')
        self.assertEqual(self.client.session['host_task_key'], str(self.ready))
        self.assertEqual(selected.context['calendar_return_url'], '/fixed/manager/?view=graph&include_completed=1')

    def test_orphan_warning_archived_reads_and_no_events(self):
        self.other_user.is_active = False
        self.other_user.save(update_fields=['is_active'])
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            graph = self.graph()
            self.first.close()
            archived = self.graph()
        self.assertEqual(callbacks, [])
        orphan = next(node for node in graph['nodes'] if node.get('entry_key') == self.blocker_spec.entry_key)
        self.assertTrue(orphan['orphaned'])
        self.assertEqual(orphan['state'], 'late')
        self.assertTrue(archived['diary']['closed'])
        response = self.client.get(reverse('query-free-manager'), {'view':'graph'})
        self.assertContains(response, 'Archived diary')
        self.assertNotContains(response, 'aria-label="Add task"')

    def test_projection_batches_reads_and_keeps_duplicate_relationship_meaning(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from Diary.tests.legacy_dependencies import seed_legacy_dependencies
        child = self.first.add_entry(spec=EntrySpec('Both relationships', DateKind.TASK, source_task_key=self.ready, day_offset=0))
        seed_legacy_dependencies(self.keys[0], ((child, (self.ready,)),))
        with CaptureQueriesContext(connection) as first:
            graph = self.graph()
        target = next(node['key'] for node in graph['nodes'] if node.get('entry_key') == child)
        self.assertEqual({edge['kind'] for edge in graph['edges'] if edge['target'] == target}, {'dependency', 'date'})
        for index in range(8):
            self.add_task(f'Extra disconnected task {index}', date(2027, 7, 1))
        with CaptureQueriesContext(connection) as second:
            self.graph()
        self.assertEqual(len(first), len(second))

    def test_matching_list_filters_and_html_escaping(self):
        self.add_task('</script><script>alert("graph")</script>', date(2027, 6, 20))
        for flags in ({}, {'include_completed':'1'}, {'exclude_blocked':'1'}, {'exclude_non_late':'1'}):
            graph = self.client.get(reverse('query-free-manager'), {'view':'graph', **flags})
            listed = self.client.get(reverse('query-free-manager'), {'view':'list', **flags})
            self.assertEqual({node['entry_key'] for node in graph.context['graph_data']['nodes'] if node['kind'] == 'task'},
                             {node['entry_key'] for node in listed.context['tasks']})
            self.assertNotContains(graph, '<script>alert("graph")</script>')

    def test_completion_refreshes_successors_and_keeps_completion_snapshot(self):
        from Diary.tests.legacy_dependencies import seed_legacy_dependencies
        seed_legacy_dependencies(self.keys[0], ((self.blocked, (self.ready,)),))
        before = {node.get('entry_key'): node for node in self.graph()['nodes'] if node['kind'] == 'task'}
        self.assertEqual(before[self.blocked]['state'], 'blocked')
        self.first.complete(entry_key=self.ready, expected_revision=before[self.ready]['revision'])
        after = {node.get('entry_key'): node for node in self.graph(include_completed=True)['nodes'] if node['kind'] == 'task'}
        self.assertEqual(after[self.blocked]['state'], 'ready')
        self.assertEqual(after[self.ready]['state'], 'completed')
        CalendarEntry.objects.filter(calendar_id=self.keys[0], entry_key=self.ready).update(due_date_override=date(2027, 8, 1))
        saved = next(node for node in self.graph(include_completed=True)['nodes'] if node.get('entry_key') == self.ready)
        self.assertEqual(saved['date'], date(2027, 6, 20))

    def test_existing_host_detail_query_values_are_preserved(self):
        from urllib.parse import parse_qs, urlsplit
        from Diary.views import ManagerDiaryView
        with patch.object(ManagerDiaryView, 'task_url', return_value='/fixed/task/?host=a&host=b&blank='):
            response = self.client.get(reverse('query-free-manager'), {'view':'graph'})
        node = next(node for node in response.context['graph_data']['nodes'] if node['kind'] == 'task')
        query = parse_qs(urlsplit(node['detail_url']).query, keep_blank_values=True)
        self.assertEqual(query['host'], ['a', 'b'])
        self.assertEqual(query['blank'], [''])
        self.assertNotIn('diary_key', query)
        self.assertTrue(query['calendar_return'])
