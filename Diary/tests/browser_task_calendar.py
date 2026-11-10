"""DFUT-018: Real browser navigation, busy days, touch layout and task return flow."""
import os
from datetime import date

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.ui import Select

from Diary.tests.test_personal_view import PersonalDiaryFixtures


@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants',
                   DIARY_TASK_OWNER_ROLES=('Helpers', 'Reviewers'), ROOT_URLCONF='Diary.tests.test_task_calendar',
                   DIARY_CALENDAR_WEEK_PREVIEW=2, DIARY_CALENDAR_MONTH_PREVIEW=2)
class TaskCalendarBrowserTests(PersonalDiaryFixtures, StaticLiveServerTestCase):
    def setUp(self):
        super().setUp()
        for index in range(8):
            self.add_task(f'Busy task {index}', date(2027, 6, 20))
        self.scope = override_settings(CALENDAR_TEST_KEYS=tuple(self.keys[:3]))
        self.scope.enable()
        self.addCleanup(self.scope.disable)
        options = webdriver.ChromeOptions()
        for argument in ('--headless', '--no-sandbox', '--disable-dev-shm-usage'):
            options.add_argument(argument)
        if self._testMethodName == 'test_without_javascript_keeps_filters_days_and_help_available':
            options.add_experimental_option('prefs', {'profile.managed_default_content_settings.javascript': 2})
        options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
        self.driver = webdriver.Chrome(service=Service(executable_path=os.environ.get('DIARY_CHROMEDRIVER')), options=options)
        self.addCleanup(self.driver.quit)
        self.wait = WebDriverWait(self.driver, 10, ignored_exceptions=(StaleElementReferenceException,))
        self.driver.set_window_size(1440, 1050)
        self.driver.get(self.live_server_url + '/calendar/')
        self.driver.add_cookie({'name': settings.SESSION_COOKIE_NAME,
                               'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'path': '/'})
        self.driver.get(self.live_server_url + '/calendar/?date=2027-06-20&view=month')

    def test_navigation_day_dialog_mobile_filters_and_return_after_note(self):
        driver = self.driver
        if os.environ.get('DIARY_CALENDAR_MONTH_SCREENSHOT'):
            driver.save_screenshot(os.environ['DIARY_CALENDAR_MONTH_SCREENSHOT'])
        self.assertEqual(len(driver.find_elements(By.CSS_SELECTOR, '.diary-calendar-day')), 35)
        self.assertFalse(driver.find_element(By.CSS_SELECTOR, '.diary-calendar-filters-content').is_displayed())
        day = driver.find_element(By.CSS_SELECTOR, '[data-calendar-date="2027-06-20"]')
        self.assertEqual(len(day.find_elements(By.CSS_SELECTOR, '.diary-calendar-task')), 2)
        day.find_element(By.CSS_SELECTOR, '.diary-calendar-more').click()
        self.wait.until(lambda browser: browser.find_element(By.CSS_SELECTOR, '.diary-calendar-task-day-dialog').get_attribute('open'))
        driver.find_element(By.CSS_SELECTOR, '.diary-calendar-day-panel').find_element(By.LINK_TEXT, 'My ready task').click()
        self.wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-detail-heading'))
        self.assertTrue(driver.find_element(By.CSS_SELECTOR, '.diary-calendar-return').is_displayed())
        driver.find_element(By.NAME, 'text').send_keys('Calendar task note')
        driver.find_element(By.CSS_SELECTOR, '.diary-note-submit').click()
        self.wait.until(lambda browser: 'Calendar task note' in browser.find_element(By.TAG_NAME, 'body').text)
        driver.find_element(By.CSS_SELECTOR, '.diary-calendar-return').click()
        self.wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-calendar-day-panel'))
        driver.find_element(By.CSS_SELECTOR, '[data-calendar-close-link]').click()
        self.wait.until(lambda browser: not browser.find_elements(By.CSS_SELECTOR, '.diary-calendar-day-panel'))
        driver.find_element(By.LINK_TEXT, 'Week').click()
        self.wait.until(lambda browser: len(browser.find_elements(By.CSS_SELECTOR, '.diary-calendar-day')) == 7)
        driver.set_window_size(390, 900)
        self.assertTrue(driver.execute_script('return document.documentElement.scrollWidth <= innerWidth'))
        self.assertEqual(driver.execute_script('return getComputedStyle(document.querySelector(".diary-calendar-grid")).gridTemplateColumns.split(" ").length'), 1)
        driver.find_element(By.CSS_SELECTOR, '.diary-calendar-filters-open').click()
        query = driver.find_element(By.NAME, 'query')
        query.send_keys('Busy task 1')
        driver.find_element(By.CSS_SELECTOR, '.diary-calendar-filter-form button[type="submit"]').click()
        self.wait.until(lambda browser: '1 matching tasks' in browser.find_element(By.CSS_SELECTOR, '.diary-calendar-summary').text)
        driver.find_element(By.CSS_SELECTOR, '.diary-calendar-help-open').click()
        self.assertIn('Task-relative dates stay fixed', driver.find_element(By.CSS_SELECTOR, '#diary-calendar-help-dialog').text)
        driver.find_element(By.CSS_SELECTOR, '#diary-calendar-help-dialog [data-calendar-close]').send_keys(Keys.ESCAPE)
        self.assertFalse(driver.find_element(By.CSS_SELECTOR, '#diary-calendar-help-dialog').get_attribute('open'))
        if os.environ.get('DIARY_CALENDAR_SCREENSHOT'):
            driver.save_screenshot(os.environ['DIARY_CALENDAR_SCREENSHOT'])
        self.assertEqual([item for item in driver.get_log('browser') if item['source'] == 'javascript' and item['level'] == 'SEVERE'], [])

    def test_manager_owner_selection_uses_visible_names(self):
        driver = self.driver
        self.client.force_login(self.manager)
        driver.add_cookie({'name': settings.SESSION_COOKIE_NAME,
                           'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'path': '/'})
        driver.get(self.live_server_url + '/calendar/?view=month&date=2027-06-20&mode=manager&diary_key=' + str(self.keys[0]))
        driver.find_element(By.CSS_SELECTOR, '.diary-calendar-filters-open').click()
        owners = Select(driver.find_element(By.NAME, 'owner'))
        owners.select_by_visible_text('Helpers')
        driver.find_element(By.CSS_SELECTOR, '.diary-calendar-filter-form button[type="submit"]').click()
        self.wait.until(lambda browser: '1 matching tasks' in browser.find_element(By.CSS_SELECTOR, '.diary-calendar-summary').text)
        self.assertEqual([item.text for item in driver.find_elements(By.CSS_SELECTOR, '.diary-calendar-owner')], ['Helpers'])
        driver.set_window_size(390, 900)
        self.assertTrue(driver.execute_script('return document.documentElement.scrollWidth <= innerWidth'))

    def test_without_javascript_keeps_filters_days_and_help_available(self):
        driver = self.driver
        self.assertTrue(driver.find_element(By.CSS_SELECTOR, '.diary-calendar-filters-content').is_displayed())
        self.assertTrue(driver.find_element(By.CSS_SELECTOR, '.diary-calendar-help-content').is_displayed())
        driver.find_element(By.CSS_SELECTOR, '[data-calendar-date="2027-06-20"] .diary-calendar-more').click()
        self.wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-calendar-day-panel'))
        self.assertTrue(driver.find_element(By.CSS_SELECTOR, '.diary-calendar-day-panel').is_displayed())
        self.assertFalse(driver.find_element(By.CSS_SELECTOR, '.diary-calendar-task-day-dialog').get_attribute('open'))
