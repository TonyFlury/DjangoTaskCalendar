"""Personal work survives a diary's one-time template application."""
import json
from dataclasses import replace
from datetime import date
from io import StringIO
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.shortcuts import render
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings

from Diary.api import Actor, DiaryAPI, EntrySpec
from Diary.choices import DateKind, OwnerKind
from Diary.models import CalendarEntry, CalendarMilestone, EntryDependency, EventCalendar, Milestone
from Diary.tests.test_task_creation import TaskCreationFixtures
from Diary.views import ManagerDiaryView, PersonalDiaryView, TaskCreateView, TemplateApplyView


class OptionalTemplateFixtures(TaskCreationFixtures):
    def setUp(self):
        super().setUp()
        created = DiaryAPI(actor=self.actor).create_diary(name='Personal workspace', event_ref='empty:1', without_template=True)
        self.empty_actor = replace(self.actor, calendar_keys=frozenset({created.key}))
        self.empty = DiaryAPI(actor=self.empty_actor).diary(key=created.key)
        self.personal_actor = Actor(f'user:{self.user.pk}', frozenset({'Participants'}), frozenset({created.key}))
        self.personal = DiaryAPI(actor=self.personal_actor).diary(key=created.key)

    def personal_task(self, name, **values):
        spec = EntrySpec(name, values.pop('date_kind', DateKind.ONCE),
                         owner_kind=OwnerKind.PERSON, person_ref=self.personal_actor.reference,
                         **(values or {'fixed_date': date(2027, 6, 1)}))
        self.personal.add_entry(spec=spec)
        return spec

    def apply(self, **values):
        return self.empty.apply_template(template_version_key=self.version.key,
                                         milestone_dates=values.pop('milestone_dates', {'target': date(2027, 6, 20)}), **values)

    def snapshot(self):
        return (list(EventCalendar.objects.order_by('pk').values()),
                list(CalendarEntry.objects.order_by('pk').values()),
                list(CalendarMilestone.objects.order_by('pk').values()),
                list(EntryDependency.objects.order_by('pk').values()))


