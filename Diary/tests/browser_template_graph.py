"""Real-browser checks for the manager's read-only template graph.

Run explicitly with Django's test command and a separate PostgreSQL test database.
"""
import os
from dataclasses import replace
from datetime import date

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select, WebDriverWait

from Diary.api import Actor, DiaryAPI, EntrySpec
from Diary.choices import DateKind
from Diary.models import CalendarEntry, TemplateVersion


@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=())
class TemplateGraphBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        model = get_user_model()
        self.manager = model.objects.create_user(**{model.USERNAME_FIELD: 'graph@example.test'})
        self.manager.groups.add(Group.objects.create(name='Planners'))
        Group.objects.create(name='Participants')
        api = DiaryAPI(actor=Actor(f'user:{self.manager.pk}', frozenset({'Planners'})))
        self.template = api.create_template(name='Graph preview')
        self.specs = [EntrySpec(name, DateKind.ANNUAL, month=6, day=1) for name in (
            'Start', 'Book venue', 'Invite team', 'Final review', 'Independent task',
            '<img src=x onerror="window.graphInjected=true"> A long task name that must remain plain text')]
        start, book, invite, review, *_ = self.specs
        self.version = self.template.save_version(entries=self.specs, predecessors={
            book.entry_key: [start.entry_key], invite.entry_key: [start.entry_key],
            review.entry_key: [book.entry_key, invite.entry_key]}, expected_version_key=None)
        self.client.force_login(self.manager)
        options = webdriver.ChromeOptions()
        for argument in ('--headless', '--no-sandbox', '--disable-dev-shm-usage'):
            options.add_argument(argument)
        options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
        self.driver = webdriver.Chrome(service=Service(executable_path=os.environ.get('DIARY_CHROMEDRIVER')),
                                       options=options)
        self.addCleanup(self.driver.quit)
        self.wait = WebDriverWait(self.driver, 10, ignored_exceptions=(StaleElementReferenceException,))
        self.driver.set_window_size(1400, 1400)
        self.driver.get(self.live_server_url + '/diary/templates/')
        self.driver.add_cookie({'name': settings.SESSION_COOKIE_NAME,
                               'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'path': '/'})
        self.driver.get(self.live_server_url + '/diary/templates/edit/Graph%20preview/')
        self.wait.until(lambda driver: len(driver.find_elements(By.CSS_SELECTOR, '.diary-graph-node')) == 6)

    def count(self, selector):
        return len(self.driver.find_elements(By.CSS_SELECTOR, selector))

    def node(self, spec):
        return self.driver.find_element(By.CSS_SELECTOR, f'.diary-graph-node[data-task-key="{spec.entry_key}"]')

    def row(self, spec):
        return self.driver.find_element(By.CSS_SELECTOR,
            f'.diary-template-task:has(.diary-template-field-entry-key[value="{spec.entry_key}"])')

    def test_graph_layout_form_updates_keyboard_and_narrow_screen(self):
        driver = self.driver
        self.assertEqual(self.count('.diary-graph-edge'), 4)
        if os.environ.get('DIARY_GRAPH_SCREENSHOT'):
            self.driver.find_element(By.CSS_SELECTOR, '.diary-template-graph').screenshot(os.environ['DIARY_GRAPH_SCREENSHOT'])
        start, book, invite, review, independent, unsafe = self.specs
        y = lambda spec: float(self.node(spec).find_element(By.TAG_NAME, 'rect').get_attribute('y'))
        self.assertLess(y(start), y(book))
        self.assertEqual(y(book), y(invite))
        self.assertLess(y(book), y(review))
        self.assertEqual(y(independent), y(start))
        self.assertEqual(self.node(unsafe).get_attribute('aria-label'), f'Edit task: {unsafe.name}')
        self.assertFalse(driver.execute_script('return Boolean(window.graphInjected)'))
        self.assertEqual(self.count('.diary-graph-canvas img'), 0)

        # Native links support keyboard activation and take focus to the editing field.
        self.node(book).send_keys(Keys.ENTER)
        name = self.row(book).find_element(By.CSS_SELECTOR, '.diary-template-field-name')
        self.assertEqual(driver.switch_to.active_element, name)
        name.clear()
        name.send_keys('Updated venue')
        self.wait.until(lambda browser: self.node(book).get_attribute('aria-label') == 'Edit task: Updated venue')
        self.assertEqual(self.count('.diary-graph-edge'), 4, 'Renaming must preserve dependencies')

        select = Select(self.row(independent).find_element(By.CSS_SELECTOR, '.diary-template-field-predecessors'))
        select.select_by_value(str(start.entry_key))
        self.assertIn(str(start.entry_key), [option.get_attribute('value') for option in select.all_selected_options])
        self.wait.until(lambda browser: self.count('.diary-graph-edge') == 5)
        self.row(independent).find_element(By.CSS_SELECTOR, '.diary-template-remove').click()
        self.wait.until(lambda browser: self.count('.diary-graph-node') == 5)
        self.assertEqual(self.count('.diary-graph-edge'), 4)
        self.row(independent).find_element(By.CSS_SELECTOR, '.diary-template-remove').click()
        self.wait.until(lambda browser: self.count('.diary-graph-node') == 6)

        # Zoom and pan stay inside the graph; fitting works after a viewport resize.
        driver.find_element(By.CSS_SELECTOR, '[data-graph-action="in"]').click()
        before = driver.find_element(By.CSS_SELECTOR, '.diary-graph-zoom').get_attribute('value')
        viewport = driver.find_element(By.CSS_SELECTOR, '.diary-graph-viewport')
        viewport.send_keys('-')
        self.assertNotEqual(driver.find_element(By.CSS_SELECTOR, '.diary-graph-zoom').get_attribute('value'), before)
        driver.set_window_size(390, 900)
        driver.find_element(By.CSS_SELECTOR, '[data-graph-action="fit"]').click()
        self.assertTrue(driver.execute_script('return document.documentElement.scrollWidth <= innerWidth'))
        self.assertTrue(driver.execute_script('const v = document.querySelector(".diary-graph-viewport"); return v.scrollWidth <= v.clientWidth + 1'))
        driver.execute_script('document.querySelector(".diary-template-editor").style.setProperty("--diary-surface", "rgb(230, 240, 250)")')
        self.assertEqual(driver.execute_script('return getComputedStyle(document.querySelector(".diary-graph-node rect")).fill'), 'rgb(230, 240, 250)')
        self.assertEqual(TemplateVersion.objects.count(), 1)
        self.assertCountEqual([entry['name'] for entry in self.template.latest_version().read()['entries']],
                              [spec.name for spec in self.specs])
        self.assertEqual([item for item in driver.get_log('browser') if item['source'] == 'javascript' and item['level'] == 'SEVERE'], [])

    def test_empty_unnamed_and_larger_graph(self):
        driver = self.driver
        driver.get(self.live_server_url + '/diary/templates/new/')
        self.wait.until(lambda browser: 'No tasks yet' in browser.find_element(By.CSS_SELECTOR, '.diary-graph-status').text)
        self.assertFalse(driver.find_element(By.CSS_SELECTOR, '.diary-graph-viewport').is_displayed())
        driver.find_element(By.CSS_SELECTOR, '.diary-template-add').click()
        self.wait.until(lambda browser: self.count('.diary-graph-node') == 1)
        self.assertIn('Unnamed task', driver.find_element(By.CSS_SELECTOR, '.diary-graph-node').get_attribute('aria-label'))
        # Add enough proposed tasks to require zoom/scroll, without creating database records.
        driver.execute_script('for (let i = 0; i < 24; i++) document.querySelector(".diary-template-add").click()')
        self.wait.until(lambda browser: self.count('.diary-graph-node') == 25)
        driver.find_element(By.CSS_SELECTOR, '[data-graph-action="in"]').click()
        viewport = driver.find_element(By.CSS_SELECTOR, '.diary-graph-viewport')
        self.assertTrue(driver.execute_script('return arguments[0].scrollWidth > arguments[0].clientWidth', viewport))
        viewport.send_keys(Keys.ARROW_RIGHT)
        self.wait.until(lambda browser: browser.execute_script('return arguments[0].scrollLeft > 0', viewport))
        driver.execute_script('arguments[0].scrollLeft = 0', viewport)
        ActionChains(driver).move_to_element_with_offset(viewport, 50, 10).click_and_hold().move_by_offset(-80, 0).release().perform()
        self.assertGreater(driver.execute_script('return arguments[0].scrollLeft', viewport), 0)
        self.assertTrue(driver.execute_script('return document.documentElement.scrollWidth <= innerWidth'))
        self.assertEqual(TemplateVersion.objects.count(), 1)

    def test_task_relative_date_controls_save_without_creating_completion_dependencies(self):
        driver = self.driver
        start, book = self.specs[:2]
        row = self.row(book)
        Select(row.find_element(By.CSS_SELECTOR, '.diary-template-field-date-kind')).select_by_value('task')
        source = row.find_element(By.CSS_SELECTOR, '.diary-template-field-source-task-key')
        self.assertTrue(source.is_displayed())
        self.assertNotIn(str(book.entry_key), [option.get_attribute('value') for option in Select(source).options])
        Select(source).select_by_value(str(start.entry_key))
        offset = row.find_element(By.CSS_SELECTOR, '.diary-template-field-day-offset')
        self.assertTrue(offset.is_displayed())
        offset.clear()
        offset.send_keys('3')
        Select(row.find_element(By.CSS_SELECTOR, '.diary-template-field-predecessors')).deselect_all()
        driver.find_element(By.CSS_SELECTOR, '.diary-template-save').click()
        self.wait.until(lambda browser: 'Version 2' in browser.find_element(By.CSS_SELECTOR, '.diary-template-version').text)
        version = self.template.latest_version()
        saved = next(entry for entry in version.read()['entries'] if entry['entry_key'] == book.entry_key)
        self.assertEqual((saved['date_kind'], saved['source_task_key'], saved['day_offset']),
                         ('task', start.entry_key, 3))
        self.assertEqual(saved['predecessors'], ())
        self.assertEqual(self.row(book).find_element(By.CSS_SELECTOR, '.diary-template-field-source-task-key').get_attribute('value'),
                         str(start.entry_key))

    def show_layout(self, names, graph):
        """Use a real saved template, with deliberately unhelpful alphabetical task order."""
        specs = [EntrySpec(name, DateKind.ANNUAL, month=6, day=1) for name in names]
        self.template.save_version(entries=specs,
            predecessors={specs[index].entry_key: [specs[source].entry_key for source in sources]
                          for index, sources in graph.items()}, expected_version_key=self.version.key)
        self.driver.refresh()
        self.wait.until(lambda browser: self.count('.diary-graph-node') == len(specs)
                         and 'Version 2' in browser.find_element(By.CSS_SELECTOR, '.diary-template-version').text)
        return specs

    def test_layout_removes_avoidable_crossings_in_connected_branches(self):
        specs = self.show_layout(['A root', 'B root', 'C root', 'D branch', 'E branch', 'F branch', 'Z join'],
                                  {3: [2], 4: [1], 5: [0], 6: [3, 4, 5]})
        x = lambda index: float(self.node(specs[index]).find_element(By.TAG_NAME, 'rect').get_attribute('x'))
        connections = [(0, 5), (1, 4), (2, 3)]
        crossings = sum((x(a) - x(c)) * (x(b) - x(d)) < 0
                        for index, (a, b) in enumerate(connections) for c, d in connections[index + 1:])
        # Alphabetical order has three crossings here. This graph admits a crossing-free arrangement.
        self.assertEqual(crossings, 0)
        self.assertEqual(self.count('.diary-graph-edge'), 6)
        before = self.driver.execute_script('return Array.from(document.querySelectorAll(".diary-graph-node"), n => [n.dataset.taskKey, n.querySelector("rect").getAttribute("x")])')
        name = self.row(specs[0]).find_element(By.CSS_SELECTOR, '.diary-template-field-name')
        name.send_keys(' renamed')
        self.wait.until(lambda browser: 'renamed' in self.node(specs[0]).get_attribute('aria-label'))
        after = self.driver.execute_script('return Array.from(document.querySelectorAll(".diary-graph-node"), n => [n.dataset.taskKey, n.querySelector("rect").getAttribute("x")])')
        self.assertEqual(before, after)

    def test_long_connections_do_not_pass_through_other_task_boxes(self):
        self.show_layout(['A start', 'B middle', 'C middle', 'D finish'], {1: [0], 2: [1], 3: [0, 2]})
        collisions = self.driver.execute_script('''
            const boxes = Array.from(document.querySelectorAll('.diary-graph-node'), node =>
                ({key: node.dataset.taskKey, box: node.querySelector('rect').getBBox()}));
            const collisions = [];
            for (const path of document.querySelectorAll('.diary-graph-edge')) {
                const others = boxes.filter(node => node.key !== path.dataset.sourceKey && node.key !== path.dataset.targetKey);
                for (let distance = 0; distance <= path.getTotalLength(); distance += 2) {
                    const point = path.getPointAtLength(distance);
                    for (const {key, box} of others) {
                        if (point.x > box.x && point.x < box.x + box.width && point.y > box.y && point.y < box.y + box.height) {
                            collisions.push(key);
                        }
                    }
                }
            }
            return collisions;
        ''')
        self.assertEqual(collisions, [])
        self.assertEqual(self.count('.diary-graph-node'), 4)
        self.assertEqual(self.count('.diary-graph-edge'), 4)

    def test_dense_graph_with_unavoidable_crossings_keeps_all_tasks_and_connections(self):
        # A complete DAG also exercises the bounded waypoint budget and exterior routing lanes.
        count = 36
        self.show_layout([f'Task {index:02}' for index in range(count)],
                         {index: list(range(index)) for index in range(1, count)})
        self.assertEqual(self.count('.diary-graph-node'), count)
        self.assertEqual(self.count('.diary-graph-edge'), count * (count - 1) // 2)
        self.assertTrue(self.driver.execute_script('''
            return Array.from(document.querySelectorAll('.diary-graph-edge'), path => path.getTotalLength())
                .every(length => Number.isFinite(length) && length > 0);
        '''))
        self.assertEqual([item for item in self.driver.get_log('browser')
                          if item['source'] == 'javascript' and item['level'] == 'SEVERE'], [])

    def test_task_selectors_follow_subgraphs_and_keep_selections_when_renamed(self):
        specs = self.show_layout(['A end', 'B unrelated', 'C target', 'Y middle', 'Z source'],
                                 {0: [3], 3: [4]})
        end, unrelated, target, middle, root = specs
        expected = [str(spec.entry_key) for spec in (root, middle, end, unrelated)]
        target_row = self.row(target)

        def values(field_name):
            return [option.get_attribute('value') for option in
                    Select(target_row.find_element(By.CSS_SELECTOR, f'.diary-template-field-{field_name}')).options
                    if option.get_attribute('value')]

        self.wait.until(lambda browser: values('predecessors') == expected)

        self.assertEqual(values('source-task-key'), expected)
        Select(target_row.find_element(By.CSS_SELECTOR, '.diary-template-field-predecessors')).select_by_value(str(end.entry_key))
        Select(target_row.find_element(By.CSS_SELECTOR, '.diary-template-field-date-kind')).select_by_value('task')
        Select(target_row.find_element(By.CSS_SELECTOR, '.diary-template-field-source-task-key')).select_by_value(str(middle.entry_key))
        name = self.row(root).find_element(By.CSS_SELECTOR, '.diary-template-field-name')
        name.clear()
        name.send_keys('Renamed source')
        self.wait.until(lambda browser: 'Renamed source' in self.node(root).get_attribute('aria-label'))
        self.assertEqual(values('predecessors'), expected)
        self.assertEqual(values('source-task-key'), expected)
        self.assertEqual([option.get_attribute('value') for option in
                         Select(target_row.find_element(By.CSS_SELECTOR, '.diary-template-field-predecessors')).all_selected_options],
                         [str(end.entry_key)])
        self.assertEqual(target_row.find_element(By.CSS_SELECTOR, '.diary-template-field-source-task-key').get_attribute('value'),
                         str(middle.entry_key))
        search = target_row.find_element(By.CSS_SELECTOR, '.diary-template-predecessor-search')
        search.send_keys('no match')
        self.assertEqual(values('predecessors'), [str(end.entry_key)])
        search.clear()
        search.send_keys(' ')
        self.wait.until(lambda browser: values('predecessors') == expected)

    def show_milestone_graph(self):
        api = DiaryAPI(actor=self.template.actor)
        api.define_milestones(definitions={'event_date': 'Event date', 'close': 'Bookings <close>',
                                           'unused': 'Unused milestone'})
        specs = self.specs.copy()
        specs[0] = replace(specs[0], date_kind=DateKind.SOURCE, milestone_name='event_date', month=None, day=None)
        specs[1] = replace(specs[1], date_kind=DateKind.RELATIVE, milestone_name='event_date',
                           day_offset=-7, month=None, day=None)
        specs[2] = replace(specs[2], date_kind=DateKind.RELATIVE, milestone_name='close',
                           day_offset=2, month=None, day=None)
        self.version = self.template.save_version(entries=specs,
            predecessors={specs[1].entry_key: [specs[0].entry_key], specs[2].entry_key: [specs[0].entry_key],
                          specs[3].entry_key: [specs[1].entry_key, specs[2].entry_key]}, expected_version_key=self.version.key)
        self.driver.refresh()
        self.wait.until(lambda browser: self.count('.diary-graph-milestone') == 2)
        return specs

    def test_only_used_milestones_are_diamonds_with_separate_date_relations(self):
        specs = self.show_milestone_graph()
        driver = self.driver
        self.assertEqual(self.count('.diary-graph-node'), 6)
        self.assertEqual(self.count('.diary-graph-milestone polygon'), 2)
        self.assertEqual(self.count('.diary-graph-milestone rect'), 0)
        self.assertEqual(self.count('.diary-graph-milestone[data-milestone-name="event_date"]'), 1)
        self.assertEqual(self.count('.diary-graph-milestone[data-milestone-name="unused"]'), 0)
        self.assertEqual(self.count('.diary-graph-edge[data-relation="dependency"]'), 4)
        self.assertEqual(self.count('.diary-graph-edge[data-relation="date"]'), 3)
        close = driver.find_element(By.CSS_SELECTOR, '.diary-graph-milestone[data-milestone-name="close"]')
        self.assertIn('Bookings <close>', close.get_attribute('aria-label'))
        self.assertEqual(self.count('.diary-graph-milestone close'), 0)
        date_path = driver.find_element(By.CSS_SELECTOR,
            f'.diary-graph-edge-date[data-target-key="{specs[1].entry_key}"]')
        self.assertIn('7 calendar days before milestone', date_path.get_attribute('aria-label'))
        self.assertNotEqual(driver.execute_script('return getComputedStyle(arguments[0]).strokeDasharray', date_path), 'none')
        close.send_keys(Keys.TAB)  # Diamonds are focusable read-only items, not editing links.
        driver.set_window_size(390, 900)
        driver.find_element(By.CSS_SELECTOR, '[data-graph-action="fit"]').click()
        self.assertTrue(driver.execute_script('return document.documentElement.scrollWidth <= innerWidth'))
        self.assertEqual([item for item in driver.get_log('browser')
                          if item['source'] == 'javascript' and item['level'] == 'SEVERE'], [])
        self.assertEqual(TemplateVersion.objects.count(), 2)

    def test_milestone_graph_updates_offsets_rules_and_deleted_tasks_without_saving(self):
        specs = self.show_milestone_graph()
        driver = self.driver
        Select(self.row(specs[2]).find_element(By.CSS_SELECTOR, '.diary-template-field-date-kind')).select_by_value('annual')
        self.wait.until(lambda browser: self.count('.diary-graph-milestone') == 1)
        offset = self.row(specs[1]).find_element(By.CSS_SELECTOR, '.diary-template-field-day-offset')
        offset.clear()
        offset.send_keys('4')
        self.wait.until(lambda browser: '4 calendar days after milestone' in browser.find_element(By.CSS_SELECTOR,
            f'.diary-graph-edge-date[data-target-key="{specs[1].entry_key}"]').get_attribute('aria-label'))
        self.row(specs[0]).find_element(By.CSS_SELECTOR, '.diary-template-remove').click()
        self.wait.until(lambda browser: self.count('.diary-graph-edge-date') == 1)
        self.assertEqual(self.count('.diary-graph-milestone'), 1)
        self.row(specs[1]).find_element(By.CSS_SELECTOR, '.diary-template-remove').click()
        self.wait.until(lambda browser: self.count('.diary-graph-milestone') == 0)
        self.row(specs[1]).find_element(By.CSS_SELECTOR, '.diary-template-remove').click()
        self.wait.until(lambda browser: self.count('.diary-graph-milestone') == 1)
        Select(self.row(specs[1]).find_element(By.CSS_SELECTOR, '.diary-template-field-milestone-name')).select_by_value('unused')
        self.wait.until(lambda browser: self.count('.diary-graph-milestone[data-milestone-name="unused"]') == 1)
        Select(self.row(specs[1]).find_element(By.CSS_SELECTOR, '.diary-template-field-date-kind')).select_by_value('task')
        self.wait.until(lambda browser: self.count('.diary-graph-milestone') == 0)
        saved = next(entry for entry in self.template.latest_version().read()['entries'] if entry['entry_key'] == specs[1].entry_key)
        self.assertEqual((saved['milestone_name'], saved['day_offset']), ('event_date', -7))

    def milestone_y(self, name):
        return self.driver.execute_script('return arguments[0].querySelector("polygon").getBBox().y',
            self.driver.find_element(By.CSS_SELECTOR, f'.diary-graph-milestone[data-milestone-name="{name}"]'))

    def task_y(self, spec):
        return float(self.node(spec).find_element(By.TAG_NAME, 'rect').get_attribute('y'))

    def test_offsets_position_negative_before_and_nonnegative_after_the_milestone(self):
        specs = self.show_milestone_graph()
        start, book, invite, review, independent, _ = specs
        Select(self.row(invite).find_element(By.CSS_SELECTOR, '.diary-template-field-milestone-name')).select_by_value('event_date')
        Select(self.row(independent).find_element(By.CSS_SELECTOR, '.diary-template-field-date-kind')).select_by_value('relative')
        Select(self.row(independent).find_element(By.CSS_SELECTOR, '.diary-template-field-milestone-name')).select_by_value('event_date')
        offset = self.row(independent).find_element(By.CSS_SELECTOR, '.diary-template-field-day-offset')
        offset.clear()
        offset.send_keys('-2')
        Select(self.row(review).find_element(By.CSS_SELECTOR, '.diary-template-field-date-kind')).select_by_value('task')
        Select(self.row(review).find_element(By.CSS_SELECTOR, '.diary-template-field-source-task-key')).select_by_value(str(book.entry_key))
        offset = self.row(review).find_element(By.CSS_SELECTOR, '.diary-template-field-day-offset')
        offset.clear()
        offset.send_keys('3')
        # -7, (-7 + 3), -2, zero and +2 must retain their relative order.
        self.wait.until(lambda browser: self.task_y(book) < self.task_y(review) < self.task_y(independent)
                         < self.milestone_y('event_date') < self.task_y(invite))
        self.assertGreater(self.task_y(start), self.milestone_y('event_date'))
        self.assertLess(self.task_y(start), self.task_y(invite))
        self.assertNotIn('not a valid', self.driver.find_element(By.CSS_SELECTOR, '.diary-graph-status').text)
        backwards = self.driver.find_element(By.CSS_SELECTOR,
            f'.diary-graph-edge[data-source-key="{start.entry_key}"][data-target-key="{book.entry_key}"]')
        self.assertTrue(backwards.get_attribute('marker-start'))
        self.assertEqual(self.count('.diary-graph-edge[data-relation="dependency"]'), 4)

        # Editing an offset changes placement, including tasks whose dates reference this task.
        offset = self.row(book).find_element(By.CSS_SELECTOR, '.diary-template-field-day-offset')
        offset.clear()
        offset.send_keys('8')
        self.wait.until(lambda browser: self.milestone_y('event_date') < self.task_y(invite)
                         < self.task_y(book) < self.task_y(review))
        offset.clear()
        offset.send_keys('0')
        self.wait.until(lambda browser: self.task_y(book) > self.milestone_y('event_date'))
        self.assertEqual(TemplateVersion.objects.count(), 2)

    def test_milestones_are_positioned_relative_to_their_tasks_not_forced_to_a_start_row(self):
        specs = self.show_milestone_graph()
        start, book, invite, *_ = specs
        Select(self.row(invite).find_element(By.CSS_SELECTOR, '.diary-template-field-date-kind')).select_by_value('source')
        self.wait.until(lambda browser: self.milestone_y('close') > self.milestone_y('event_date'))
        self.assertGreater(self.task_y(start), self.milestone_y('event_date'))
        self.assertGreater(self.task_y(invite), self.milestone_y('close'))
        self.assertLess(self.task_y(book), self.milestone_y('event_date'))
        self.assertNotIn('not a valid', self.driver.find_element(By.CSS_SELECTOR, '.diary-graph-status').text)

    def test_zero_offset_chains_enter_task_tops_without_changing_actual_due_dates(self):
        specs = self.show_milestone_graph()
        start, book, _, review, before, after = specs

        def set_date_source(task, source, days):
            row = self.row(task)
            Select(row.find_element(By.CSS_SELECTOR, '.diary-template-field-date-kind')).select_by_value('task')
            Select(row.find_element(By.CSS_SELECTOR, '.diary-template-field-source-task-key')).select_by_value(str(source.entry_key))
            offset = row.find_element(By.CSS_SELECTOR, '.diary-template-field-day-offset')
            offset.clear()
            offset.send_keys(str(days))

        set_date_source(book, start, 0)
        set_date_source(review, book, 0)
        set_date_source(before, book, -1)
        set_date_source(after, book, 1)
        self.wait.until(lambda browser: self.task_y(before) < self.milestone_y('event_date')
                         < self.task_y(start) < self.task_y(book) < self.task_y(review) < self.task_y(after))
        for source_key, task in [('milestone:event_date', start), (str(start.entry_key), book), (str(book.entry_key), review)]:
            relation = 'date' if source_key.startswith('milestone:') else 'dependency'
            edge = self.driver.find_element(By.CSS_SELECTOR,
                f'.diary-graph-edge[data-relation="{relation}"][data-source-key="{source_key}"][data-target-key="{task.entry_key}"]')
            self.assertTrue(edge.get_attribute('marker-end'))
            self.assertFalse(edge.get_attribute('marker-start'))
            end = self.driver.execute_script('const p = arguments[0].getPointAtLength(arguments[0].getTotalLength()); return {x: p.x, y: p.y}', edge)
            self.assertAlmostEqual(end['y'], self.task_y(task) - 4, delta=.1)
            if relation == 'date':
                self.assertIn('Same date as', edge.get_attribute('aria-label'))
            else:
                self.assertEqual(self.count(f'.diary-graph-edge-date[data-source-key="{source_key}"][data-target-key="{task.entry_key}"]'), 0)

        self.driver.find_element(By.CSS_SELECTOR, '.diary-template-save').click()
        self.wait.until(lambda browser: 'Version 3' in browser.find_element(By.CSS_SELECTOR, '.diary-template-version').text)
        version = self.template.latest_version()
        saved = {entry['entry_key']: entry for entry in version.read()['entries']}
        self.assertEqual(saved[book.entry_key]['day_offset'], 0)
        self.assertEqual(saved[review.entry_key]['day_offset'], 0)
        diary = DiaryAPI(actor=self.template.actor).create_diary(name='Same-day graph', template_version_key=version.key,
            milestone_dates={'event_date': date(2027, 6, 10), 'close': date(2027, 6, 1)})
        dates = {entry.entry_key: entry.due_date for entry in CalendarEntry.objects.filter(calendar_id=diary.key)}
        for task in (start, book, review):
            self.assertEqual(dates[task.entry_key], date(2027, 6, 10))
        self.assertEqual(dates[before.entry_key], date(2027, 6, 9))
        self.assertEqual(dates[after.entry_key], date(2027, 6, 11))

    def test_completion_arrow_replaces_date_arrow_without_losing_date_positioning(self):
        specs = self.show_milestone_graph()
        start, book, *_ = specs
        row = self.row(book)
        Select(row.find_element(By.CSS_SELECTOR, '.diary-template-field-date-kind')).select_by_value('task')
        Select(row.find_element(By.CSS_SELECTOR, '.diary-template-field-source-task-key')).select_by_value(str(start.entry_key))
        offset = row.find_element(By.CSS_SELECTOR, '.diary-template-field-day-offset')
        offset.clear()
        offset.send_keys('0')
        date_selector = f'.diary-graph-edge-date[data-source-key="{start.entry_key}"][data-target-key="{book.entry_key}"]'
        dependency_selector = f'.diary-graph-edge[data-relation="dependency"][data-source-key="{start.entry_key}"][data-target-key="{book.entry_key}"]'
        self.wait.until(lambda browser: self.count(date_selector) == 0 and self.task_y(book) > self.task_y(start))
        self.assertEqual(self.count(dependency_selector), 1)
        Select(row.find_element(By.CSS_SELECTOR, '.diary-template-field-predecessors')).deselect_all()
        self.wait.until(lambda browser: self.count(date_selector) == 1 and self.count(dependency_selector) == 0)

        # Even an opposite-direction completion dependency takes visual priority; the date still places Book below Start.
        Select(self.row(start).find_element(By.CSS_SELECTOR, '.diary-template-field-predecessors')).select_by_value(str(book.entry_key))
        reverse_dependency = f'.diary-graph-edge[data-relation="dependency"][data-source-key="{book.entry_key}"][data-target-key="{start.entry_key}"]'
        self.wait.until(lambda browser: self.count(date_selector) == 0 and self.count(reverse_dependency) == 1)
        self.assertGreater(self.task_y(book), self.task_y(start))
        self.assertNotIn('not a valid', self.driver.find_element(By.CSS_SELECTOR, '.diary-graph-status').text)
