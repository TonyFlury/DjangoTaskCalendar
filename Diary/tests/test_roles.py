"""Verify configured access groups and ownership-role startup validation."""
from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError

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
# Verifies DV1-015: Startup ownership-group membership validation.
@override_settings(DIARY_TASK_OWNER_ROLES=('ConfiguredRole',))
class RoleConfigurationTests(SimpleTestCase):
    """Verify ownership-role configuration independently of access-group database checks."""

    def setUp(self):
        """Provide ownership query results and isolate unrelated access-group validation."""
        def groups_matching(*, name__in):
            """Return configured matching ownership names from the fake group directory."""
            query = Mock()
            query.annotate.return_value = query
            query.values_list.return_value = [(name, True) for name in {'ConfiguredRole'} & set(name__in)]
            return query

        query_patch = patch.object(Group.objects, 'filter', side_effect=groups_matching)
        self.group_query = query_patch.start()
        self.addCleanup(query_patch.stop)
        access_patch = patch('Diary.roles.validate_access_groups')
        access_patch.start()
        self.addCleanup(access_patch.stop)
        command_access_patch = patch(
            'Diary.management.commands.validate_diary_configuration.validate_access_groups')
        command_access_patch.start()
        self.addCleanup(command_access_patch.stop)

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

    @override_settings(DIARY_MANAGER='Managers', DIARY_USER='Users')
    def test_startup_never_queries_groups(self):
        """App loading must work before tables and configured groups exist."""
        config = apps.get_app_config('Diary')
        with self.settings(DIARY_TASK_OWNER_ROLES=('MissingRole',)):
            for argv in (['manage.py', 'runserver'], ['server'], ['manage.py', 'migrate']):
                with self.subTest(argv=argv), patch('sys.argv', argv):
                    config.ready()
        self.group_query.assert_not_called()

    def test_validation_command_reports_group_errors(self):
        """Preserve actionable configuration failures as command failures."""
        with self.settings(DIARY_TASK_OWNER_ROLES=('MissingRole',)):
            with self.assertRaisesMessage(CommandError, 'MissingRole'):
                call_command('validate_diary_configuration', stdout=StringIO())

    def test_validation_command_accepts_valid_groups(self):
        output = StringIO()
        call_command('validate_diary_configuration', stdout=output)
        self.assertIn('Diary configuration is valid.', output.getvalue())


# Verifies DV1-009: Configured ownership role names and existence checks.
# Verifies DV1-048: Standard Django groups and optional template default.
# Verifies DV1-015: Startup ownership-group membership validation.
@override_settings(DIARY_TASK_OWNER_ROLES=('CustomOwner',))
class DjangoGroupDatabaseTests(TestCase):
    """Verify ownership role existence against the separate PostgreSQL test database."""

    def test_database_role_existence_is_required_without_creating_missing_roles(self):
        """Reject missing ownership groups without creating them as a validation side effect."""
        with self.assertRaisesMessage(ImproperlyConfigured, 'CustomOwner'):
            validate_task_owner_roles()
        self.assertFalse(Group.objects.filter(name='CustomOwner').exists())
        group = Group.objects.create(name='CustomOwner')
        with self.assertRaisesMessage(ImproperlyConfigured, 'Empty roles with no members: CustomOwner'):
            validate_task_owner_roles()
        model = get_user_model()
        member = model._default_manager.create_user(**{model.USERNAME_FIELD: 'owner@example.test'})
        member.groups.add(group)
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

    def test_management_and_web_startup_do_not_query_groups(self):
        """Even empty groups must not cause database access during app loading."""
        for argv in (['manage.py', 'runserver'], ['manage.py', 'check'],
                     ['manage.py', 'collectstatic'], ['server']):
            with self.subTest(argv=argv), patch('sys.argv', argv), self.assertNumQueries(0):
                self.config.ready()

    def test_validation_command_rejects_invalid_access_groups(self):
        with patch('Diary.management.commands.validate_diary_configuration.validate_task_owner_roles') as owners:
            with self.assertRaisesMessage(CommandError, 'empty group'):
                call_command('validate_diary_configuration', stdout=StringIO())
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


# Verifies DV1-015: Startup ownership-group membership validation.
@override_settings(DIARY_MANAGER='OwnerManagers', DIARY_USER='OwnerUsers',
                   DIARY_TASK_OWNER_ROLES=('FirstOwner', 'SecondOwner'))