@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',))
class OptionalTemplateTests(OptionalTemplateFixtures, TestCase):
    def test_empty_diary_creation_defaults_retries_and_conflicting_inputs(self):
        self.assertIsNone(self.empty.read()['template_version_key'])
        self.assertEqual(self.empty.read()['entries'], ())
        api = DiaryAPI(actor=self.empty_actor)
        self.assertEqual(api.create_diary(name='Personal workspace', event_ref='empty:1', without_template=True).key, self.empty.key)
        with self.settings(DIARY_TEMPLATE_NAME=None):
            other = api.create_diary(name='No default')
            self.assertIsNone(EventCalendar.objects.get(pk=other.key).template_version_id)
        with self.assertRaises(ValidationError):
            api.create_diary(name='Invalid', template_name='Creation template', without_template=True)
        with self.assertRaises(ValidationError):
            api.create_diary(name='Invalid', milestone_dates={'target': date(2027, 6, 20)}, without_template=True)

    def test_application_preserves_private_fields_history_privacy_and_identity(self):
        first = self.personal_task('Prepare')
        completed = self.personal_task('Review')
        self.personal.update_due_date(entry_key=first.entry_key, due_date=date(2027, 7, 1), expected_revision=0)
        self.personal.complete(entry_key=completed.entry_key, expected_revision=0)
        self.personal_task('My annual note', date_kind=DateKind.ANNUAL, month=2, day=29, year_offset=1)
        before = list(CalendarEntry.objects.filter(calendar_id=self.empty.key).order_by('pk').values())
        created_at = EventCalendar.objects.get(pk=self.empty.key).created_at
        self.assertIs(self.apply(), self.empty)
        self.assertEqual(list(CalendarEntry.objects.filter(calendar_id=self.empty.key, source_entry=None).order_by('pk').values()), before)
        calendar = EventCalendar.objects.get(pk=self.empty.key)
        self.assertEqual(calendar.created_at, created_at)
        self.assertTrue(calendar.dependencies_locked)
        self.assertEqual(calendar.template_version_id, self.version.key)
        copied = calendar.entries.get(entry_key=self.first.entry_key)
        successor = calendar.entries.get(entry_key=self.second.entry_key)
        self.assertEqual(copied.name, 'Prepare (template)')
        self.assertEqual(successor.name, 'Review (template)')
        self.assertEqual(successor.predecessors.get().pk, copied.pk)
        outsider = Actor(f'user:{self.other.pk}', frozenset({'Participants'}), frozenset({self.empty.key}))
        visible = DiaryAPI(actor=outsider).diary(key=self.empty.key).read()['entries']
        self.assertEqual({item['entry_key'] for item in visible}, {self.first.entry_key, self.second.entry_key})
        before = self.snapshot()
        self.apply()
        DiaryAPI(actor=self.actor).create_diary(name='Personal workspace', event_ref='empty:1', without_template=True)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_dates_permissions_drafts_and_closed_diaries_leave_no_changes(self):
        before = self.snapshot()
        for dates in ({}, {'target': None}, {'target': '2027-06-20'}):
            with self.assertRaises(ValidationError):
                self.apply(milestone_dates=dates)
            self.assertEqual(self.snapshot(), before)
        for actor in (self.personal_actor, replace(self.empty_actor, calendar_keys=frozenset())):
            with self.assertRaises(PermissionDenied):
                DiaryAPI(actor=actor).diary(key=self.empty.key).apply_template(
                    template_version_key=self.version.key, milestone_dates={'target': date(2027, 6, 20)})
        draft = self.template.create_version(number=2)
        with self.assertRaises(ValidationError):
            self.empty.apply_template(template_version_key=draft.key, milestone_dates={})
        self.assertEqual(self.snapshot(), before)
        self.empty.close()
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            self.apply()
        self.assertEqual(self.snapshot(), before)

    def test_unused_milestone_is_required_and_replacement_is_rejected(self):
        Milestone.objects.create(name='unused', label='Unused date')
        next_version = self.template.save_version(entries=(self.first, self.second),
            predecessors={self.second.entry_key: (self.first.entry_key,)}, expected_version_key=self.version.key,
            milestone_names=('target', 'unused'))
        with self.assertRaisesMessage(ValidationError, 'unused'):
            self.empty.apply_template(template_version_key=next_version.key, milestone_dates={'target': date(2027, 6, 20)})
        self.apply()
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            self.empty.apply_template(template_version_key=next_version.key,
                milestone_dates={'target': date(2027, 6, 20), 'unused': date(2027, 6, 1)})
        with self.assertRaises(IntegrityError), transaction.atomic():
            EventCalendar.objects.filter(pk=self.empty.key).update(template_version=None)
        with self.assertRaises(IntegrityError), transaction.atomic():
            EventCalendar.objects.filter(pk=self.empty.key).update(dependencies_locked=False)
        with self.assertRaises(ValidationError):
            self.empty.set_milestone_dates(milestone_dates={'target': date(2030, 1, 1)})
        self.assertEqual(self.snapshot(), before)

    def test_midway_failure_rolls_back_assignment_dates_and_task_copies(self):
        self.personal_task('My note')
        before = self.snapshot()
        with patch('Diary.api.EntryDependency.objects.create', side_effect=ValidationError('Cannot save link')):
            with self.assertRaises(ValidationError):
                self.apply()
        self.assertEqual(self.snapshot(), before)

    def test_raw_assignment_requires_approved_template_and_complete_initialization(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            EventCalendar.objects.filter(pk=self.empty.key).update(template_version_id=self.version.key)
        with self.assertRaises(IntegrityError), transaction.atomic():
            EventCalendar.objects.filter(pk=self.empty.key).update(dependencies_locked=False)
        self.assertIsNone(self.empty.read()['template_version_key'])

    def response(self, view, user, *, data=None, method='get'):
        payload = data or {}
        if method == 'get':
            payload = {'diary_key': str(self.empty.key), **payload}
        request = getattr(RequestFactory(), method)('/host/diary/?diary_key=' + str(self.empty.key), payload)
        request.user = user
        with patch('Diary.views.render', wraps=render) as renderer:
            response = view.as_view(permitted_diary_keys=(self.empty.key,))(request)
        return response, renderer

    def test_empty_personal_page_and_task_creation_have_no_template_warning(self):
        response, renderer = self.response(PersonalDiaryView, self.user)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'does not exist')
        for user in (self.user, self.manager):
            response, renderer = self.response(TaskCreateView, user)
            self.assertContains(response, 'This personal task' if user == self.user else 'Select a person')
            self.assertNotContains(response, 'Template for future diaries')
            self.assertNotIn('source', dict(renderer.call_args.args[2]['creation_form'].fields['date_kind'].choices))
        spec = self.personal_task('Existing note')
        request = RequestFactory().post('/host/create/?diary_key=' + str(self.empty.key), {
            'entry_key': str(spec.entry_key), 'name': 'Existing note', 'date_kind': 'once', 'fixed_date': '2027-06-01'})
        request.user = self.user
        self.assertEqual(TaskCreateView.as_view(permitted_diary_keys=(self.empty.key,))(request).status_code, 302)

    def test_manager_apply_workflow_requires_every_date_and_preserves_personal_tasks(self):
        self.personal_task('Prepare')
        response, renderer = self.response(ManagerDiaryView, self.manager)
        self.assertContains(response, 'Apply template')
        response, renderer = self.response(TemplateApplyView, self.manager)
        self.assertContains(response, 'Choose template')
        response, renderer = self.response(TemplateApplyView, self.manager,
                                            data={'template_version_key': str(self.version.key)})
        self.assertContains(response, 'milestone_target')
        response, renderer = self.response(TemplateApplyView, self.manager, method='post',
                                            data={'template_version_key': str(self.version.key)})
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self.empty.read()['template_version_key'])
        data = {'template_version_key': str(self.version.key), 'milestone_target': '2027-06-20'}
        response, renderer = self.response(TemplateApplyView, self.manager, method='post', data=data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(self.empty.read()['entries']), 3)
        response, renderer = self.response(TemplateApplyView, self.manager, method='post', data=data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(self.empty.read()['entries']), 3)
        with self.assertRaises(PermissionDenied):
            self.response(TemplateApplyView, self.user)

    def test_template_with_no_dates_or_tasks_can_be_applied_through_ui(self):
        version = self.template.create_version(number=2).approve()
        response, renderer = self.response(TemplateApplyView, self.manager,
                                            data={'template_version_key': str(version.key)})
        self.assertContains(response, 'Apply template</button>')
        response, renderer = self.response(TemplateApplyView, self.manager, method='post',
                                            data={'template_version_key': str(version.key)})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.empty.read()['template_version_key'], version.key)

    def test_management_create_inspect_apply_and_delete_without_a_template(self):
        output = StringIO()
        call_command('manage_diaries', 'create', '--without-template', '--json', name='CLI workspace',
                     event_ref='cli:empty', actor=self.manager.get_username(), stdout=output)
        key = json.loads(output.getvalue())['key']
        output = StringIO()
        call_command('manage_diaries', 'list', '--details', event_ref='cli:empty', actor=self.manager.get_username(), stdout=output)
        self.assertIn('Not applied', output.getvalue())
        call_command('manage_diaries', 'apply-template', '--json', diary=key, template='Creation template',
                     milestone=['target=2027-06-20'], actor=self.manager.get_username(), stdout=StringIO())
        self.assertEqual(EventCalendar.objects.get(pk=key).template_version_id, self.version.key)
        call_command('manage_diaries', 'delete', '--force', diary=self.empty.key,
                     actor=self.manager.get_username(), stdout=StringIO())
        self.assertFalse(EventCalendar.objects.filter(pk=self.empty.key).exists())
        connection.check_constraints()


@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',))
class ConcurrentTemplateApplicationTests(OptionalTemplateFixtures, TransactionTestCase):
    def test_two_identical_applications_copy_one_snapshot(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections

        barrier = Barrier(2)

        def apply():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return self.apply().key
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(list(executor.map(lambda unused: apply(), range(2))), [self.empty.key, self.empty.key])
        self.assertEqual(CalendarEntry.objects.filter(calendar_id=self.empty.key).count(), 2)
        self.assertEqual(EntryDependency.objects.filter(entry__calendar_id=self.empty.key).count(), 1)
