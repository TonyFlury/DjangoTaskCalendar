"""Verify configured access groups and ownership-role startup validation."""
from unittest.mock import Mock, patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured
from django.db import OperationalError, connection, transaction
from django.test import SimpleTestCase, TestCase, override_settings

from Diary.roles import access_groups, task_owner_roles, validate_access_groups, validate_task_owner_roles


# Verifies DV1-047: Simple V1 access settings.
# Verifies DV1-014: Startup access-group validation.
@override_settings(DIARY_MANAGER='CustomManager', DIARY_USER='CustomUser')
class AccessGroupConfigurationTests(SimpleTestCase):
    """Verify access setting values without requiring database tables."""

    def test_two_group_names_are_sufficient_and_not_shared_mutable_state(self):
        """Return a fresh mapping for two valid configurable group names."""
        self.assertEqual(access_groups(), {'manager': 'CustomManager', 'user': 'CustomUser'})
        changed = access_groups()
        changed['manager'] = 'Changed'
        self.assertEqual(access_groups()['manager'], 'CustomManager')

    def test_each_setting_requires_one_nonempty_group_name(self):
        """Reject absent, empty, spaced, and collection values for either access setting."""
        for name in ('DIARY_MANAGER', 'DIARY_USER'):
            for value in (None, '', ' ', ' Role ', ('Role',), ['Role']):
                with self.settings(**{name: value}):
                    with self.assertRaisesMessage(ImproperlyConfigured, name):
                        access_groups()

    def test_startup_validates_both_settings_even_without_ownership_roles(self):
        """Validate access settings before any startup database query."""
        config = apps.get_app_config('Diary')
        with self.settings(DIARY_TASK_OWNER_ROLES=(), DIARY_USER=None):
            with patch('sys.argv', ['manage.py', 'runserver']):
                with self.assertRaisesMessage(ImproperlyConfigured, 'DIARY_USER'):
                    config.ready()


# Verifies DV1-009: Configured ownership role names and existence checks.
@override_settings(DIARY_TASK_OWNER_ROLES=('ConfiguredRole',))
class RoleConfigurationTests(SimpleTestCase):
    """Verify ownership-role configuration independently of access-group database checks."""

    def setUp(self):
        """Provide ownership query results and isolate unrelated access-group validation."""
        def groups_matching(*, name__in):
            """Return configured matching ownership names from the fake group directory."""
            query = Mock()
            query.values_list.return_value = {'ConfiguredRole'} & set(name__in)
            return query

        query_patch = patch.object(Group.objects, 'filter', side_effect=groups_matching)
        self.group_query = query_patch.start()
        self.addCleanup(query_patch.stop)
        access_patch = patch('Diary.roles.validate_access_groups')
        access_patch.start()
        self.addCleanup(access_patch.stop)

    def test_configured_roles_validate_without_project_specific_names(self):
        """Accept a populated fake directory without requiring host-specific role names."""
        self.assertEqual(task_owner_roles(), frozenset({'ConfiguredRole'}))
        validate_task_owner_roles()

    def test_missing_roles_have_an_actionable_configuration_error(self):
        """Identify every absent ownership role in a stable error message."""
        with self.settings(DIARY_TASK_OWNER_ROLES=('MissingB', 'ConfiguredRole', 'MissingA')):
            with self.assertRaisesMessage(ImproperlyConfigured, 'MissingA, MissingB'):
                validate_task_owner_roles()

    def test_invalid_settings_are_configuration_errors(self):
        """Reject ownership role settings with invalid types or names."""
        for roles in ('ConfiguredRole', (None,), ('',), (' Role ',), {'Role': True}):
            with self.settings(DIARY_TASK_OWNER_ROLES=roles):
                with self.assertRaisesMessage(ImproperlyConfigured, 'DIARY_TASK_OWNER_ROLES'):
                    validate_task_owner_roles()

    def test_empty_roles_need_no_database_lookup(self):
        """Avoid ownership queries when the configured collection is empty."""
        with self.settings(DIARY_TASK_OWNER_ROLES=()):
            validate_task_owner_roles()
        self.group_query.assert_not_called()

    def test_database_failure_has_configuration_context(self):
        """Convert ownership database failures into useful configuration errors."""
        self.group_query.side_effect = OperationalError('Unavailable')
        with self.assertRaisesMessage(ImproperlyConfigured, 'Check the database connection'):
            validate_task_owner_roles()

    def test_startup_checks_roles_but_allows_database_bootstrap(self):
        """Check ownership roles during normal startup and preserve existing setup commands."""
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
    """Verify ownership role existence against the separate PostgreSQL test database."""

    def test_database_role_existence_is_required_without_creating_missing_roles(self):
        """Reject missing ownership groups without creating them as a validation side effect."""
        with self.assertRaisesMessage(ImproperlyConfigured, 'CustomOwner'):
            validate_task_owner_roles()
        self.assertFalse(Group.objects.filter(name='CustomOwner').exists())
        Group.objects.create(name='CustomOwner')
        validate_task_owner_roles()


