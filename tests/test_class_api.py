from dataclasses import replace
from datetime import date
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings

from Diary import api
from Diary.choices import DateKind
from Diary.models import EventCalendar


@override_settings(
    DIARY_PERMISSION_GROUPS={
        'use': ('DiaryUser', 'DiaryManager'),
        'view': ('DiaryUser', 'DiaryManager', 'Reviewer'),
        'edit': ('DiaryManager',),
        'view_template': ('DiaryManager',),
    },
    DIARY_TEMPLATE_NAME='Class API template',
)
class ClassAPITests(TestCase):
    def setUp(self):
        self.actor = api.Actor('manager', frozenset({'DiaryManager', 'DiaryUser'}))
        self.client = api.DiaryAPI(actor=self.actor)
        self.client.define_milestones(definitions={'target': 'Target date'})
        self.template = self.client.create_template()
        self.version = self.template.create_version(number=1)
        self.entry = api.EntrySpec('Prepare', DateKind.SOURCE, milestone_name='target')
        self.version.add_entry(spec=self.entry)
        self.version.approve()
        self.created = self.client.create_diary(
            event_ref='class-api:1', name='Class API diary', event_year=2027,
            milestone_dates={'target': date(2027, 6, 27)},
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
            actor=self.actor, event_ref='class-api:1', name='Class API diary', event_year=2027,
            milestone_dates={'target': date(2027, 6, 27)},
        )
        self.assertEqual(same.key, self.diary.key)
        self.assertEqual(EventCalendar.objects.count(), 1)
        self.assertEqual(api.DiaryInstance.from_key(actor=self.actor, key=str(same.key)).key, same.key)

    def test_template_factories_and_version_selection(self):
        self.assertEqual(self.client.template(key=self.template.key).key, self.template.key)
        self.assertEqual(self.client.template(name=' class API template ').key, self.template.key)
        self.assertEqual(api.DiaryTemplate.from_name(actor=self.actor).key, self.template.key)
        draft = self.template.create_version(number=2)
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
        with self.settings(DIARY_PERMISSION_GROUPS={}):
            with self.assertRaises(PermissionDenied):
                self.diary.read()
            with self.assertRaises(PermissionDenied):
                self.version.required_milestones()
            with self.assertRaises(PermissionDenied):
                self.template.create_version(number=3)

    def test_a_view_reference_does_not_authorize_writes(self):
        reviewer = api.Actor('reviewer', frozenset({'Reviewer'}), frozenset({self.diary.key}))
        diary = api.DiaryInstance.from_key(actor=reviewer, key=self.diary.key)
        self.assertEqual(diary.read()['name'], 'Class API diary')
        with self.assertRaises(PermissionDenied):
            diary.close()
        with self.assertRaises(PermissionDenied):
            diary.add_entry(spec=api.EntrySpec('Denied', DateKind.ANNUAL, month=1, day=1))
        with self.assertRaises(PermissionDenied):
            api.DiaryTemplate.from_key(actor=reviewer, key=self.template.key)

    def test_existing_template_version_handle_observes_approval(self):
        draft = self.template.create_version(number=2)
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
