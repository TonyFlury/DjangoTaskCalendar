from unittest.mock import Mock, patch

from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.db import OperationalError
from django.test import SimpleTestCase, TestCase, override_settings

from Diary.roles import access_groups, task_owner_roles, validate_task_owner_roles


# Verifies DV1-047: Simple V1 access settings.
# Verifies DV1-014: Startup access-group validation.
@override_settings(DIARY_MANAGER='CustomManager', DIARY_USER='CustomUser')
class AccessGroupConfigurationTests(SimpleTestCase):
    def test_two_group_names_are_sufficient_and_not_shared_mutable_state(self):
        self.assertEqual(access_groups(), {'manager': 'CustomManager', 'user': 'CustomUser'})
        changed = access_groups()
        changed['manager'] = 'Changed'
        self.assertEqual(access_groups()['manager'], 'CustomManager')

    def test_each_setting_requires_one_nonempty_group_name(self):
        for name in ('DIARY_MANAGER', 'DIARY_USER'):
            for value in (None, '', ' ', ' Role ', ('Role',), ['Role']):
                with self.settings(**{name: value}):
                    with self.assertRaisesMessage(ImproperlyConfigured, name):
                        access_groups()

    def test_startup_validates_both_settings_even_without_ownership_roles(self):
        config = apps.get_app_config('Diary')
        with self.settings(DIARY_TASK_OWNER_ROLES=(), DIARY_USER=None):
            with patch('sys.argv', ['manage.py', 'runserver']):
                with self.assertRaisesMessage(ImproperlyConfigured, 'DIARY_USER'):
                    config.ready()


# Verifies DV1-009: Configured ownership role names and existence checks.
@override_settings(DIARY_TASK_OWNER_ROLES=('ConfiguredRole',))
class RoleConfigurationTests(SimpleTestCase):
    def setUp(self):
        def groups_matching(*, name__in):
            query = Mock()
            query.values_list.return_value = {'ConfiguredRole'} & set(name__in)
            return query

        query_patch = patch('Diary.roles.Group.objects.filter', side_effect=groups_matching)
        self.group_query = query_patch.start()
        self.addCleanup(query_patch.stop)

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

    def test_empty_roles_need_no_database_lookup(self):
        with self.settings(DIARY_TASK_OWNER_ROLES=()):
            validate_task_owner_roles()
        self.group_query.assert_not_called()

    def test_database_failure_has_configuration_context(self):
        with patch('Diary.roles.Group.objects.filter', side_effect=OperationalError('Unavailable')):
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


# Verifies DV1-009: Configured ownership role names and existence checks.
# Verifies DV1-048: Standard Django groups and optional template default.
@override_settings(DIARY_TASK_OWNER_ROLES=('CustomOwner',))
class DjangoGroupDatabaseTests(TestCase):
    def test_database_role_existence_is_required_without_creating_missing_roles(self):
        from django.contrib.auth.models import Group

        with self.assertRaisesMessage(ImproperlyConfigured, 'CustomOwner'):
            validate_task_owner_roles()
        self.assertFalse(Group.objects.filter(name='CustomOwner').exists())
        Group.objects.create(name='CustomOwner')
        validate_task_owner_roles()
