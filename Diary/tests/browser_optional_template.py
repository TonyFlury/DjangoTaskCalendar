"""Optional Chrome verification of personal work followed by template application."""
import os

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import include, path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait

from Diary.models import CalendarEntry, EventCalendar
from Diary.tests.test_optional_template import OptionalTemplateFixtures
from Diary.urls import urlpatterns as package_patterns
from Diary.views import ManagerDiaryView, PersonalDiaryView, TaskCreateView, TaskDetailView, TemplateApplyView


class HostScope:
    def get_diary_keys(self):
        return EventCalendar.objects.filter(event_ref='empty:1').values_list('pk', flat=True)


class HostPersonal(HostScope, PersonalDiaryView):
    pass


class HostManager(HostScope, ManagerDiaryView):
    pass


class HostCreate(HostScope, TaskCreateView):
    pass


class HostDetail(HostScope, TaskDetailView):
    pass


class HostApply(HostScope, TemplateApplyView):
    pass


replacements = {'diary-personal': HostPersonal, 'diary-manager': HostManager,
                'diary-task-create': HostCreate, 'diary-task-detail': HostDetail, 'diary-template-apply': HostApply,
                'personal-diary': HostPersonal, 'manager-diary': HostManager, 'task-create': HostCreate,
                'task-detail': HostDetail, 'template-apply': HostApply}
host_patterns = [path(item.pattern._route, replacements[item.name].as_view(), name=item.name)
                 if item.name in replacements else item for item in package_patterns]
urlpatterns = [path('diary/', include((host_patterns, 'Diary')))]


@override_settings(ROOT_URLCONF=__name__, DIARY_MANAGER='Planners', DIARY_USER='Participants',
                   DIARY_TASK_OWNER_ROLES=('Helpers',))
class OptionalTemplateBrowserTests(OptionalTemplateFixtures, StaticLiveServerTestCase):
    def test_personal_task_then_manager_application(self):
        options = webdriver.ChromeOptions()
        for argument in ('--headless', '--no-sandbox', '--disable-dev-shm-usage'):
            options.add_argument(argument)
        driver = webdriver.Chrome(service=Service(executable_path=os.environ.get('DIARY_CHROMEDRIVER')), options=options)
        wait = WebDriverWait(driver, 10)
        try:
            driver.get(self.live_server_url + '/diary/')
            driver.add_cookie({'name': settings.SESSION_COOKIE_NAME,
                               'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'path': '/'})
            driver.get(self.live_server_url + '/diary/?diary_key=' + str(self.empty.key))
            self.assertNotIn('does not exist', driver.find_element(By.TAG_NAME, 'body').text)
            driver.find_element(By.CSS_SELECTOR, '.diary-create-link').click()
            driver.find_element(By.CSS_SELECTOR, '.diary-create-field-name').send_keys('Prepare')
            self.assertEqual(driver.find_elements(By.CSS_SELECTOR, '.diary-create-future'), [])
            driver.execute_script("document.querySelector('[name=fixed_date]').value = '2027-06-01'")
            driver.find_element(By.CSS_SELECTOR, '.diary-create-form button[type=submit]').click()
            wait.until(lambda browser: browser.find_elements(By.CSS_SELECTOR, '.diary-create-success'))
            before = list(CalendarEntry.objects.filter(calendar_id=self.empty.key, source_entry=None).values())
            self.assertEqual(len(before), 1)
            self.client.force_login(self.manager)
            driver.add_cookie({'name': settings.SESSION_COOKIE_NAME,
                               'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'path': '/'})
            driver.get(self.live_server_url + '/diary/manager/?diary_key=' + str(self.empty.key))
            driver.find_element(By.CSS_SELECTOR, '.diary-apply-template-link').click()
            Select(driver.find_element(By.NAME, 'template_version_key')).select_by_value(str(self.version.key))
            driver.find_element(By.CSS_SELECTOR, '.diary-apply-selection button').click()
            driver.set_window_size(390, 900)
            self.assertTrue(driver.execute_script('return document.documentElement.scrollWidth <= innerWidth'))
            driver.execute_script("document.querySelector('[name=milestone_target]').value = '2027-06-20'")
            driver.find_element(By.CSS_SELECTOR, '.diary-apply-form button').click()
            wait.until(lambda browser: '/manager/' in browser.current_url)
            self.assertIn('Prepare (template)', driver.find_element(By.TAG_NAME, 'body').text)
            self.assertEqual(CalendarEntry.objects.filter(calendar_id=self.empty.key).count(), 3)
            self.assertEqual(list(CalendarEntry.objects.filter(calendar_id=self.empty.key, source_entry=None).values()), before)
        finally:
            driver.quit()
