"""Operator commands enumerate data and delete complete objects atomically."""
import json
from io import StringIO
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings

from Diary.management import administration
from Diary.models import (CalendarEntry, CalendarMilestone, CalendarTemplate, EntryDependency,
                          EventCalendar, Milestone, TemplateDependency, TemplateEntry, TemplateMilestone, TemplateVersion)
from Diary.tests.test_task_creation import TaskCreationFixtures


@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',))
class AdministrationCommandTests(TaskCreationFixtures, TestCase):
    def command(self, command_name, operation, **options):
        output = StringIO()
        call_command(command_name, operation, actor=options.pop('actor', self.manager.get_username()), stdout=output, **options)
        return json.loads(output.getvalue())

    def templates(self, operation, **options):
        if operation == 'list':
            options.setdefault('json', True)
        return self.command('manage_diary_templates', operation, **options)

    def diaries(self, operation, **options):
        if operation == 'list':
            options.setdefault('json', True)
        return self.command('manage_diaries', operation, **options)

    def snapshot(self):
        return {model._meta.label: list(model.objects.order_by('pk').values()) for model in (
            CalendarEntry, CalendarMilestone, CalendarTemplate, EntryDependency, EventCalendar,
            Milestone, TemplateDependency, TemplateEntry, TemplateMilestone, TemplateVersion)}

    def test_lists_and_details_include_versions_dates_tasks_and_counts(self):
        templates = self.templates('list')
        self.assertEqual(templates[0]['version_count'], 1)
        versions = self.templates('versions', template='creation TEMPLATE')
        self.assertEqual(versions[0]['diary_count'], 2)
        self.assertEqual(versions[0]['task_count'], 2)
        self.assertEqual(versions[0]['milestone_count'], 1)
        detail = self.templates('show', template='Creation template', template_version=1)
        self.assertEqual(detail['milestones'][0]['name'], 'target')
        self.assertEqual(len(detail['entries']), 2)
        diaries = self.diaries('list', state='open', template='Creation template')
        self.assertEqual(len(diaries), 2)
        self.assertEqual(diaries[0]['task_count'], 2)
        detail = self.diaries('show', diary=self.diary.key)
        self.assertEqual(detail['name'], 'Selected diary')
        self.assertEqual(len(detail['entries']), 2)

    def test_diary_list_defaults_to_names_only_and_retains_filters(self):
        output = StringIO()
        call_command('manage_diaries', 'list', actor=self.manager.get_username(), stdout=output)
        self.assertEqual(output.getvalue(), 'Other diary\nSelected diary\n')
        output = StringIO()
        call_command('manage_diaries', 'list', actor=self.manager.get_username(),
                     event_ref='creation:selected', stdout=output)
        self.assertEqual(output.getvalue(), 'Selected diary\n')
        output = StringIO()
        call_command('manage_diaries', 'list', actor=self.manager.get_username(), state='closed', stdout=output)
        self.assertEqual(output.getvalue(), '')
        EventCalendar.objects.filter(pk=self.other_diary.key).update(name='Selected diary')
        output = StringIO()
        call_command('manage_diaries', 'list', actor=self.manager.get_username(), stdout=output)
        self.assertEqual(output.getvalue(), 'Selected diary\nSelected diary\n')

    def test_diary_list_details_formats_counts_dates_and_closed_state(self):
        self.diary.complete(entry_key=self.first.entry_key, expected_revision=0)
        self.diary.close()
        output = StringIO()
        call_command('manage_diaries', 'list', '--full', actor=self.manager.get_username(),
                     state='closed', stdout=output)
        text = output.getvalue()
        self.assertTrue(text.startswith('Selected diary\n'))
        for value in (str(self.diary.key), 'Status:', 'Closed', 'Created:', 'Closed:',
                      'Creation template (version 1)', '2 total, 1 completed, 1 open', 'creation:selected'):
            self.assertIn(value, text)
        self.assertNotIn('Other diary', text)
        self.assertRegex(text, r'Created:\s+\d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2} [A-Z]+')
        output = StringIO()
        call_command('manage_diaries', 'list', '--details', actor=self.manager.get_username(),
                     state='closed', stdout=output)
        self.assertEqual(text, output.getvalue())
        with self.assertRaises(CommandError):
            self.diaries('list', details=True)
        with self.assertRaises(CommandError):
            self.diaries('show', diary=self.diary.key, details=True)

    def test_template_list_names_filter_and_empty_results(self):
        self.templates('create', template='Another template')
        output = StringIO()
        call_command('manage_diary_templates', 'list', actor=self.manager.get_username(), stdout=output)
        self.assertEqual(output.getvalue(), 'Another template\nCreation template\n')
        output = StringIO()
        call_command('manage_diary_templates', 'list', template='CREATION TEMPLATE',
                     actor=self.manager.get_username(), stdout=output)
        self.assertEqual(output.getvalue(), 'Creation template\n')
        output = StringIO()
        call_command('manage_diary_templates', 'list', template='Unknown',
                     actor=self.manager.get_username(), stdout=output)
        self.assertEqual(output.getvalue(), '')

    def test_template_details_show_each_versions_requirements_and_actual_usage(self):
        CalendarTemplate.objects.filter(pk=self.template.key).update(description='Reusable event tasks')
        Milestone.objects.create(name='unused_requirement', label='Unused required date')
        Milestone.objects.create(name='unrelated', label='Unrelated catalogue date')
        self.templates('create-version', template='Creation template', milestone=['unused_requirement'])
        self.templates('create', template='Empty definition')
        self.diary.close()
        output = StringIO()
        call_command('manage_diary_templates', 'list', '--details', actor=self.manager.get_username(), stdout=output)
        text = output.getvalue()
        for value in ('Creation template', 'Description:   Reusable event tasks', 'In use:        Yes (2 diaries)',
                      'Version 1 (approved)', 'Target (target)', 'Used by:\n      - Other diary\n      - Selected diary',
                      'Version 2 (draft)', 'Unused required date (unused_requirement)', 'Used by:     None',
                      'Empty definition', 'Versions:      None', 'Description:   (none)'):
            self.assertIn(value, text)
        self.assertNotIn('Unrelated catalogue date', text)
        version_two = text.split('Version 2 (draft)', 1)[1].split('Empty definition', 1)[0]
        self.assertNotIn('Target (target)', version_two)
        self.assertNotIn('Selected diary', version_two)
        self.assertNotIn('Other diary', version_two)
        self.assertEqual(text.count('In use:'), 2)
        alias_output = StringIO()
        call_command('manage_diary_templates', 'list', '--full', actor=self.manager.get_username(), stdout=alias_output)
        self.assertEqual(alias_output.getvalue(), text)
        with self.assertRaises(CommandError):
            self.templates('list', details=True)
        with self.assertRaises(CommandError):
            self.templates('versions', template='Creation template', details=True)

    def test_uuid_lists_show_identity_with_name_and_support_details(self):
        for command_name, key, name, selector in (
            ('manage_diaries', self.diary.key, 'Selected diary', {'event_ref': 'creation:selected'}),
            ('manage_diary_templates', self.template.key, 'Creation template', {'template': 'Creation template'}),
        ):
            for details in (False, True):
                with self.subTest(command=command_name, details=details):
                    output = StringIO()
                    call_command(command_name, 'list', '--uuid', details=details,
                                 actor=self.manager.get_username(), stdout=output, **selector)
                    text = output.getvalue()
                    self.assertEqual(text.splitlines()[0], f'{key}  {name}')
                    self.assertEqual(text.count(str(key)), 1)
                    if not details:
                        self.assertEqual(text, f'{key}  {name}\n')
            output = StringIO()
            call_command(command_name, 'list', '--uuid', '--json', actor=self.manager.get_username(),
                         stdout=output, **selector)
            self.assertEqual(json.loads(output.getvalue())[0]['id'], str(key))
            with self.assertRaises(CommandError):
                call_command(command_name, 'show', uuid=True, actor=self.manager.get_username(), **selector)

    def test_create_copy_and_approve_template_version(self):
        self.templates('create', template='New definition', description='Example')
        draft = self.templates('create-version', template='New definition', milestone=['target'])
        self.assertEqual(draft['status'], 'draft')
        self.assertEqual(draft['milestones'][0]['name'], 'target')
        self.assertEqual(self.templates('approve', template='New definition', template_version=1)['status'], 'approved')
        copied = self.templates('create-version', template='Creation template', copy_version=1)
        self.assertEqual(copied['number'], 2)
        self.assertEqual(len(copied['entries']), 2)
        self.assertEqual(copied['milestones'][0]['name'], 'target')
        second = next(item for item in copied['entries'] if item['entry_key'] == str(self.second.entry_key))
        self.assertEqual(second['predecessors'], [str(self.first.entry_key)])
        self.templates('approve', template='Creation template', template_version=2)
        self.assertEqual(EventCalendar.objects.get(pk=self.diary.key).template_version_id, self.version.key)

    def test_create_requires_all_dates_and_close_is_idempotent(self):
        before = self.snapshot()
        for dates in ([], ['target=bad'], ['target=2027-05-01', 'target=2027-06-01']):
            with self.assertRaises(CommandError):
                self.diaries('create', template='Creation template', name='New', milestone=dates)
            self.assertEqual(self.snapshot(), before)
        result = self.diaries('create', template='Creation template', template_version=1, name='New',
                              event_ref='operator:new', milestone=['target=2027-06-01'])
        repeated = self.diaries('create', template='Creation template', name='New',
                                event_ref='operator:new', milestone=['target=2027-06-01'])
        self.assertEqual(result['key'], repeated['key'])
        closed = self.diaries('close', diary=result['key'])
        self.assertTrue(closed['closed'])
        self.assertEqual(self.diaries('close', diary=result['key']), closed)
        self.assertEqual(len(self.diaries('list', state='closed')), 1)

    def test_diary_deletion_previews_and_removes_only_target_including_history(self):
        self.diary.complete(entry_key=self.first.entry_key, expected_revision=0)
        before = self.snapshot()
        plan = self.diaries('delete', diary=self.diary.key)
        self.assertFalse(plan['deleted'])
        self.assertEqual(plan['counts']['tasks'], 2)
        self.assertEqual(plan['counts']['completed_tasks'], 1)
        self.assertEqual(plan['counts']['dependencies'], 1)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.diaries('delete', diary=self.diary.key, yes=True, dry_run=True)['deleted'])
        self.assertEqual(self.snapshot(), before)
        other = list(CalendarEntry.objects.filter(calendar=self.other_diary.key).values())
        self.assertTrue(self.diaries('delete', diary=self.diary.key, yes=True)['deleted'])
        self.assertFalse(EventCalendar.objects.filter(pk=self.diary.key).exists())
        self.assertFalse(CalendarEntry.objects.filter(calendar_id=self.diary.key).exists())
        self.assertFalse(CalendarMilestone.objects.filter(calendar_id=self.diary.key).exists())
        self.assertEqual(list(CalendarEntry.objects.filter(calendar=self.other_diary.key).values()), other)
        self.assertEqual(TemplateEntry.objects.count(), 2)
        connection.check_constraints()

    def test_referenced_version_and_template_are_protected(self):
        before = self.snapshot()
        for operation, options in (('delete-version', {'template_version': 1}), ('delete', {})):
            with self.assertRaisesMessage(CommandError, 'reference'):
                self.templates(operation, template='Creation template', yes=True, **options)
        self.assertEqual(self.snapshot(), before)

    def test_unused_approved_version_and_whole_template_deletion(self):
        self.templates('create-version', template='Creation template', copy_version=1)
        self.templates('approve', template='Creation template', template_version=2)
        before = self.snapshot()
        plan = self.templates('delete-version', template='Creation template', template_version=2)
        self.assertEqual(plan['counts']['milestone_declarations'], 1)
        self.assertEqual(self.snapshot(), before)
        self.templates('delete-version', template='Creation template', template_version=2, yes=True)
        self.assertEqual(TemplateVersion.objects.count(), 1)
        for diary in (self.diary, self.other_diary):
            self.diaries('delete', diary=diary.key, yes=True)
        self.templates('delete', template='Creation template', yes=True)
        for model in (CalendarTemplate, TemplateVersion, TemplateEntry, TemplateDependency, TemplateMilestone):
            self.assertFalse(model.objects.exists())
        self.assertTrue(Milestone.objects.filter(name='target').exists())
        connection.check_constraints()

    def test_empty_template_and_empty_diary_can_be_deleted(self):
        self.templates('create', template='Empty')
        self.assertFalse(self.templates('delete', template='Empty')['deleted'])
        self.templates('create-version', template='Empty')
        self.templates('approve', template='Empty', template_version=1)
        diary = self.diaries('create', template='Empty', name='Empty diary')
        self.diaries('close', diary=diary['key'])
        self.diaries('delete', diary=diary['key'], yes=True)
        self.templates('delete', template='Empty', yes=True)
        connection.check_constraints()

    def test_failed_deletion_rolls_back_parent_children_and_history(self):
        before = self.snapshot()
        real_delete = administration.delete_rows
        calls = 0

        def fail_midway(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise ValidationError('Simulated cleanup failure')
            return real_delete(*args, **kwargs)

        with patch.object(administration, 'delete_rows', side_effect=fail_midway):
            with self.assertRaises(CommandError):
                self.diaries('delete', diary=self.diary.key, yes=True)
        self.assertEqual(self.snapshot(), before)

    def test_removing_dependency_endpoints_cannot_bypass_live_diary_guard(self):
        before = self.snapshot()
        dependency = EntryDependency.objects.get(entry__calendar_id=self.diary.key)
        with self.assertRaises(IntegrityError), transaction.atomic():
            administration.delete_rows(CalendarEntry, 'calendar_id = %s', [self.diary.key])
            administration.delete_rows(EntryDependency, 'id = %s', [dependency.pk])
        self.assertEqual(self.snapshot(), before)

    def test_failed_template_deletion_restores_approved_version(self):
        self.templates('create-version', template='Creation template', copy_version=1)
        self.templates('approve', template='Creation template', template_version=2)
        before = self.snapshot()
        real_delete = administration.delete_rows

        def fail_on_declarations(model, *args):
            if model is TemplateMilestone:
                raise ValidationError('Simulated cleanup failure')
            return real_delete(model, *args)

        with patch.object(administration, 'delete_rows', side_effect=fail_on_declarations):
            with self.assertRaises(CommandError):
                self.templates('delete-version', template='Creation template', template_version=2, yes=True)
        self.assertEqual(self.snapshot(), before)

    def test_missing_actors_targets_and_irrelevant_flags_fail_without_changes(self):
        before = self.snapshot()
        for actor in (self.user, self.outsider):
            for name in ('manage_diaries', 'manage_diary_templates'):
                with self.assertRaises(CommandError):
                    self.command(name, 'list', actor=actor.get_username())
        self.manager.is_active = False
        self.manager.save()
        with self.assertRaises(CommandError):
            self.diaries('list')
        self.manager.is_active = True
        self.manager.save()
        for operation, options in (('delete', {}), ('delete', {'diary': self.diary.key, 'template': 'Creation template'})):
            with self.assertRaises(CommandError):
                self.diaries(operation, yes=True, **options)
        with self.assertRaises(CommandError):
            self.templates('delete', template='Creation template', template_version=1, yes=True)
        with self.assertRaises(CommandError):
            self.templates('delete-version', template='Creation template', yes=True)
        with self.assertRaises(CommandError):
            self.templates('create-version', template='Creation template', milestone=['typo'])
        self.assertEqual(self.snapshot(), before)
