"""Verify manager diary filters, keyboard controls, and responsive host styles."""
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

from Diary.tests.test_manager_view import ManagerDiaryTests


# DV1-022, DV1-039, DV1-041, DV1-052: Real browser verification on a separate PostgreSQL test database.
@unittest.skipUnless(os.environ.get('DIARY_CHROMEDRIVER'), 'Set DIARY_CHROMEDRIVER for the optional Chrome test.')
@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=(),
                   DIARY_TIME_ZONE='Europe/London', ROOT_URLCONF='Diary.tests.test_manager_view')
class ManagerDiaryBrowserTests(StaticLiveServerTestCase):
    """Reuse manager fixtures to inspect the production UI in Chrome."""

    setUp = ManagerDiaryTests.setUp
    add_task = ManagerDiaryTests.add_task

    def test_manager_filters_and_layout(self):
        """Apply filters with keyboard controls and verify mobile layout and host overrides."""
        options = webdriver.ChromeOptions()
        for argument in ('--headless', '--no-sandbox', '--disable-dev-shm-usage'):
            options.add_argument(argument)
        driver = webdriver.Chrome(service=Service(os.environ['DIARY_CHROMEDRIVER']), options=options)
        wait = WebDriverWait(driver, 10)
        try:
            driver.set_window_size(1280, 1000)
            driver.get(self.live_server_url + '/host-manager/')
            driver.add_cookie({'name': settings.SESSION_COOKIE_NAME,
                               'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'path': '/'})
            driver.get(self.live_server_url + f'/host-manager/?diary_key={self.diary.key}')
            self.assertEqual(len(driver.find_elements(By.CSS_SELECTOR, '.diary-manager-task')), 7)
            history = driver.find_element(By.CSS_SELECTOR, '.diary-manager-filter-include-completed')
            history.send_keys(Keys.SPACE)
            self.assertTrue(history.is_selected())
            driver.find_element(By.CSS_SELECTOR, '.diary-manager-apply').click()
            wait.until(lambda browser: len(browser.find_elements(By.CSS_SELECTOR, '.diary-manager-task')) == 8)
            self.assertTrue(driver.find_element(By.CSS_SELECTOR, '.diary-manager-completion').is_displayed())
            driver.find_element(By.CSS_SELECTOR, '.diary-manager-filter-exclude-non-late').send_keys(Keys.SPACE)
            driver.find_element(By.CSS_SELECTOR, '.diary-manager-apply').click()
            wait.until(lambda browser: len(browser.find_elements(By.CSS_SELECTOR, '.diary-manager-task')) == 2)
            driver.find_element(By.CSS_SELECTOR, '.diary-manager-filter-exclude-blocked').send_keys(Keys.SPACE)
            driver.find_element(By.CSS_SELECTOR, '.diary-manager-apply').click()
            wait.until(lambda browser: len(browser.find_elements(By.CSS_SELECTOR, '.diary-manager-task')) == 1)
            driver.find_element(By.CSS_SELECTOR, '.diary-manager-reset').click()
            wait.until(lambda browser: len(browser.find_elements(By.CSS_SELECTOR, '.diary-manager-task')) == 7)
            driver.execute_script('''
                const style = document.createElement('style');
                style.textContent = '.diary { --diary-accent: rgb(25, 35, 95); } .diary .diary-manager-task-title { font-size: 23px; }';
                document.head.append(style);
            ''')
            self.assertEqual(driver.execute_script(
                'return getComputedStyle(document.querySelector(".diary-manager-heading")).backgroundColor'),
                'rgb(25, 35, 95)')
            self.assertEqual(driver.execute_script(
                'return getComputedStyle(document.querySelector(".diary-manager-task-title")).fontSize'), '23px')
            driver.save_screenshot('/tmp/diary-manager-desktop.png')
            driver.set_window_size(390, 844)
            self.assertTrue(driver.execute_script('return document.documentElement.scrollWidth <= innerWidth'))
            self.assertTrue(driver.find_element(By.CSS_SELECTOR, '.diary-manager-apply').is_displayed())
            self.assertTrue(driver.find_element(By.CSS_SELECTOR, '.diary-manager-reset').is_displayed())
            driver.save_screenshot('/tmp/diary-manager-mobile.png')
        finally:
            driver.quit()
