"""Verify request-time validation, failure recovery, and concurrent first requests."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from Diary.middleware import DiaryConfigurationMiddleware


class DiaryConfigurationMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.access_patch = patch('Diary.middleware.validate_access_groups')
        self.owners_patch = patch('Diary.middleware.validate_task_owner_roles')
        self.access = self.access_patch.start()
        self.owners = self.owners_patch.start()
        self.addCleanup(self.access_patch.stop)
        self.addCleanup(self.owners_patch.stop)
        self.response = Mock(return_value='response')
        self.middleware = DiaryConfigurationMiddleware(self.response)

    def test_construction_does_not_validate(self):
        self.access.assert_not_called()
        self.owners.assert_not_called()

    def test_success_validates_only_once_and_passes_requests_through(self):
        requests = [object(), object()]
        for request in requests:
            self.assertEqual(self.middleware(request), 'response')
        self.access.assert_called_once_with()
        self.owners.assert_called_once_with()
        self.assertEqual([call.args[0] for call in self.response.call_args_list], requests)

    def test_failure_blocks_request_and_retries_both_checks(self):
        for validator in (self.access, self.owners):
            with self.subTest(validator=validator):
                middleware = DiaryConfigurationMiddleware(self.response)
                validator.side_effect = ImproperlyConfigured('Invalid groups')
                with self.assertRaisesMessage(ImproperlyConfigured, 'Invalid groups'):
                    middleware(object())
                self.response.assert_not_called()
                validator.side_effect = None
                self.access.reset_mock()
                self.owners.reset_mock()
                self.assertEqual(middleware(object()), 'response')
                self.access.assert_called_once_with()
                self.owners.assert_called_once_with()
                self.response.reset_mock()

    def test_new_worker_instance_validates_again(self):
        self.middleware(object())
        DiaryConfigurationMiddleware(self.response)(object())
        self.assertEqual(self.access.call_count, 2)
        self.assertEqual(self.owners.call_count, 2)

    def test_concurrent_first_requests_wait_for_one_validation(self):
        entered = Event()
        release = Event()

        def validate():
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError('Test did not release validation')

        self.access.side_effect = validate
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.middleware, object())
            try:
                self.assertTrue(entered.wait(timeout=5))
                second = pool.submit(self.middleware, object())
                self.response.assert_not_called()
            finally:
                release.set()
            self.assertEqual(first.result(timeout=5), 'response')
            self.assertEqual(second.result(timeout=5), 'response')
        self.access.assert_called_once_with()
        self.owners.assert_called_once_with()
