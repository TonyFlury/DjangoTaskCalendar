"""One unchanged, identifier-free host endpoint switches package presentations."""
import os

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from Diary.tests.test_personal_view import PersonalDiaryFixtures


@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers', 'Reviewers'),
                   ROOT_URLCONF='Diary.tests.test_diary_presentations')
class DiaryPresentationBrowserTests(PersonalDiaryFixtures, StaticLiveServerTestCase):
    def setUp(self):
        super().setUp()
        scope = override_settings(PRESENTATION_DIARY_KEY=self.keys[0], MANAGER_TEST_KEYS=tuple(self.keys[:3]))
        scope.enable()
        self.addCleanup(scope.disable)
        options = webdriver.ChromeOptions()
        for argument in ('--headless', '--no-sandbox', '--disable-dev-shm-usage'):
            options.add_argument(argument)
        if 'without_javascript' in self._testMethodName:
            options.add_experimental_option('prefs', {'profile.managed_default_content_settings.javascript': 2})
        self.driver = webdriver.Chrome(service=Service(executable_path=os.environ.get('DIARY_CHROMEDRIVER')), options=options)
        self.addCleanup(self.driver.quit)
        self.wait = WebDriverWait(self.driver, 10, ignored_exceptions=(StaleElementReferenceException,))
        self.driver.set_window_size(1400, 1000)
        self.driver.get(self.live_server_url + '/fixed/personal/')
        self.driver.add_cookie({'name': settings.SESSION_COOKIE_NAME,
                               'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'path': '/'})
        self.driver.get(self.live_server_url + '/fixed/personal/?view=list&date=2027-06-20')

    def test_same_url_preferences_filters_and_post_selected_task(self):
        driver = self.driver
        driver.find_element(By.LINK_TEXT, 'Week').click()
        self.wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-calendar-week'))
        self.assertIn('/fixed/personal/?', driver.current_url)
        driver.find_element(By.LINK_TEXT, 'Month').click()
        self.wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-calendar-month'))
        driver.get(self.live_server_url + '/fixed/personal/?date=2027-06-20')
        self.assertTrue(driver.find_element(By.CSS_SELECTOR, '.diary-calendar-month').is_displayed())
        driver.find_element(By.LINK_TEXT, 'Day').click()
        self.wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-calendar-day-view'))
        self.assertNotIn('diary_key=', driver.current_url)
        self.assertEqual(driver.find_elements(By.CSS_SELECTOR, 'input[name="diary_key"]'), [])
        driver.find_element(By.CSS_SELECTOR, 'button.diary-calendar-task-link[value="' + str(self.ready) + '"]').click()
        self.wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-detail-heading'))
        self.assertIn('/fixed/task/?calendar_return=', driver.current_url)
        driver.find_element(By.CSS_SELECTOR, '.diary-note-form textarea').send_keys('Unified presentation note')
        driver.find_element(By.CSS_SELECTOR, '.diary-note-submit').click()
        self.wait.until(lambda browser: 'Unified presentation note' in browser.find_element(By.TAG_NAME, 'body').text)
        driver.find_element(By.CSS_SELECTOR, '.diary-calendar-return').click()
        self.wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-calendar-day-view'))
        # The day dialog is optional on return; close it through the package link if present.
        close = driver.find_elements(By.CSS_SELECTOR, '.diary-calendar-day-panel [data-calendar-close-link]')
        if close:
            close[0].click()
        driver.find_element(By.LINK_TEXT, 'List').click()
        self.wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-personal-filters'))
        self.assertEqual(driver.find_element(By.NAME, 'view').get_attribute('value'), 'list')
        self.assertNotIn('diary_key=', driver.current_url)

    def test_without_javascript_switching_and_task_selection(self):
        driver = self.driver
        driver.find_element(By.LINK_TEXT, 'Month').click()
        self.wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-calendar-month'))
        self.assertTrue(driver.find_element(By.CSS_SELECTOR, '.diary-calendar-filters-content').is_displayed())
        driver.find_element(By.LINK_TEXT, 'Day').click()
        self.wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-calendar-day-view'))
        driver.find_element(By.CSS_SELECTOR, 'button.diary-calendar-task-link[value="' + str(self.ready) + '"]').click()
        self.wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-calendar-return'))
        driver.find_element(By.CSS_SELECTOR, '.diary-calendar-return').click()
        self.wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-calendar-day-view'))

    def test_manager_graph_css_zoom_and_existing_host_task_actions(self):
        self.client.force_login(self.manager)
        driver = self.driver
        driver.add_cookie({'name': settings.SESSION_COOKIE_NAME,
                           'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'path': '/'})
        driver.get(self.live_server_url + '/fixed/manager/?view=graph&include_completed=1')
        self.wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-manager-graph .diary-graph-node'))
        self.assertTrue(driver.find_elements(By.CSS_SELECTOR, '.diary-graph-milestone'))
        self.assertTrue(driver.find_elements(By.CSS_SELECTOR, '.diary-graph-task-completed'))
        self.assertTrue(driver.find_elements(By.CSS_SELECTOR, '.diary-graph-task-late'))
        self.assertTrue(driver.find_elements(By.CSS_SELECTOR, '.diary-graph-task-blocked-late'))
        self.assertNotIn('diary_key=', driver.current_url)
        colours = driver.execute_script('''
            const graph=document.querySelector('.diary-manager-graph');
            graph.style.setProperty('--diary-task-completed-background','#123456');
            graph.style.setProperty('--diary-task-completed-border','#654321');
            graph.style.setProperty('--diary-task-completed-text','#abcdef');
            const node=graph.querySelector('.diary-graph-node.diary-graph-task-completed');
            return [getComputedStyle(node.querySelector('rect')).fill,
                    getComputedStyle(node.querySelector('rect')).stroke,
                    getComputedStyle(node.querySelector('text')).fill];
        ''')
        self.assertEqual(colours, ['rgb(18, 52, 86)', 'rgb(101, 67, 33)', 'rgb(171, 205, 239)'])
        driver.find_element(By.CSS_SELECTOR, '.diary-graph-colours').click()
        self.assertTrue(driver.find_elements(By.CSS_SELECTOR, '.diary-graph-neutral .diary-graph-task-blocked-pattern'))
        for width in (1400, 600):
            driver.set_window_size(width, 900)
            panel = driver.find_element(By.CSS_SELECTOR, '.diary-graph-viewport')
            before = panel.rect
            for _ in range(5):
                driver.find_element(By.CSS_SELECTOR, '[data-graph-action="in"]').click()
            self.assertAlmostEqual(panel.rect['width'], before['width'], delta=2)
            self.assertAlmostEqual(panel.rect['height'], before['height'], delta=2)
            driver.find_element(By.CSS_SELECTOR, '[data-graph-action="fit"]').click()
        driver.find_element(By.CSS_SELECTOR, '.diary-manager-graph-help').click()
        self.assertTrue(driver.find_element(By.CSS_SELECTOR, '.diary-manager-graph-help-dialog').is_displayed())
        driver.find_element(By.CSS_SELECTOR, '.diary-manager-graph-help-dialog [data-graph-close]').click()
        # The scoped SVG action delegates to the host's existing POST task selection.
        driver.find_element(By.CSS_SELECTOR, '.diary-graph-node[data-entry-key="' + str(self.ready) + '"]').click()
        self.wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-detail-heading'))
        self.assertIn('/fixed/task/?calendar_return=', driver.current_url)
        driver.find_element(By.CSS_SELECTOR, '.diary-note-form textarea').send_keys('Graph host navigation note')
        driver.find_element(By.CSS_SELECTOR, '.diary-note-submit').click()
        self.wait.until(lambda browser: 'Graph host navigation note' in browser.find_element(By.TAG_NAME, 'body').text)
        driver.find_element(By.CSS_SELECTOR, '.diary-calendar-return').click()
        self.wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-manager-graph .diary-graph-node'))
        self.assertIn('view=graph', driver.current_url)
        self.assertIn('include_completed=1', driver.current_url)

    def test_without_javascript_manager_graph_keeps_existing_task_list_and_filters(self):
        self.client.force_login(self.manager)
        driver = self.driver
        driver.add_cookie({'name': settings.SESSION_COOKIE_NAME,
                           'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'path': '/'})
        driver.get(self.live_server_url + '/fixed/manager/?view=graph')
        self.assertTrue(driver.find_element(By.CSS_SELECTOR, '.diary-manager-graph-task-list').get_attribute('open'))
        self.assertTrue(driver.find_element(By.CSS_SELECTOR, '.diary-manager-graph-filter-content').is_displayed())
        self.assertTrue(driver.find_element(By.CSS_SELECTOR, '.diary-manager-graph-help-content').is_displayed())
        driver.find_element(By.CSS_SELECTOR, '.diary-manager-graph-task-list button[value="' + str(self.ready) + '"]').click()
        self.wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-detail-heading'))
        driver.find_element(By.CSS_SELECTOR, '.diary-detail-complete').click()
        self.wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-detail-completed'))
        driver.find_element(By.CSS_SELECTOR, '.diary-calendar-return').click()
        self.wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-manager-graph'))
        self.assertEqual(driver.find_elements(By.CSS_SELECTOR, '.diary-manager-graph-task-list button[value="' + str(self.ready) + '"]'), [])
