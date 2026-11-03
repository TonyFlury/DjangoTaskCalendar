"""Make sure task date editing and completion controls operate correctly in Chrome."""
import os
import unittest
from datetime import date

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from Diary.models import CalendarEntry
from Diary.tests.test_task_editing import TaskEditingFixtures


# DV1-023, DV1-032, DV1-035, DV1-036, DV1-037, DV1-038, DV1-039, DV1-041: Chrome uses a separate PostgreSQL test database.
@unittest.skipUnless(os.environ.get('DIARY_CHROMEDRIVER'), 'Set DIARY_CHROMEDRIVER for the optional Chrome test.')
@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',),
                   ROOT_URLCONF='Diary.tests.test_task_editing')
class TaskEditingBrowserTests(TaskEditingFixtures, StaticLiveServerTestCase):
    """Make sure personal edits, manager date edits, blockers, completion, keyboard controls, and narrow screens operate correctly."""

    # Cleanup includes identity tables without requiring unrelated host business tables.
    available_apps = sorted({'Diary', 'django.contrib.auth', 'django.contrib.contenttypes',
                             'django.contrib.sessions', get_user_model()._meta.app_config.name})

    def login_browser(self, driver, user, path):
        """Use the test client's authenticated session on the local browser test server."""
        self.client.force_login(user)
        driver.get(self.live_server_url + path)
        driver.delete_all_cookies()
        driver.add_cookie({'name': settings.SESSION_COOKIE_NAME,
                           'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'path': '/'})
        driver.get(self.live_server_url + path)

    def test_personal_dates_manager_template_dates_completion_and_layout(self):
        """Follow scoped list links, save dates, complete tasks, and inspect forced-completion history."""
        options = webdriver.ChromeOptions()
        for argument in ('--headless', '--no-sandbox', '--disable-dev-shm-usage'):
            options.add_argument(argument)
        driver = webdriver.Chrome(service=Service(os.environ['DIARY_CHROMEDRIVER']), options=options)
        wait = WebDriverWait(driver, 10)
        try:
            driver.set_window_size(1280, 1000)
            self.login_browser(driver, self.user, reverse('host-edit-personal'))
            driver.find_element(By.CSS_SELECTOR, '.diary-task-detail-link').click()
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.diary-detail-due-date')))
            driver.execute_script('document.querySelector(".diary-detail-due-date").value = "2027-07-02"')
            driver.find_element(By.CSS_SELECTOR, '.diary-detail-save-date').send_keys(Keys.ENTER)
            wait.until(EC.text_to_be_present_in_element((By.CSS_SELECTOR, '.diary-detail-date'), '2 July 2027'))
            driver.find_element(By.CSS_SELECTOR, '.diary-detail-complete').send_keys(Keys.ENTER)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.diary-detail-history')))
            self.assertIn('2 July 2027', driver.find_element(By.CSS_SELECTOR, '.diary-detail-completion-due').text)
            self.assertEqual(driver.find_elements(By.CSS_SELECTOR, '.diary-detail-save-date'), [])
            self.login_browser(driver, self.manager, self.task_url(self.second.entry_key))
            self.assertIn('Prepare', driver.find_element(By.CSS_SELECTOR, '.diary-detail-blockers').text)
            self.assertEqual(driver.execute_script(
                'return getComputedStyle(document.querySelector(".diary-detail-task")).borderTopStyle'), 'dashed')
            self.assertIn('does not warn managers', driver.find_element(By.CSS_SELECTOR, '.diary-detail-date-limit').text)
            driver.execute_script('document.querySelector(".diary-detail-due-date").value = "2027-08-03"')
            driver.find_element(By.CSS_SELECTOR, '.diary-detail-save-date').click()
            wait.until(EC.text_to_be_present_in_element((By.CSS_SELECTOR, '.diary-detail-date'), '3 August 2027'))
            self.diary.update_due_date(entry_key=self.first.entry_key, due_date=date(2020, 1, 1), expected_revision=0)
            driver.refresh()
            self.assertEqual(driver.execute_script(
                'return getComputedStyle(document.querySelector(".diary-detail-task")).borderTopColor'), 'rgb(148, 96, 0)')
            self.diary.update_due_date(entry_key=self.second.entry_key, due_date=date(2020, 1, 2), expected_revision=1)
            driver.refresh()
            self.assertEqual(driver.execute_script(
                'return getComputedStyle(document.querySelector(".diary-detail-task")).borderTopColor'), 'rgb(163, 21, 21)')
            self.diary.update_due_date(entry_key=self.second.entry_key, due_date=date(2027, 8, 3), expected_revision=2)
            driver.refresh()
            driver.execute_script('''
                const style = document.createElement('style');
                style.textContent = '.diary { --diary-accent: rgb(30, 50, 100); } .diary .diary-detail-name { font-size: 22px; }';
                document.head.append(style);
            ''')
            self.assertEqual(driver.execute_script(
                'return getComputedStyle(document.querySelector(".diary-detail-heading")).backgroundColor'), 'rgb(30, 50, 100)')
            self.assertEqual(driver.execute_script(
                'return getComputedStyle(document.querySelector(".diary-detail-name")).fontSize'), '22px')
            driver.save_screenshot('/tmp/diary-task-detail-desktop.png')
            driver.set_window_size(390, 844)
            self.assertTrue(driver.execute_script('return document.documentElement.scrollWidth <= innerWidth'))
            driver.save_screenshot('/tmp/diary-task-detail-mobile.png')
            driver.find_element(By.CSS_SELECTOR, '.diary-detail-close-all').click()
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.diary-detail-history')))
            driver.get(self.live_server_url + self.task_url(self.first.entry_key))
            self.assertIn('Close all', driver.find_element(By.CSS_SELECTOR, '.diary-detail-completion-comment').text)
            first = CalendarEntry.objects.get(calendar_id=self.diary.key, entry_key=self.first.entry_key)
            second = CalendarEntry.objects.get(calendar_id=self.diary.key, entry_key=self.second.entry_key)
            self.assertEqual(first.completed_at, second.completed_at)
            self.assertEqual(second.completed_due_date.isoformat(), '2027-08-03')
        finally:
            driver.quit()
