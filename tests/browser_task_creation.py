"""Make sure DV1-029, DV1-030, and DV1-033 controls operate correctly in Chrome."""
import os
import unittest

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from Diary.models import CalendarEntry, TemplateEntry
from Diary.tests.test_task_creation import TaskCreationFixtures


# DV1-029, DV1-030, DV1-033, DV1-041: Browser checks keep the separate PostgreSQL test database.
@unittest.skipUnless(os.environ.get('DIARY_CHROMEDRIVER'), 'Set DIARY_CHROMEDRIVER for the optional Chrome test.')
@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',),
                   ROOT_URLCONF='Diary.tests.test_task_creation')
class TaskCreationBrowserTests(TaskCreationFixtures, StaticLiveServerTestCase):
    """Make sure personal creation, template addition, keyboard controls, and narrow screens operate correctly."""

    # Include identity tables while limiting transaction cleanup to the tested apps.
    available_apps = sorted({'Diary', 'django.contrib.auth', 'django.contrib.contenttypes',
                             'django.contrib.sessions', get_user_model()._meta.app_config.name})

    def login_browser(self, driver, user):
        """Transfer the test client's authenticated session to the local browser."""
        self.client.force_login(user)
        driver.get(self.live_server_url + self.url())
        driver.delete_all_cookies()
        driver.add_cookie({'name': settings.SESSION_COOKIE_NAME,
                           'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'path': '/'})
        driver.get(self.live_server_url + self.url())

    def test_personal_and_manager_creation_keyboard_mobile_and_overrides(self):
        """Create tasks through visible controls and verify the optional future rule and styling interface."""
        options = webdriver.ChromeOptions()
        for argument in ('--headless', '--no-sandbox', '--disable-dev-shm-usage'):
            options.add_argument(argument)
        driver = webdriver.Chrome(service=Service(os.environ['DIARY_CHROMEDRIVER']), options=options)
        wait = WebDriverWait(driver, 10)
        try:
            driver.set_window_size(1280, 1000)
            self.login_browser(driver, self.user)
            self.assertEqual(driver.find_elements(By.CSS_SELECTOR, '.diary-create-future'), [])
            driver.find_element(By.NAME, 'name').send_keys('Browser personal task')
            driver.execute_script('document.querySelector(".diary-create-field-fixed-date").value = "2027-06-22"')
            driver.find_element(By.CSS_SELECTOR, '.diary-create-save').send_keys(Keys.ENTER)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.diary-create-success')))
            personal = CalendarEntry.objects.get(name='Browser personal task')
            self.assertEqual(personal.person_ref, f'user:{self.user.pk}')
            self.login_browser(driver, self.manager)
            driver.find_element(By.NAME, 'name').send_keys('Browser future task')
            driver.execute_script('document.querySelector(".diary-create-field-fixed-date").value = "2027-06-23"')
            Select(driver.find_element(By.NAME, 'person_ref')).select_by_value(f'user:{self.other.pk}')
            driver.find_element(By.NAME, 'add_to_template').send_keys(Keys.SPACE)
            Select(driver.find_element(By.NAME, 'future-date_kind')).select_by_value('annual')
            driver.find_element(By.NAME, 'future-month').send_keys('7')
            driver.find_element(By.NAME, 'future-day').send_keys('3')
            driver.execute_script('''
                const style = document.createElement('style');
                style.textContent = '.diary { --diary-accent: rgb(30, 50, 100); } .diary .diary-create-label { font-size: 22px; }';
                document.head.append(style);
            ''')
            self.assertEqual(driver.execute_script(
                'return getComputedStyle(document.querySelector(".diary-create-heading")).backgroundColor'), 'rgb(30, 50, 100)')
            self.assertEqual(driver.execute_script(
                'return getComputedStyle(document.querySelector(".diary-create-label")).fontSize'), '22px')
            driver.save_screenshot('/tmp/diary-task-create-desktop.png')
            driver.set_window_size(390, 844)
            self.assertTrue(driver.execute_script('return document.documentElement.scrollWidth <= innerWidth'))
            driver.save_screenshot('/tmp/diary-task-create-mobile.png')
            driver.find_element(By.CSS_SELECTOR, '.diary-create-save').click()
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.diary-create-success')))
            task = CalendarEntry.objects.get(name='Browser future task')
            self.assertTrue(TemplateEntry.objects.filter(entry_key=task.entry_key, version__number=2).exists())
            self.assertEqual(task.person_ref, f'user:{self.other.pk}')
        finally:
            driver.quit()