# Verifies DV1-014: Startup access-group existence and membership validation.
@override_settings(DIARY_MANAGER='CustomManager', DIARY_USER='CustomUser', DIARY_TASK_OWNER_ROLES=())
class AccessGroupDatabaseTests(TestCase):
    """Verify populated access groups and application startup on PostgreSQL."""

    def setUp(self):
        """Create empty access groups with project-independent names in the test database."""
        self.managers = Group.objects.create(name='CustomManager')
        self.users = Group.objects.create(name='CustomUser')
        self.config = apps.get_app_config('Diary')

    def add_member(self, *groups):
        """Create a member through the configured user model and assign the supplied groups."""
        model = get_user_model()
        identity = f'member-{model._base_manager.count()}@example.test'
        member = model._default_manager.create_user(**{model.USERNAME_FIELD: identity})
        member.groups.add(*groups)
        return member

    def test_populated_groups_validate_with_one_database_query(self):
        """Check both access groups together without changing their memberships."""
        self.assertEqual(connection.vendor, 'postgresql')
        member = self.add_member(self.managers, self.users)
        with self.assertNumQueries(1):
            self.assertIsNone(validate_access_groups())
        self.assertCountEqual(member.groups.values_list('name', flat=True), ['CustomManager', 'CustomUser'])

    def test_missing_and_empty_groups_have_distinct_setting_specific_errors(self):
        """Report a missing user group separately from an empty manager group."""
        self.users.delete()
        group_count = Group.objects.count()
        user_count = get_user_model()._base_manager.count()
        with self.assertRaises(ImproperlyConfigured) as raised:
            validate_access_groups()
        self.assertIn("DIARY_MANAGER references empty group 'CustomManager'", str(raised.exception))
        self.assertIn("DIARY_USER references missing group 'CustomUser'", str(raised.exception))
        self.assertEqual(Group.objects.count(), group_count)
        self.assertEqual(get_user_model()._base_manager.count(), user_count)

    def test_each_access_group_requires_a_member(self):
        """Reject either empty access group even when the other group is populated."""
        member = self.add_member(self.users)
        with self.assertRaisesMessage(ImproperlyConfigured, "DIARY_MANAGER references empty group 'CustomManager'"):
            validate_access_groups()
        member.groups.clear()
        member.groups.add(self.managers)
        with self.assertRaisesMessage(ImproperlyConfigured, "DIARY_USER references empty group 'CustomUser'"):
            validate_access_groups()

    def test_same_populated_group_can_supply_both_access_roles(self):
        """Permit a host to map both access roles to one populated Django group."""
        self.add_member(self.managers)
        with self.settings(DIARY_USER='CustomManager'):
            validate_access_groups()

    def test_unrelated_ownership_members_do_not_populate_access_groups(self):
        """Require access-group membership independently of task ownership group membership."""
        owners = Group.objects.create(name='Owners')
        self.add_member(owners)
        with self.assertRaises(ImproperlyConfigured) as raised:
            validate_access_groups()
        self.assertIn('CustomManager', str(raised.exception))
        self.assertIn('CustomUser', str(raised.exception))

    def test_removing_or_deleting_the_last_member_invalidates_the_group(self):
        """Use current membership rather than a cached result from an earlier validation."""
        manager = self.add_member(self.managers)
        self.add_member(self.users)
        validate_access_groups()
        manager.groups.clear()
        with self.assertRaisesMessage(ImproperlyConfigured, "empty group 'CustomManager'"):
            validate_access_groups()
        manager.groups.add(self.managers)
        validate_access_groups()
        manager.delete()
        with self.assertRaisesMessage(ImproperlyConfigured, "empty group 'CustomManager'"):
            validate_access_groups()

    def test_database_failure_names_settings_and_configured_groups(self):
        """Report database unavailability with the affected configuration and repair guidance."""
        with patch('django.db.models.query.QuerySet._fetch_all', side_effect=OperationalError('Unavailable')):
            with self.assertRaises(ImproperlyConfigured) as raised:
                validate_access_groups()
        message = str(raised.exception)
        for value in ('DIARY_MANAGER', 'DIARY_USER', 'CustomManager', 'CustomUser', 'database connection'):
            self.assertIn(value, message)
        self.assertIsInstance(raised.exception.__cause__, OperationalError)

    def test_unmigrated_tables_have_a_useful_configuration_error(self):
        """Use an isolated PostgreSQL search path to check genuinely unavailable application tables."""
        group_count = Group.objects.count()
        with self.assertRaisesMessage(ImproperlyConfigured, 'Apply migrations'):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('SET LOCAL search_path TO pg_catalog')
                validate_access_groups()
        self.assertEqual(Group.objects.count(), group_count)

    def test_normal_management_and_web_startup_check_access_groups(self):
        """Validate access groups for management commands and WSGI or ASGI startup."""
        arguments = (['manage.py', 'runserver'], ['manage.py', 'check'], ['manage.py', 'collectstatic'], ['server'])
        for argv in arguments:
            with self.subTest(argv=argv), patch('sys.argv', argv):
                with self.assertRaisesMessage(ImproperlyConfigured, 'empty group'):
                    self.config.ready()
        self.add_member(self.managers, self.users)
        for argv in arguments:
            with self.subTest(argv=argv), patch('sys.argv', argv), self.assertNumQueries(1):
                self.config.ready()

    def test_invalid_access_groups_stop_startup_before_ownership_validation(self):
        """Reject invalid access configuration before evaluating independent ownership roles."""
        with patch('sys.argv', ['manage.py', 'runserver']), patch('Diary.roles.validate_task_owner_roles') as owners:
            with self.assertRaisesMessage(ImproperlyConfigured, 'empty group'):
                self.config.ready()
        owners.assert_not_called()

    def test_setup_repair_and_test_commands_do_not_query_application_tables(self):
        """Keep administrative repair and test-database creation usable before group setup."""
        for command in ('migrate', 'sync_access_policy', 'shell', 'createsuperuser', 'loaddata', 'test'):
            with self.subTest(command=command), patch('sys.argv', ['manage.py', command]), self.assertNumQueries(0):
                self.config.ready()

    def test_setup_commands_still_reject_invalid_setting_values(self):
        """Retain setting-value validation even while database checks are deferred for setup."""
        for command in ('migrate', 'shell', 'test'):
            with self.subTest(command=command), patch('sys.argv', ['manage.py', command]):
                with self.settings(DIARY_MANAGER=None), self.assertNumQueries(0):
                    with self.assertRaisesMessage(ImproperlyConfigured, 'DIARY_MANAGER'):
                        self.config.ready()