class OwnershipGroupMembershipTests(TestCase):
    """Verify ownership-group membership during startup against PostgreSQL."""

    def setUp(self):
        """Create populated access groups and empty ownership groups with configurable names."""
        self.first = Group.objects.create(name='FirstOwner')
        self.second = Group.objects.create(name='SecondOwner')
        managers = Group.objects.create(name='OwnerManagers')
        users = Group.objects.create(name='OwnerUsers')
        model = get_user_model()
        self.member = model._default_manager.create_user(**{model.USERNAME_FIELD: 'ownership-member@example.test'})
        self.member.groups.add(managers, users)
        self.config = apps.get_app_config('Diary')

    def test_populated_roles_validate_in_one_query_without_membership_changes(self):
        """Check every ownership group together without copying or changing memberships."""
        self.assertEqual(connection.vendor, 'postgresql')
        self.member.groups.add(self.first, self.second)
        before = set(self.member.groups.values_list('pk', flat=True))
        with self.assertNumQueries(1):
            validate_task_owner_roles()
        self.assertEqual(set(self.member.groups.values_list('pk', flat=True)), before)

    def test_error_distinguishes_all_missing_and_empty_roles(self):
        """Report missing groups separately from every empty configured ownership group."""
        self.second.delete()
        with self.settings(DIARY_TASK_OWNER_ROLES=('FirstOwner', 'SecondOwner', 'ThirdOwner')):
            with self.assertRaises(ImproperlyConfigured) as raised:
                validate_task_owner_roles()
        message = str(raised.exception)
        self.assertIn('DIARY_TASK_OWNER_ROLES', message)
        self.assertIn('Roles missing from the database: SecondOwner, ThirdOwner.', message)
        self.assertIn('Empty roles with no members: FirstOwner.', message)
        self.assertFalse(Group.objects.filter(name='ThirdOwner').exists())

    def test_populated_access_groups_do_not_satisfy_ownership_membership(self):
        """Reject empty ownership groups even when both access groups have members."""
        validate_access_groups()
        with self.assertRaisesMessage(CommandError, 'Empty roles with no members: FirstOwner, SecondOwner'):
            call_command('validate_diary_configuration', stdout=StringIO())

    def test_membership_removal_and_user_deletion_are_detected(self):
        """Read current ownership memberships on each validation call."""
        self.member.groups.add(self.first, self.second)
        validate_task_owner_roles()
        self.member.groups.remove(self.first)
        with self.assertRaisesMessage(ImproperlyConfigured, 'Empty roles with no members: FirstOwner.'):
            validate_task_owner_roles()
        self.member.groups.add(self.first)
        validate_task_owner_roles()
        self.member.delete()
        with self.assertRaisesMessage(ImproperlyConfigured, 'FirstOwner, SecondOwner'):
            validate_task_owner_roles()

    def test_database_failure_preserves_configuration_context(self):
        """Report query failures with the ownership setting and the original database exception."""
        with patch('django.db.models.query.QuerySet._fetch_all', side_effect=OperationalError('Unavailable')):
            with self.assertRaisesMessage(ImproperlyConfigured, 'DIARY_TASK_OWNER_ROLES') as raised:
                validate_task_owner_roles()
        self.assertIsInstance(raised.exception.__cause__, OperationalError)

    def test_no_configured_roles_need_no_membership_query(self):
        """Permit projects without role-owned tasks to omit ownership groups."""
        with self.settings(DIARY_TASK_OWNER_ROLES=()), self.assertNumQueries(0):
            validate_task_owner_roles()

    def test_validation_command_accepts_only_populated_roles(self):
        """Validate current ownership membership after application initialization."""
        with self.assertRaisesMessage(CommandError, 'Empty roles'):
            call_command('validate_diary_configuration', stdout=StringIO())
        self.member.groups.add(self.first, self.second)
        with self.assertNumQueries(2):
            call_command('validate_diary_configuration', stdout=StringIO())

    def test_setup_commands_remain_available_with_empty_ownership_groups(self):
        """Defer ownership database checks only for the existing setup and test commands."""
        for command in ('migrate', 'sync_access_policy', 'shell', 'createsuperuser', 'loaddata', 'test'):
            with self.subTest(command=command), patch('sys.argv', ['manage.py', command]), self.assertNumQueries(0):
                self.config.ready()
