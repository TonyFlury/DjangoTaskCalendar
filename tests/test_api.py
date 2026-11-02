from dataclasses import replace
from datetime import date
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from Diary import api
from Diary.choices import DateKind, OwnerKind
from Diary.models import (CalendarEntry, CalendarMilestone, EntryDependency, EventCalendar,
                          Milestone, TemplateDependency, TemplateEntry, TemplateVersion)


class Directory:
    def person_in_groups(self, reference, group_names):
        return reference in {'person:1', 'person:2'} and 'ExecMember' in group_names

    def role_exists(self, reference):
        return reference == 'SponsorshipManager'


@override_settings(
    DIARY_PERMISSION_GROUPS={'use': ('ExecMember', 'Officer'), 'view': ('ExecMember', 'Officer'),
                             'edit': ('Officer',), 'view_template': ('Officer',)},
    DIARY_TEMPLATE_NAME='Garage Sale calendar', DIARY_TIME_ZONE='Europe/London',
)
class DiaryTests(TestCase):
    def setUp(self):
        self.officer = api.Actor('person:1', frozenset({'Officer', 'ExecMember'}))
        self.exec_member = api.Actor('person:2', frozenset({'ExecMember'}))
        api.define_milestones(actor=self.officer, definitions={
            'event_date': 'Event date', 'add_board_bookings_open': 'Advertising board bookings open',
            'unused_date': 'Unused date',
        })
        self.template = api.create_template(actor=self.officer, name='Standard calendar')
        self.version = api.create_template_version(actor=self.officer, template_key=self.template, number=1)
        self.first = api.EntrySpec('Prepare boards', DateKind.RELATIVE,
                                   milestone_name='add_board_bookings_open', day_offset=42)
        self.second = api.EntrySpec('Inspect boards', DateKind.SOURCE, milestone_name='event_date')
        self.annual = api.EntrySpec('Annual check', DateKind.ANNUAL, month=3, day=1)
        for spec in (self.first, self.second, self.annual):
            api.add_template_entry(actor=self.officer, template_version_key=self.version, spec=spec)
        api.set_predecessors(actor=self.officer, scope_key=self.version, entry_key=self.second.entry_key,
                             predecessor_keys=[self.first.entry_key], template=True)

    def calendar(self, ref='event:2027', dates=None):
        api.approve_template_version(actor=self.officer, template_version_key=self.version)
        key = api.create_calendar(actor=self.officer, template_version_key=self.version, event_ref=ref,
                                  name='June event', event_year=2027,
                                  milestone_dates=dates if dates is not None else {
                                      'event_date': date(2027, 6, 27),
                                      'add_board_bookings_open': date(2027, 5, 1),
                                  })
        self.officer = replace(self.officer, calendar_keys=frozenset({key}))
        self.exec_member = replace(self.exec_member, calendar_keys=frozenset({key}))
        return key

    def test_postgresql(self):
        self.assertEqual(connection.vendor, 'postgresql')

    def test_close_calendar_preserves_open_tasks_and_completion_records(self):
        key = self.calendar()
        personal = api.EntrySpec('My open task', DateKind.ONCE, fixed_date=date(2027, 6, 1),
                                  owner_kind=OwnerKind.PERSON, person_ref=self.exec_member.reference)
        api.add_entry(actor=self.exec_member, calendar_key=key, spec=personal)
        completed = CalendarEntry.objects.get(calendar_id=key, entry_key=self.annual.entry_key)
        completed.completed_at = timezone.now()
        completed.completed_by_ref = self.officer.reference
        completed.completed_due_date = completed.due_date
        completed.save()
        before = list(CalendarEntry.objects.filter(calendar_id=key).order_by('pk').values())
        milestones = list(CalendarMilestone.objects.filter(calendar_id=key).order_by('pk').values())
        dependencies = list(EntryDependency.objects.filter(entry__calendar_id=key).order_by('pk').values())
        self.assertTrue(api.personal_tasks(actor=self.exec_member, calendar_key=key))

        self.assertEqual(api.close_calendar(actor=self.officer, calendar_key=key), key)

        result = api.get_calendar(actor=self.officer, calendar_key=key)
        self.assertTrue(result['closed'])
        self.assertIsNotNone(result['closed_at'])
        self.assertEqual(result['closed_by_ref'], self.officer.reference)
        self.assertEqual(len(result['entries']), 4)
        self.assertEqual(list(CalendarEntry.objects.filter(calendar_id=key).order_by('pk').values()), before)
        self.assertEqual(list(CalendarMilestone.objects.filter(calendar_id=key).order_by('pk').values()), milestones)
        self.assertEqual(list(EntryDependency.objects.filter(entry__calendar_id=key).order_by('pk').values()), dependencies)
        self.assertEqual(api.active_tasks(actor=self.officer, calendar_key=key), ())
        self.assertEqual(api.personal_tasks(actor=self.exec_member, calendar_key=key), ())

    def test_close_calendar_is_idempotent_and_does_not_reopen_on_creation_retry(self):
        key = self.calendar()
        api.close_calendar(actor=self.officer, calendar_key=key)
        original = api.get_calendar(actor=self.officer, calendar_key=key)
        other_manager = replace(self.officer, reference='another-manager')
        self.assertEqual(api.close_calendar(actor=other_manager, calendar_key=str(key)), key)
        self.assertEqual(api.get_calendar(actor=self.officer, calendar_key=key), original)
        self.assertEqual(self.calendar(), key)
        self.assertTrue(api.get_calendar(actor=self.officer, calendar_key=key)['closed'])

    def test_close_calendar_requires_configured_edit_access_and_host_scope(self):
        key = self.calendar()
        for actor in (self.exec_member, replace(self.officer, calendar_keys=frozenset())):
            with self.assertRaises(PermissionDenied):
                api.close_calendar(actor=actor, calendar_key=key)
        self.assertFalse(EventCalendar.objects.get(pk=key).closed_at)
        with self.settings(DIARY_PERMISSION_GROUPS={'edit': ('CustomManager',)}):
            with self.assertRaises(PermissionDenied):
                api.close_calendar(actor=self.officer, calendar_key=key)
            manager = api.Actor('custom-manager', frozenset({'CustomManager'}), frozenset({key}))
            self.assertEqual(api.close_calendar(actor=manager, calendar_key=key), key)
        with self.settings(DIARY_PERMISSION_GROUPS={}):
            with self.assertRaises(PermissionDenied):
                api.close_calendar(actor=self.officer, calendar_key=key)

    def test_closed_calendar_rejects_api_changes(self):
        key = self.calendar()
        api.close_calendar(actor=self.officer, calendar_key=key)
        operations = (
            lambda: api.add_entry(actor=self.officer, calendar_key=key,
                                  spec=api.EntrySpec('New task', DateKind.ONCE, fixed_date=date(2027, 7, 1))),
            lambda: api.set_milestone_dates(actor=self.officer, calendar_key=key,
                                            milestone_dates={'event_date': date(2027, 7, 1)}),
            lambda: api.set_predecessors(actor=self.officer, scope_key=key,
                                         entry_key=self.second.entry_key, predecessor_keys=[]),
        )
        before = api.get_calendar(actor=self.officer, calendar_key=key)
        for operation in operations:
            with self.assertRaisesMessage(ValidationError, 'This diary is closed.'):
                operation()
        self.assertEqual(api.get_calendar(actor=self.officer, calendar_key=key), before)

    def test_models_have_no_foreign_keys_to_other_apps(self):
        from django.apps import apps
        for model in apps.get_app_config('Diary').get_models():
            for field in model._meta.get_fields():
                if field.is_relation:
                    self.assertEqual(field.related_model._meta.app_label, 'Diary')

    def test_required_milestones_are_distinct_and_template_specific(self):
        duplicate = api.EntrySpec('Another board task', DateKind.RELATIVE,
                                  milestone_name='add_board_bookings_open', day_offset=-7)
        api.add_template_entry(actor=self.officer, template_version_key=self.version, spec=duplicate)
        result = api.required_milestones(actor=self.officer, template_version_key=self.version)
        self.assertEqual([m['name'] for m in result], ['add_board_bookings_open', 'event_date'])
        other = api.create_template_version(actor=self.officer, template_key=self.template, number=2)
        self.assertEqual(api.required_milestones(actor=self.officer, template_version_key=other), ())

    def test_calendar_creation_returns_a_stable_key_and_copies_rules_and_dependencies(self):
        key = self.calendar()
        self.assertEqual(self.calendar(), key)
        self.assertEqual(EventCalendar.objects.count(), 1)
        self.assertEqual(CalendarEntry.objects.count(), 3)
        entry = CalendarEntry.objects.get(calendar_id=key, entry_key=self.first.entry_key)
        self.assertEqual(entry.due_date, date(2027, 6, 12))
        successor = CalendarEntry.objects.get(calendar_id=key, entry_key=self.second.entry_key)
        self.assertEqual(list(successor.predecessors.values_list('entry_key', flat=True)), [self.first.entry_key])
        self.assertFalse(successor.is_ready)
        self.assertTrue(entry.is_ready)

    def test_missing_milestone_has_no_due_date_and_fixed_date_does_not_move(self):
        key = self.calendar(dates={})
        first = CalendarEntry.objects.get(calendar_id=key, entry_key=self.first.entry_key)
        self.assertIsNone(first.due_date)
        api.set_milestone_dates(actor=self.officer, calendar_key=key,
                                milestone_dates={'add_board_bookings_open': date(2027, 5, 8)})
        self.assertEqual(first.due_date, date(2027, 6, 19))
        annual = CalendarEntry.objects.get(calendar_id=key, entry_key=self.annual.entry_key)
        self.assertEqual(annual.due_date, date(2027, 3, 1))

    def test_leap_day_and_previous_year(self):
        leap = replace(self.annual, name='Leap day', entry_key=uuid4(), month=2, day=29)
        previous = replace(self.annual, name='Previous year', entry_key=uuid4(), month=12, day=1, year_offset=-1)
        for spec in (leap, previous):
            api.add_template_entry(actor=self.officer, template_version_key=self.version, spec=spec)
        key = self.calendar()
        self.assertIsNone(CalendarEntry.objects.get(calendar_id=key, entry_key=leap.entry_key).due_date)
        self.assertEqual(CalendarEntry.objects.get(calendar_id=key, entry_key=previous.entry_key).due_date, date(2026, 12, 1))

    def test_invalid_rules_and_one_time_template_dates_are_rejected(self):
        for spec in [replace(self.annual, day=31, month=4),
                     replace(self.first, milestone_name=''),
                     api.EntrySpec('Once', DateKind.ONCE, fixed_date=date(2027, 5, 1))]:
            with self.assertRaises(ValidationError):
                api.add_template_entry(actor=self.officer, template_version_key=self.version, spec=replace(spec, entry_key=uuid4()))

    def test_duplicate_names_and_keys_are_rejected(self):
        with self.assertRaises(ValidationError):
            api.add_template_entry(actor=self.officer, template_version_key=self.version,
                                    spec=replace(self.first, name=self.first.name.upper(), entry_key=uuid4()))
        self.assertEqual(api.add_template_entry(actor=self.officer, template_version_key=self.version, spec=self.first), self.first.entry_key)
        with self.assertRaises(ValidationError):
            api.add_template_entry(actor=self.officer, template_version_key=self.version, spec=replace(self.first, day_offset=99))

    def test_approved_versions_are_immutable(self):
        self.calendar()
        entry = TemplateEntry.objects.get(version_id=self.version, entry_key=self.first.entry_key)
        entry.name = 'Changed'
        with self.assertRaises(ValidationError):
            entry.save()
        version = TemplateVersion.objects.get(pk=self.version)
        version.number = 9
        with self.assertRaises(ValidationError):
            version.save()
        with self.assertRaises(ValidationError):
            api.set_predecessors(actor=self.officer, scope_key=self.version,
                                 entry_key=self.second.entry_key, predecessor_keys=[], template=True)

    def test_personal_entries_are_self_owned_and_repeat_calls_are_safe(self):
        key = self.calendar()
        spec = api.EntrySpec('My preparation', DateKind.ONCE, fixed_date=date(2027, 6, 1),
                              owner_kind=OwnerKind.PERSON, person_ref=self.exec_member.reference)
        result = api.add_entry(actor=self.exec_member, calendar_key=key, spec=spec)
        self.assertEqual(api.add_entry(actor=self.exec_member, calendar_key=key, spec=spec), result)
        for bad in [replace(spec, person_ref='person:1'), replace(spec, owner_kind=OwnerKind.TEAM, person_ref=''),
                    replace(spec, owner_kind=OwnerKind.ROLE, person_ref='', role_ref='SponsorshipManager')]:
            with self.assertRaises(PermissionDenied):
                api.add_entry(actor=self.exec_member, calendar_key=key, spec=replace(bad, entry_key=uuid4()))

    def test_officer_can_assign_person_role_and_whole_team(self):
        key = self.calendar()
        for index, spec in enumerate([
            api.EntrySpec('Person', DateKind.ANNUAL, month=1, day=1, owner_kind=OwnerKind.PERSON, person_ref='person:2'),
            api.EntrySpec('Role', DateKind.ANNUAL, month=1, day=1, owner_kind=OwnerKind.ROLE, role_ref='SponsorshipManager'),
            api.EntrySpec('Team', DateKind.ANNUAL, month=1, day=1),
        ]):
            api.add_entry(actor=self.officer, calendar_key=key, spec=spec, directory=Directory())
        with self.assertRaises(ValidationError):
            api.add_entry(actor=self.officer, calendar_key=key, directory=Directory(),
                          spec=api.EntrySpec('Invalid owner', DateKind.ANNUAL, month=1, day=1,
                                              owner_kind=OwnerKind.PERSON, person_ref='unknown'))

    def test_role_and_person_are_mutually_exclusive_at_database_level(self):
        key = self.calendar()
        entry = CalendarEntry.objects.get(calendar_id=key, entry_key=self.first.entry_key)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CalendarEntry.objects.filter(pk=entry.pk).update(owner_kind='person', person_ref='p', role_ref='g')

    def test_permission_groups_are_configurable_and_missing_configuration_denies(self):
        with override_settings(DIARY_PERMISSION_GROUPS={}):
            with self.assertRaises(PermissionDenied):
                api.required_milestones(actor=self.officer, template_version_key=self.version)
        custom = api.Actor('custom:1', frozenset({'DiaryReviewer'}))
        with override_settings(DIARY_PERMISSION_GROUPS={'view_template': ['DiaryReviewer']}):
            self.assertEqual(len(api.required_milestones(actor=custom, template_version_key=self.version)), 2)
        with override_settings(DIARY_PERMISSION_GROUPS={'view_template': 'Officer'}):
            with self.assertRaises(ValidationError):
                api.permission_groups()

    def test_view_and_calendar_scope_are_checked(self):
        key = self.calendar()
        with self.assertRaises(PermissionDenied):
            api.get_calendar(actor=replace(self.exec_member, calendar_keys=frozenset()), calendar_key=key)
        with self.assertRaises(PermissionDenied):
            api.required_milestones(actor=self.exec_member, template_version_key=self.version)
        result = api.get_calendar(actor=self.exec_member, calendar_key=key)
        self.assertEqual(result['key'], key)
        self.assertEqual(len(result['entries']), 3)

    def test_selector_excludes_self_and_transitive_successors(self):
        api.set_predecessors(actor=self.officer, scope_key=self.version, entry_key=self.annual.entry_key,
                             predecessor_keys=[self.second.entry_key], template=True)
        self.assertEqual(api.available_predecessors(actor=self.officer, scope_key=self.version,
                         entry_key=self.first.entry_key, template=True), ())
        choices = api.available_predecessors(actor=self.officer, scope_key=self.version,
                                             entry_key=self.annual.entry_key, template=True)
        self.assertEqual({item['entry_key'] for item in choices}, {self.first.entry_key, self.second.entry_key})
        with self.assertRaises(ValidationError):
            api.set_predecessors(actor=self.officer, scope_key=self.version, entry_key=self.first.entry_key,
                                 predecessor_keys=[self.annual.entry_key], template=True)

    def test_cross_calendar_links_and_self_links_are_rejected(self):
        key = self.calendar()
        other = self.calendar(ref='event:2028')
        first = CalendarEntry.objects.get(calendar_id=key, entry_key=self.first.entry_key)
        second = CalendarEntry.objects.get(calendar_id=other, entry_key=self.second.entry_key)
        for predecessor in (first, second):
            with self.assertRaises(ValidationError):
                EntryDependency.objects.create(entry=first, predecessor=predecessor)

    def test_failed_dependency_replacement_keeps_original_links(self):
        with self.assertRaises(ValidationError):
            api.set_predecessors(actor=self.officer, scope_key=self.version, entry_key=self.second.entry_key,
                                 predecessor_keys=[self.second.entry_key], template=True)
        entry = TemplateEntry.objects.get(version_id=self.version, entry_key=self.second.entry_key)
        self.assertEqual(list(entry.predecessors.values_list('entry_key', flat=True)), [self.first.entry_key])

    def test_failed_calendar_creation_is_atomic(self):
        api.approve_template_version(actor=self.officer, template_version_key=self.version)
        with self.assertRaises(Milestone.DoesNotExist):
            api.create_calendar(actor=self.officer, template_version_key=self.version, event_ref='bad',
                                 name='Bad calendar', event_year=2027,
                                 milestone_dates={'unknown': date(2027, 1, 1)})
        self.assertFalse(EventCalendar.objects.exists())

    def test_active_tasks_can_be_blocked_and_late_and_exclude_completed_tasks(self):
        key = self.calendar()
        entries = {item['entry_key']: item for item in api.active_tasks(
            actor=self.exec_member, calendar_key=key, today=date(2027, 7, 1))}
        self.assertEqual(entries[self.second.entry_key]['state'], 'blocked')
        self.assertTrue(entries[self.second.entry_key]['late'])
        self.assertEqual(entries[self.first.entry_key]['state'], 'ready')
        first = CalendarEntry.objects.get(calendar_id=key, entry_key=self.first.entry_key)
        first.completed_at = timezone.now()
        first.completed_by_ref = self.officer.reference
        first.save()
        entries = {item['entry_key']: item for item in api.active_tasks(
            actor=self.exec_member, calendar_key=key, today=date(2027, 6, 27))}
        self.assertNotIn(self.first.entry_key, entries)
        self.assertEqual(entries[self.second.entry_key]['state'], 'ready')
        self.assertTrue(entries[self.second.entry_key]['late'])

    def test_task_list_marks_missing_dates_and_has_constant_query_count(self):
        key = self.calendar(dates={})
        with self.assertNumQueries(4):
            result = api.active_tasks(actor=self.exec_member, calendar_key=key, today=date(2027, 1, 1))
        entry = next(item for item in result if item['entry_key'] == self.first.entry_key)
        self.assertTrue(entry['date_not_set'])
        self.assertFalse(entry['late'])
        for index in range(5):
            api.add_entry(actor=self.officer, calendar_key=key,
                          spec=api.EntrySpec(f'Extra {index}', DateKind.ANNUAL, month=1, day=1))
        with self.assertNumQueries(4):
            api.active_tasks(actor=self.exec_member, calendar_key=key, today=date(2027, 1, 1))

    def test_personal_tasks_include_matching_roles_without_duplicate_entries(self):
        key = self.calendar()
        mine = api.EntrySpec('My task', DateKind.ANNUAL, month=5, day=1,
                              owner_kind=OwnerKind.PERSON, person_ref=self.exec_member.reference)
        role = api.EntrySpec('Role task', DateKind.ANNUAL, month=5, day=1,
                              owner_kind=OwnerKind.ROLE, role_ref='SponsorshipManager')
        other = replace(mine, name='Another person task', person_ref=self.officer.reference, entry_key=uuid4())
        for spec in (mine, role, other):
            api.add_entry(actor=self.officer, calendar_key=key, spec=spec, directory=Directory())
        member = replace(self.exec_member, groups=frozenset({'ExecMember', 'SponsorshipManager'}))
        tasks = api.personal_tasks(actor=member, calendar_key=key, today=date(2027, 1, 1))
        self.assertEqual({item['entry_key'] for item in tasks}, {mine.entry_key, role.entry_key})
        tasks = api.personal_tasks(actor=self.exec_member, calendar_key=key, today=date(2027, 1, 1))
        self.assertEqual([item['entry_key'] for item in tasks], [mine.entry_key])

    def test_completed_due_date_stays_fixed_when_milestone_changes(self):
        key = self.calendar()
        entry = CalendarEntry.objects.get(calendar_id=key, entry_key=self.first.entry_key)
        entry.completed_at = timezone.now()
        entry.completed_by_ref = self.officer.reference
        entry.save()
        api.set_milestone_dates(actor=self.officer, calendar_key=key,
                                milestone_dates={'add_board_bookings_open': date(2027, 5, 15)})
        entry.refresh_from_db()
        self.assertEqual(entry.due_date, date(2027, 6, 12))
        entry.name = 'Changed completed task'
        with self.assertRaises(ValidationError):
            entry.save()

    def test_no_persistent_readiness_or_lateness_flags(self):
        names = {field.name for field in CalendarEntry._meta.fields}
        self.assertFalse(names & {'late', 'is_late', 'ready', 'is_ready', 'blocked'})

    @override_settings(DIARY_TEMPLATE_NAME='Standard calendar')
    def test_default_template_name_selects_latest_approved_version(self):
        self.calendar()
        self.assertEqual(len(api.required_milestones(actor=self.officer)), 2)
        second = api.create_template_version(actor=self.officer, template_key=self.template, number=2)
        self.assertEqual(api.get_template_version(actor=self.officer)['key'], self.version)
        api.add_template_entry(actor=self.officer, template_version_key=second,
                               spec=api.EntrySpec('Other date', DateKind.SOURCE, milestone_name='unused_date'))
        api.approve_template_version(actor=self.officer, template_version_key=second)
        self.assertEqual([m['name'] for m in api.required_milestones(actor=self.officer)], ['unused_date'])
        key = api.create_calendar(actor=self.officer, event_ref='new-default', name='New default',
                                   event_year=2028, milestone_dates={'unused_date': date(2028, 1, 1)})
        self.assertEqual(EventCalendar.objects.get(pk=key).template_version_id, second)
        self.assertEqual(EventCalendar.objects.get(event_ref='event:2027').template_version_id, self.version)

    def test_missing_configured_template_has_a_clear_error(self):
        with override_settings(DIARY_TEMPLATE_NAME='Unknown template'):
            with self.assertRaises(ValidationError):
                api.required_milestones(actor=self.officer)
        with override_settings(DIARY_TEMPLATE_NAME=''):
            with self.assertRaises(ValidationError):
                api.get_template_version(actor=self.officer)

    @override_settings(DIARY_TEMPLATE_NAME='Reusable project calendar')
    def test_template_creation_uses_the_configured_name(self):
        from Diary.models import CalendarTemplate
        key = api.create_template(actor=self.officer)
        self.assertEqual(CalendarTemplate.objects.get(pk=key).name, 'Reusable project calendar')

    def test_documented_setup_and_callable_examples_execute(self):
        import re
        from pathlib import Path
        guide = (Path(__file__).resolve().parents[1] / 'README.md').read_text()
        setup = guide.split('This is a complete first setup example.', 1)[1]
        code = re.search(r'```python\n(.*?)```', setup, re.S).group(1)
        namespace = {}
        exec(compile(code, 'Diary/README.md setup example', 'exec'), namespace)
        examples = guide.split('## More callable examples', 1)[1].split('## Ownership', 1)[0]
        for index, match in enumerate(re.finditer(r'```python\n(.*?)```', examples, re.S)):
            exec(compile(match.group(1), f'Diary/README.md example {index}', 'exec'), namespace)
