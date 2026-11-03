"""Optional Chrome checks for the production template editor.
Run this module explicitly with Django's test command and a separate PostgreSQL test database.
"""
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait

from Diary.models import CalendarTemplate, TemplateEntry, TemplateVersion


@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',))
class EditorBrowserTests(StaticLiveServerTestCase):
    """Verify browser task addition, dependency exclusions, warnings, and revision saves."""

    # Verifies DV1-017: Empty-group warnings during template editing.
    # Verifies DV1-025: Template authoring interface.
    # Verifies DV1-027: Safe template predecessor editor.
    # Verifies DV1-041: Complete pages, fragments, and styling interface.
    # Partial DV1-044: Regression and concurrency verification.
    def test_editor(self):
        """Save a complete template through the real browser and inspect narrow layout."""
        model = get_user_model()
        manager = model.objects.create_user(**{model.USERNAME_FIELD: 'browser@example.test'})
        manager.groups.add(Group.objects.create(name='Planners'))
        Group.objects.create(name='Participants')
        Group.objects.create(name='Helpers')
        self.client.force_login(manager)
        options = webdriver.ChromeOptions()
        for argument in ('--headless', '--no-sandbox', '--disable-dev-shm-usage'):
            options.add_argument(argument)
        options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
        driver = webdriver.Chrome(service=Service(executable_path=os.environ.get('DIARY_CHROMEDRIVER')), options=options)
        wait = WebDriverWait(driver, 10)
        try:
            driver.set_window_size(1400, 1100)
            driver.get(self.live_server_url + '/diary/templates/')
            driver.add_cookie({'name': settings.SESSION_COOKIE_NAME,
                               'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'path': '/'})
            driver.get(self.live_server_url + '/diary/templates/new/')
            driver.find_element(By.CSS_SELECTOR, '.diary-template-metadata .diary-template-field-name').send_keys('Browser template')
            driver.find_element(By.CSS_SELECTOR, '.diary-template-add').click()
            rows = driver.find_elements(By.CSS_SELECTOR, '.diary-template-task-list .diary-template-task')
            self.assertEqual(len(rows), 1)
            first = rows[0]
            first.find_element(By.CSS_SELECTOR, '.diary-template-field-name').send_keys('Prepare')
            first.find_element(By.CSS_SELECTOR, '.diary-template-field-milestone-name').send_keys('target')
            Select(first.find_element(By.CSS_SELECTOR, '.diary-template-field-date-kind')).select_by_value('relative')
            first.find_element(By.CSS_SELECTOR, '.diary-template-field-day-offset').send_keys('-7')
            driver.find_element(By.CSS_SELECTOR, '.diary-template-add').click()
            second = driver.find_elements(By.CSS_SELECTOR, '.diary-template-task-list .diary-template-task')[1]
            second.find_element(By.CSS_SELECTOR, '.diary-template-field-name').send_keys('Review')
            Select(second.find_element(By.CSS_SELECTOR, '.diary-template-field-date-kind')).select_by_value('annual')
            second.find_element(By.CSS_SELECTOR, '.diary-template-field-month').send_keys('6')
            second.find_element(By.CSS_SELECTOR, '.diary-template-field-day').send_keys('1')
            Select(second.find_element(By.CSS_SELECTOR, '.diary-template-field-owner-kind')).select_by_value('role')
            Select(second.find_element(By.CSS_SELECTOR, '.diary-template-field-role-ref')).select_by_value('Helpers')
            wait.until(lambda browser: 'No role members' in second.find_element(By.CSS_SELECTOR, '.diary-template-owner-warning').text)
            first_key = first.find_element(By.CSS_SELECTOR, '.diary-template-field-entry-key').get_attribute('value')
            Select(second.find_element(By.CSS_SELECTOR, '.diary-template-field-predecessors')).select_by_value(first_key)
            self.assertEqual(len(Select(first.find_element(By.CSS_SELECTOR, '.diary-template-field-predecessors')).options), 0)
            search = second.find_element(By.CSS_SELECTOR, '.diary-template-predecessor-search')
            search.send_keys('No matching task')
            self.assertEqual(len(Select(second.find_element(By.CSS_SELECTOR, '.diary-template-field-predecessors')).all_selected_options), 1)
            search.clear()
            search.send_keys('Prepare')
            driver.set_window_size(390, 900)
            self.assertTrue(driver.execute_script('return document.documentElement.scrollWidth <= innerWidth'))
            driver.find_element(By.CSS_SELECTOR, '.diary-template-save').click()
            wait.until(lambda browser: '/templates/edit/' in browser.current_url)
            self.assertEqual(TemplateVersion.objects.get().status, 'approved')
            self.assertEqual(TemplateEntry.objects.count(), 2)
            self.assertEqual(TemplateEntry.objects.get(name='Review').predecessors.get().name, 'Prepare')
            rows = driver.find_elements(By.CSS_SELECTOR, '.diary-template-task-list .diary-template-task')
            rows[1].find_element(By.CSS_SELECTOR, '.diary-template-remove').click()
            self.assertIn('diary-template-task-deleted', rows[1].get_attribute('class'))
            rows[1].find_element(By.CSS_SELECTOR, '.diary-template-remove').click()
            self.assertNotIn('diary-template-task-deleted', rows[1].get_attribute('class'))
            rows[1].find_element(By.CSS_SELECTOR, '.diary-template-remove').click()
            driver.find_element(By.CSS_SELECTOR, '.diary-template-save').click()
            wait.until(lambda browser: 'Version 2' in browser.find_element(By.CSS_SELECTOR, '.diary-template-version').text)
            self.assertEqual(TemplateVersion.objects.count(), 2)
            self.assertEqual(TemplateVersion.objects.order_by('-number').first().entries.count(), 1)
            self.assertEqual(CalendarTemplate.objects.count(), 1)

            # A successful browser workflow must not leave JavaScript errors.
            errors = [item for item in driver.get_log('browser') if item['source'] == 'javascript' and item['level'] == 'SEVERE']
            self.assertEqual(errors, [])
        finally:
            driver.quit()
