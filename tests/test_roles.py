from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.db import OperationalError
from django.test import SimpleTestCase, TestCase, override_settings

from Diary.roles import task_owner_roles, validate_task_owner_roles


def existing_roles(names):
    return {'ConfiguredRole'} & names


@override_settings(DIARY_TASK_OWNER_ROLES=('ConfiguredRole',),
                   DIARY_ROLE_LOOKUP='Diary.tests.test_roles.existing_roles')
class RoleConfigurationTests(SimpleTestCase):
    def test_configured_roles_validate_without_project_specific_names(self):
        self.assertEqual(task_owner_roles(), frozenset({'ConfiguredRole'}))
        validate_task_owner_roles()

    def test_missing_roles_have_an_actionable_configuration_error(self):
        with self.settings(DIARY_TASK_OWNER_ROLES=('MissingB', 'ConfiguredRole', 'MissingA')):
            with self.assertRaisesMessage(ImproperlyConfigured, 'MissingA, MissingB'):
                validate_task_owner_roles()

    def test_invalid_settings_are_configuration_errors(self):
        for roles in ('ConfiguredRole', (None,), ('',), (' Role ',), {'Role': True}):
            with self.settings(DIARY_TASK_OWNER_ROLES=roles):
                with self.assertRaisesMessage(ImproperlyConfigured, 'DIARY_TASK_OWNER_ROLES'):
                    validate_task_owner_roles()
        for lookup in ('', None, 'missing.path.lookup', 'Diary.roles.settings'):
            with self.settings(DIARY_ROLE_LOOKUP=lookup):
                with self.assertRaisesMessage(ImproperlyConfigured, 'DIARY_ROLE_LOOKUP'):
                    validate_task_owner_roles()

    def test_empty_roles_need_no_database_lookup(self):
        with self.settings(DIARY_TASK_OWNER_ROLES=(), DIARY_ROLE_LOOKUP=''):
            validate_task_owner_roles()

    def test_database_failure_has_configuration_context(self):
        with patch(__name__ + '.existing_roles', side_effect=OperationalError('Unavailable')):
            with self.assertRaisesMessage(ImproperlyConfigured, 'Check the database connection'):
                validate_task_owner_roles()

    def test_startup_checks_roles_but_allows_database_bootstrap(self):
        config = apps.get_app_config('Diary')
        with patch('sys.argv', ['manage.py', 'runserver']):
            with self.settings(DIARY_TASK_OWNER_ROLES=('MissingRole',)):
                with self.assertRaisesMessage(ImproperlyConfigured, 'MissingRole'):
                    config.ready()
        for command in ('migrate', 'sync_access_policy'):
            with patch('sys.argv', ['manage.py', command]):
                with patch('Diary.roles.validate_task_owner_roles') as validate:
                    config.ready()
                    validate.assert_not_called()


@skipUnless(apps.is_installed('django.contrib.auth'), 'Requires the host Django group database.')
@override_settings(DIARY_TASK_OWNER_ROLES=('CustomOwner',),
                   DIARY_ROLE_LOOKUP='GarageSale.diary_roles.existing_task_owner_roles')
class HostRoleDatabaseTests(TestCase):
    def test_database_role_existence_is_required_without_creating_missing_roles(self):
        from django.contrib.auth.models import Group

        with self.assertRaisesMessage(ImproperlyConfigured, 'CustomOwner'):
            validate_task_owner_roles()
        self.assertFalse(Group.objects.filter(name='CustomOwner').exists())
        Group.objects.create(name='CustomOwner')
        validate_task_owner_roles()
