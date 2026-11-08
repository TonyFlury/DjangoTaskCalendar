"""Task selectors follow visible subgraphs rather than task-name sorting."""
from datetime import date

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from Diary.api import DiaryAPI, EntrySpec
from Diary.choices import DateKind
from Diary.template_graph import ordered_task_choices
from Diary.tests.test_task_creation import TaskCreationFixtures


class TaskChoiceOrderTests(SimpleTestCase):
    def test_groups_connected_tasks_source_first_with_stable_ties(self):
        entries = [dict(entry_key='end', predecessors=['middle']), dict(entry_key='unrelated'),
                   dict(entry_key='middle', predecessors=['root']), dict(entry_key='root')]
        self.assertEqual([entry['entry_key'] for entry in ordered_task_choices(entries)],
                         ['root', 'middle', 'end', 'unrelated'])
        # With no date references, the date picker follows the completion subgraphs too.
        self.assertEqual(ordered_task_choices(entries, date_sources=True), ordered_task_choices(entries))

    def test_date_and_completion_orders_remain_independent(self):
        entries = [dict(entry_key='a', predecessors=['b']), dict(entry_key='b', source_task_key='a')]
        self.assertEqual([entry['entry_key'] for entry in ordered_task_choices(entries)], ['b', 'a'])
        self.assertEqual([entry['entry_key'] for entry in ordered_task_choices(entries, date_sources=True)], ['a', 'b'])

    def test_invalid_unsaved_references_do_not_drop_choices_or_loop(self):
        entries = [dict(entry_key='a', predecessors=['b', 'missing']),
                   dict(entry_key='b', predecessors=['a']), dict(entry_key='unrelated')]
        self.assertCountEqual(ordered_task_choices(entries), entries)
        self.assertEqual(ordered_task_choices([entries[0], entries[0]]), (entries[0], entries[0]))


@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',),
                   ROOT_URLCONF='Diary.tests.test_task_creation')
class TaskSelectorOrderTests(TaskCreationFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.root = EntrySpec('Z source', DateKind.SOURCE, milestone_name='target')
        self.middle = EntrySpec('Y middle', DateKind.TASK, source_task_key=self.root.entry_key)
        self.end = EntrySpec('A end', DateKind.TASK, source_task_key=self.middle.entry_key)
        self.unrelated = EntrySpec('B unrelated', DateKind.ANNUAL, month=6, day=1)
        self.target = EntrySpec('C target', DateKind.ANNUAL, month=6, day=1)
        self.version = self.template.save_version(entries=[self.end, self.unrelated, self.target, self.middle, self.root],
            predecessors={self.middle.entry_key: [self.root.entry_key], self.end.entry_key: [self.middle.entry_key]},
            expected_version_key=self.version.key)
        self.client.force_login(self.manager)

    def test_api_and_server_template_choices_follow_subgraphs(self):
        expected = ['Z source', 'Y middle', 'A end', 'B unrelated']
        self.assertEqual([entry['name'] for entry in self.version.available_predecessors(entry_key=self.target.entry_key)], expected)
        response = self.client.get(reverse('Diary:template-edit', kwargs={'template_name': 'Creation template'}))
        self.assertEqual(response.status_code, 200)
        form = next(form for form in response.context['task_forms'].forms
                    if str(form['entry_key'].value()) == str(self.target.entry_key))
        self.assertEqual([name for _, name in form.fields['predecessors'].choices], expected)
        self.assertEqual([name for key, name in form.fields['source_task_key'].choices if key], expected)

    def test_diary_and_future_template_source_selectors_follow_subgraphs(self):
        diary = DiaryAPI(actor=self.actor).create_diary(name='Ordered choices', template_version_key=self.version.key,
                                                       milestone_dates={'target': date(2027, 6, 20)})
        with self.settings(CREATION_TEST_KEYS=(diary.key,)):
            response = self.client.get(self.url(key=diary.key))
        self.assertEqual(response.status_code, 200)
        expected = ['Z source', 'Y middle', 'A end', 'B unrelated', 'C target']
        for name in ('creation_form', 'future_form'):
            self.assertEqual([label for key, label in response.context[name].fields['source_task_key'].choices if key], expected)
