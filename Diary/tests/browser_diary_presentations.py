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
