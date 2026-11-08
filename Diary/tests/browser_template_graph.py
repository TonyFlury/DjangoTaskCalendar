"""Real-browser checks for the manager's read-only template graph.

Run explicitly with Django's test command and a separate PostgreSQL test database.
"""
import os

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
from Diary.models import TemplateVersion


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
