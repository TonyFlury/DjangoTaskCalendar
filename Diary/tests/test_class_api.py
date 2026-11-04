from dataclasses import replace
from datetime import date
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings

from Diary import api
from Diary.choices import DateKind
from Diary.models import EventCalendar


# Verifies DV1-046: Class-based callable API and factories.
# Verifies DV1-047: Simple V1 access settings.
# Verifies DV1-048: Standard Django groups and optional template default.
@override_settings(
    DIARY_MANAGER='DiaryManager', DIARY_USER='DiaryUser',
    DIARY_TEMPLATE_NAME='Class API template',
)
class ClassAPITests(TestCase):
    def setUp(self):
        self.actor = api.Actor('manager', frozenset({'DiaryManager'}))
        self.client = api.DiaryAPI(actor=self.actor)
        self.client.define_milestones(definitions={'target': 'Target date'})
        self.template = self.client.create_template()
        self.version = self.template.create_version(number=1, milestone_names=('target',))
        self.entry = api.EntrySpec('Prepare', DateKind.SOURCE, milestone_name='target')
        self.version.add_entry(spec=self.entry)
        self.version.approve()
        self.created = self.client.create_diary(
            event_ref='class-api:1', name='Class API diary', milestone_dates={'target': date(2027, 6, 27)},
        )
        self.actor = replace(self.actor, calendar_keys=frozenset({self.created.key}))
        self.client = api.DiaryAPI(actor=self.actor)
        self.diary = self.client.diary(key=self.created.key)

    def test_factories_return_references_without_granting_calendar_scope(self):
        self.assertIsInstance(self.created, api.DiaryInstance)
        with self.assertRaises(PermissionDenied):
            self.created.read()
        self.assertEqual(self.diary.read()['key'], self.created.key)
        same = api.DiaryInstance.create(
            actor=self.actor, event_ref='class-api:1', name='Class API diary', milestone_dates={'target': date(2027, 6, 27)},
        )
        self.assertEqual(same.key, self.diary.key)
        self.assertEqual(EventCalendar.objects.count(), 1)
        self.assertEqual(api.DiaryInstance.from_key(actor=self.actor, key=str(same.key)).key, same.key)

    def test_template_factories_and_version_selection(self):
        self.assertEqual(self.client.template(key=self.template.key).key, self.template.key)
        self.assertEqual(self.client.template(name=' class API template ').key, self.template.key)
        self.assertEqual(api.DiaryTemplate.from_name(actor=self.actor).key, self.template.key)
        draft = self.template.create_version(number=2, milestone_names=('target',))
        self.assertEqual(self.template.latest_version().key, draft.key)
        self.assertEqual(self.template.latest_version(approved_only=True).key, self.version.key)
        self.assertEqual(self.template.version(number=2).key, draft.key)
        self.assertEqual(self.client.template_version().key, self.version.key)
        self.assertEqual(self.client.template_version(key=draft.key).read()['status'], 'draft')
        self.assertEqual(self.version.required_milestones()[0]['name'], 'target')
        with self.assertRaises(ValidationError):
            self.client.template(key=self.template.key, name='Class API template')

    def test_existing_handles_observe_closure_and_current_permission_settings(self):
        other = self.client.diary(key=self.diary.key)
        self.assertIs(other.close(), other)
        self.assertTrue(self.diary.read()['closed'])
        self.assertEqual(self.diary.active_tasks(), ())
        with self.assertRaisesMessage(ValidationError, 'This diary is closed.'):
            self.diary.add_entry(spec=api.EntrySpec('Another task', DateKind.ANNUAL, month=1, day=1))
        with self.settings(DIARY_MANAGER='AnotherManager', DIARY_USER='AnotherUser'):
            with self.assertRaises(PermissionDenied):
                self.diary.read()
            with self.assertRaises(PermissionDenied):
                self.version.required_milestones()
            with self.assertRaises(PermissionDenied):
                self.template.create_version(number=3)

    def test_user_reference_does_not_authorize_manager_actions(self):
        reviewer = api.Actor('reviewer', frozenset({'DiaryUser'}), frozenset({self.diary.key}))
        diary = api.DiaryInstance.from_key(actor=reviewer, key=self.diary.key)
        self.assertEqual(diary.read()['name'], 'Class API diary')
        with self.assertRaises(PermissionDenied):
            diary.close()
        with self.assertRaises(PermissionDenied):
            diary.add_entry(spec=api.EntrySpec('Denied', DateKind.ANNUAL, month=1, day=1))
        with self.assertRaises(PermissionDenied):
            api.DiaryTemplate.from_key(actor=reviewer, key=self.template.key)

    def test_user_role_does_not_grant_any_template_operation(self):
        user = api.Actor('ordinary-user', frozenset({'DiaryUser'}))
        version = api.DiaryTemplateVersion(actor=user, key=self.version.key)
        operations = (
            version.read,
            version.required_milestones,
            version.approve,
            lambda: version.add_entry(spec=self.entry),
            lambda: version.available_predecessors(entry_key=self.entry.entry_key),
            lambda: version.set_predecessors(entry_key=self.entry.entry_key, predecessor_keys=[]),
            lambda: api.DiaryTemplate.create(actor=user, name='Not permitted'),
            lambda: api.DiaryTemplate(actor=user, key=self.template.key).create_version(number=3),
        )
        for operation in operations:
            with self.assertRaises(PermissionDenied):
                operation()

    def test_legacy_action_mapping_cannot_grant_extra_access(self):
        user = api.Actor('legacy-user', frozenset({'LegacyEditors'}))
        with self.settings(DIARY_PERMISSION_GROUPS={'edit': ('LegacyEditors',)}):
            with self.assertRaises(PermissionDenied):
                api.DiaryTemplate.create(actor=user, name='Legacy grant ignored')

    def test_existing_template_version_handle_observes_approval(self):
        draft = self.template.create_version(number=2, milestone_names=('target',))
        draft.add_entry(spec=self.entry)
        other = self.client.template_version(key=draft.key)
        self.assertIs(other.approve(), other)
        self.assertEqual(draft.read()['status'], 'approved')
        with self.assertRaises(ValidationError):
            draft.add_entry(spec=api.EntrySpec('Too late', DateKind.ANNUAL, month=1, day=1))

    def test_instance_lookups_check_scope_and_existence(self):
        outsider = replace(self.actor, calendar_keys=frozenset())
        with self.assertRaises(PermissionDenied):
            api.DiaryInstance.from_key(actor=outsider, key=self.diary.key)

        # Direct construction of a reference cannot bypass operation checks.
        with self.assertRaises(PermissionDenied):
            api.DiaryInstance(actor=outsider, key=self.diary.key).read()
        missing = uuid4()
        actor = replace(self.actor, calendar_keys=frozenset({missing}))
        with self.assertRaises(EventCalendar.DoesNotExist):
            api.DiaryInstance.from_key(actor=actor, key=missing)

    def test_explicit_template_names_work_without_a_default_setting(self):
        with self.settings(DIARY_TEMPLATE_NAME=None):
            del settings.DIARY_TEMPLATE_NAME
            template = self.client.create_template(name='Caller chosen template')
            version = template.create_version(number=1, milestone_names=('target',))
            version.add_entry(spec=self.entry)
            version.approve()
            template.create_version(number=2)
            self.assertEqual(self.client.template(name='Caller chosen template').key, template.key)
            self.assertEqual(self.client.template_version(name='Caller chosen template').key, version.key)
            self.assertEqual(
                api.DiaryTemplateVersion.from_name(actor=self.actor, name='Caller chosen template').key,
                version.key,
            )
            ordinary = api.Actor('user', frozenset({'DiaryUser'}))
            created = api.DiaryInstance.create(
                actor=ordinary, event_ref='explicit:name', name='Explicit name diary', milestone_dates={'target': date(2027, 6, 27)}, template_name='Caller chosen template',
            )
            by_key = self.client.create_diary(
                event_ref='explicit:key', name='Explicit key diary', milestone_dates={'target': date(2027, 6, 27)}, template_version_key=version.key,
            )
            for diary in (created, by_key):
                self.assertEqual(EventCalendar.objects.get(pk=diary.key).template_version_id, version.key)

    def test_missing_default_allows_diary_without_a_template(self):
        with self.settings(DIARY_TEMPLATE_NAME=None):
            created = self.client.create_diary(event_ref='missing-template', name='No template')
            self.assertIsNone(EventCalendar.objects.get(pk=created.key).template_version_id)
            with self.assertRaises(ValidationError):
                self.client.template_version()
            with self.assertRaises(ValidationError):
                self.client.create_template()
        self.assertTrue(EventCalendar.objects.filter(event_ref='missing-template').exists())

    def test_explicit_name_overrides_default_and_rejects_ambiguous_selectors(self):
        with self.settings(DIARY_TEMPLATE_NAME='Unused default'):
            self.assertEqual(self.client.template_version(name='Class API template').key, self.version.key)
            diary = self.client.create_diary(
                event_ref='named-selection', name='Named diary', milestone_dates={'target': date(2027, 6, 27)}, template_name='Class API template',
            )
            self.assertEqual(EventCalendar.objects.get(pk=diary.key).template_version_id, self.version.key)
        with self.assertRaisesMessage(ValidationError, 'not both'):
            self.client.template_version(key=self.version.key, name='Class API template')
        with self.assertRaisesMessage(ValidationError, 'not both'):
            self.client.create_diary(
                event_ref='ambiguous-selection', name='Ambiguous', milestone_dates={},
                template_version_key=self.version.key, template_name='Class API template',
            )
        self.assertFalse(EventCalendar.objects.filter(event_ref='ambiguous-selection').exists())
