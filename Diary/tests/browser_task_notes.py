"""Optional real-browser verification of note history on open and closed tasks."""
import os

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import include, path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from Diary.models import EventCalendar, TaskNote
from Diary.tests.test_task_notes import NoteFixtures
from Diary.urls import urlpatterns as package_patterns
from Diary.views import TaskDetailView


class HostDetail(TaskDetailView):
    def get_diary_keys(self):
        return EventCalendar.objects.values_list('pk', flat=True)


patterns = [path(item.pattern._route, HostDetail.as_view(), name=item.name)
            if item.name in {'task-detail', 'diary-task-detail'} else item for item in package_patterns]
urlpatterns = [path('diary/', include((patterns, 'Diary')))]


@override_settings(ROOT_URLCONF=__name__, DIARY_MANAGER='Planners', DIARY_USER='Participants',
                   DIARY_TASK_OWNER_ROLES=('Helpers',))
class TaskNotesBrowserTests(NoteFixtures, StaticLiveServerTestCase):
    def test_append_notes_before_and_after_completion_and_closure(self):
        options = webdriver.ChromeOptions()
        for argument in ('--headless', '--no-sandbox', '--disable-dev-shm-usage'):
            options.add_argument(argument)
        driver = webdriver.Chrome(service=Service(executable_path=os.environ.get('DIARY_CHROMEDRIVER')), options=options)
        wait = WebDriverWait(driver, 10)
        url = self.live_server_url + f'/diary/diaries/{self.diary.key}/tasks/{self.personal}/'
        try:
            driver.get(self.live_server_url + '/diary/')
            driver.add_cookie({'name': settings.SESSION_COOKIE_NAME,
                               'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'path': '/'})
            driver.get(url)
            driver.find_element(By.CSS_SELECTOR, '.diary-note-form textarea').send_keys('First update\nMore detail')
            driver.find_element(By.CSS_SELECTOR, '.diary-note-submit').click()
            wait.until(lambda browser: len(browser.find_elements(By.CSS_SELECTOR, '.diary-note')) == 1)
            self.assertNotIn('?', driver.current_url)
            self.assertIn('Alice Smith', driver.find_element(By.CSS_SELECTOR, '.diary-task-notes').text)
            self.assertTrue(driver.find_element(By.CSS_SELECTOR, '.diary-note-time').get_attribute('datetime'))
            self.user_diary.complete(entry_key=self.personal, expected_revision=0)
            self.diary.close()
            self.client.force_login(self.manager)
            driver.add_cookie({'name': settings.SESSION_COOKIE_NAME,
                               'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'path': '/'})
            driver.get(url)
            driver.set_window_size(390, 900)
            self.assertTrue(driver.execute_script('return document.documentElement.scrollWidth <= innerWidth'))
            driver.find_element(By.CSS_SELECTOR, '.diary-note-form textarea').send_keys('Manager follow-up')
            driver.find_element(By.CSS_SELECTOR, '.diary-note-submit').click()
            wait.until(lambda browser: len(browser.find_elements(By.CSS_SELECTOR, '.diary-note')) == 2)
            history = driver.find_element(By.CSS_SELECTOR, '.diary-task-notes').text
            self.assertIn('First update', history)
            self.assertIn('Manager follow-up', history)
            self.assertIn('Mary Jones', history)
            self.assertNotIn(self.user.get_username(), history)
            self.assertEqual(TaskNote.objects.count(), 2)
            self.user.delete()
            driver.get(url)
            self.assertIn('deleted user', driver.find_element(By.CSS_SELECTOR, '.diary-task-notes').text)
        finally:
            driver.quit()
