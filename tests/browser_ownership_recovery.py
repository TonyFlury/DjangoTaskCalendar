"""DV1-040: Verify ownership recovery through the existing manager list and task editor in Chrome."""
import os
import unittest
from datetime import date

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait

from Diary.tests.test_ownership_recovery import OwnershipRecoveryTests
from Diary.tests.test_task_creation import TaskCreationFixtures


@unittest.skipUnless(os.environ.get('DIARY_CHROMEDRIVER'), 'Set DIARY_CHROMEDRIVER for Chrome verification.')
@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',),
                   ROOT_URLCONF='Diary.tests.test_task_editing')
class OwnershipRecoveryBrowserTests(TaskCreationFixtures, StaticLiveServerTestCase):
    """Check orphan ordering, existing edit navigation, replacement controls, and narrow-screen layout."""

    def setUp(self):
        """Create the diary and supply trusted scope for the existing manager and detail routes."""
        super().setUp()
        scope = override_settings(EDIT_TEST_KEYS=(self.diary.key,))
        scope.enable()
        self.addCleanup(scope.disable)
        self.client.force_login(self.manager)
        self.url = f'/host/manager/?diary_key={self.diary.key}'
    orphan = OwnershipRecoveryTests.orphan

    def test_existing_editor_reassigns_orphaned_template_task(self):
        """Keep orphaned tasks first and save a whole-team replacement through the normal editor."""
        entry = self.orphan()
        entry.due_date_override = date(2030, 1, 1)
        entry.save()
        options = webdriver.ChromeOptions()
        for argument in ('--headless', '--no-sandbox', '--disable-dev-shm-usage'):
            options.add_argument(argument)
        driver = webdriver.Chrome(service=Service(os.environ['DIARY_CHROMEDRIVER']), options=options)
        wait = WebDriverWait(driver, 10)
        try:
            driver.get(self.live_server_url + self.url)
            driver.add_cookie({'name': settings.SESSION_COOKIE_NAME,
                'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'path': '/'})
            driver.get(self.live_server_url + self.url)
            first = driver.find_element(By.CSS_SELECTOR, '.diary-manager-task')
            self.assertIn('Orphaned template task', first.text)
            first.find_element(By.CSS_SELECTOR, '.diary-task-detail-link').click()
            wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-recovery-form'))
            people = Select(driver.find_element(By.CSS_SELECTOR, '.diary-recovery-person-ref'))
            self.assertNotIn(f'user:{self.manager.pk}', [option.get_attribute('value') for option in people.options])
            driver.set_window_size(390, 844)
            self.assertTrue(driver.execute_script('return document.documentElement.scrollWidth <= innerWidth'))
            Select(driver.find_element(By.CSS_SELECTOR, '.diary-recovery-owner-kind')).select_by_value('team')
            driver.find_element(By.CSS_SELECTOR, '.diary-recovery-submit').click()
            wait.until(lambda browser: not browser.find_elements(By.CSS_SELECTOR, '.diary-recovery-form'))
            self.assertIn('Whole team', driver.find_element(By.CSS_SELECTOR, '.diary-detail-owner').text)
        finally:
            driver.quit()
