"""Verify personal task filters, scope, mobile layout, and keyboard operation in Chrome."""
import os
import unittest

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from Diary.tests.test_personal_view import PersonalDiaryFixtures


# DV1-021, DV1-031, DV1-041, DV1-049: Personal UI verification with a separate PostgreSQL test database.
@unittest.skipUnless(os.environ.get('DIARY_CHROMEDRIVER'), 'Set DIARY_CHROMEDRIVER for the optional Chrome test.')
@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers', 'Reviewers'),
                   DIARY_TIME_ZONE='Europe/London', ROOT_URLCONF='Diary.tests.test_personal_view')
class PersonalDiaryBrowserTests(PersonalDiaryFixtures, StaticLiveServerTestCase):
    """Exercise the production personal view through a trusted host route."""

    def test_personal_filters_keyboard_and_layout(self):
        """Use checkboxes and status links while retaining task privacy and responsive layout."""
        options = webdriver.ChromeOptions()
        for argument in ('--headless', '--no-sandbox', '--disable-dev-shm-usage'):
            options.add_argument(argument)
        driver = webdriver.Chrome(service=Service(os.environ['DIARY_CHROMEDRIVER']), options=options)
        wait = WebDriverWait(driver, 10)
        try:
            driver.set_window_size(1280, 1000)
            driver.get(self.live_server_url + '/host-personal/')
            driver.add_cookie({'name': settings.SESSION_COOKIE_NAME,
                               'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'path': '/'})
            driver.get(self.live_server_url + '/host-personal/')
            self.assertEqual(len(driver.find_elements(By.CSS_SELECTOR, '.diary-task')), 6)
            driver.find_element(By.CSS_SELECTOR, '.diary-personal-filter-show-blocked').send_keys(Keys.SPACE)
            driver.find_element(By.CSS_SELECTOR, '.diary-personal-apply').click()
            wait.until(lambda browser: len(browser.find_elements(By.CSS_SELECTOR, '.diary-task')) == 8)
            self.assertNotIn('Private blocker', driver.find_element(By.CSS_SELECTOR, '.diary-personal').text)
            driver.find_element(By.CSS_SELECTOR, '.diary-personal-filter-include-whole-team').send_keys(Keys.SPACE)
            driver.find_element(By.CSS_SELECTOR, '.diary-personal-apply').click()
            wait.until(lambda browser: len(browser.find_elements(By.CSS_SELECTOR, '.diary-task')) == 9)
            driver.find_element(By.CSS_SELECTOR, '.diary-personal-status-late').click()
            wait.until(lambda browser: len(browser.find_elements(By.CSS_SELECTOR, '.diary-task')) == 2)
            self.assertEqual(len(driver.find_elements(By.CSS_SELECTOR, '.diary-task-late')), 2)
            driver.find_element(By.CSS_SELECTOR, '.diary-personal-reset').click()
            wait.until(lambda browser: len(browser.find_elements(By.CSS_SELECTOR, '.diary-task')) == 6)
            driver.execute_script('''
                const style = document.createElement('style');
                style.textContent = '.diary { --diary-accent: rgb(30, 50, 100); } .diary .diary-task-title { font-size: 22px; }';
                document.head.append(style);
            ''')
            self.assertEqual(driver.execute_script(
                'return getComputedStyle(document.querySelector(".diary-personal-heading")).backgroundColor'),
                'rgb(30, 50, 100)')
            self.assertEqual(driver.execute_script(
                'return getComputedStyle(document.querySelector(".diary-task-title")).fontSize'), '22px')
            driver.save_screenshot('/tmp/diary-personal-desktop.png')
            driver.set_window_size(390, 844)
            self.assertTrue(driver.execute_script('return document.documentElement.scrollWidth <= innerWidth'))
            self.assertTrue(driver.find_element(By.CSS_SELECTOR, '.diary-personal-apply').is_displayed())
            driver.save_screenshot('/tmp/diary-personal-mobile.png')
        finally:
            driver.quit()
