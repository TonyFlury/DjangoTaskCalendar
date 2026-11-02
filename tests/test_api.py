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
    DIARY_TASK_OWNER_ROLES=('SponsorshipManager',),
)
class DiaryTests(TestCase):
    def setUp(self):
        self.officer = api.Actor('person:1', frozenset({'Officer', 'ExecMember'}))
        self.exec_member = api.Actor('person:2', frozenset({'ExecMember'}))
        api.DiaryAPI(actor=self.officer).define_milestones(
            definitions={'event_date': 'Event date', 'add_board_bookings_open': 'Advertising board bookings open',
                         'unused_date': 'Unused date'})
        self.template = api.DiaryTemplate.create(actor=self.officer, name='Standard calendar').key
        self.version = api.DiaryTemplate.from_key(actor=self.officer, key=self.template).create_version(number=1).key
        self.first = api.EntrySpec('Prepare boards', DateKind.RELATIVE, milestone_name='add_board_bookings_open',
                                   day_offset=42)
        self.second = api.EntrySpec('Inspect boards', DateKind.SOURCE, milestone_name='event_date')
        self.annual = api.EntrySpec('Annual check', DateKind.ANNUAL, month=3, day=1)
        for spec in (self.first, self.second, self.annual):
            api.DiaryTemplateVersion.from_key(actor=self.officer, key=self.version).add_entry(spec=spec)
        api.DiaryTemplateVersion.from_key(actor=self.officer, key=self.version).set_predecessors(
            entry_key=self.second.entry_key, predecessor_keys=[self.first.entry_key])

    def calendar(self, ref='event:2027', dates=None):
        api.DiaryTemplateVersion.from_key(actor=self.officer, key=self.version).approve()
        key = api.DiaryInstance.create(actor=self.officer, template_version_key=self.version, event_ref=ref,
                                       name='June event', event_year=2027,
                                       milestone_dates=dates if dates is not None else {'event_date': date(2027, 6, 27),
                                                                                        'add_board_bookings_open': date(
                                                                                            2027, 5, 1)}).key
        self.officer = replace(self.officer, calendar_keys=frozenset({key}))
        self.exec_member = replace(self.exec_member, calendar_keys=frozenset({key}))
        return key

    def test_postgresql(self):
        self.assertEqual(connection.vendor, 'postgresql')

    def test_close_calendar_preserves_open_tasks_and_completion_records(self):
        key = self.calendar()
        personal = api.EntrySpec('My open task', DateKind.ONCE, fixed_date=date(2027, 6, 1),
                                 owner_kind=OwnerKind.PERSON, person_ref=self.exec_member.reference)
        api.DiaryInstance.from_key(actor=self.exec_member, key=key).add_entry(spec=personal)
        completed = CalendarEntry.objects.get(calendar_id=key, entry_key=self.annual.entry_key)
        completed.completed_at = timezone.now()
        completed.completed_by_ref = self.officer.reference
        completed.completed_due_date = completed.due_date
        completed.save()
        before = list(CalendarEntry.objects.filter(calendar_id=key).order_by('pk').values())
        milestones = list(CalendarMilestone.objects.filter(calendar_id=key).order_by('pk').values())
        dependencies = list(EntryDependency.objects.filter(entry__calendar_id=key).order_by('pk').values())
        self.assertTrue(api.DiaryInstance.from_key(actor=self.exec_member, key=key).personal_tasks())

        self.assertEqual(api.DiaryInstance.from_key(actor=self.officer, key=key).close().key, key)

        result = api.DiaryInstance.from_key(actor=self.officer, key=key).read()
        self.assertTrue(result['closed'])
        self.assertIsNotNone(result['closed_at'])
        self.assertEqual(result['closed_by_ref'], self.officer.reference)
        self.assertEqual(len(result['entries']), 4)
        self.assertEqual(list(CalendarEntry.objects.filter(calendar_id=key).order_by('pk').values()), before)
        self.assertEqual(list(CalendarMilestone.objects.filter(calendar_id=key).order_by('pk').values()), milestones)
        self.assertEqual(list(EntryDependency.objects.filter(entry__calendar_id=key).order_by('pk').values()),
                         dependencies)
        self.assertEqual(api.DiaryInstance.from_key(actor=self.officer, key=key).active_tasks(), ())
        self.assertEqual(api.DiaryInstance.from_key(actor=self.exec_member, key=key).personal_tasks(), ())

    def test_close_calendar_is_idempotent_and_does_not_reopen_on_creation_retry(self):
        key = self.calendar()
        api.DiaryInstance.from_key(actor=self.officer, key=key).close()
        original = api.DiaryInstance.from_key(actor=self.officer, key=key).read()
        other_manager = replace(self.officer, reference='another-manager')
        self.assertEqual(api.DiaryInstance.from_key(actor=other_manager, key=str(key)).close().key, key)
        self.assertEqual(api.DiaryInstance.from_key(actor=self.officer, key=key).read(), original)
        self.assertEqual(self.calendar(), key)
        self.assertTrue(api.DiaryInstance.from_key(actor=self.officer, key=key).read()['closed'])

    def test_close_calendar_requires_configured_edit_access_and_host_scope(self):
        key = self.calendar()
        for actor in (self.exec_member, replace(self.officer, calendar_keys=frozenset())):
            with self.assertRaises(PermissionDenied):
                api.DiaryInstance.from_key(actor=actor, key=key).close()
        self.assertFalse(EventCalendar.objects.get(pk=key).closed_at)
        with self.settings(DIARY_PERMISSION_GROUPS={'edit': ('CustomManager',)}):
            with self.assertRaises(PermissionDenied):
                api.DiaryInstance.from_key(actor=self.officer, key=key).close()
            manager = api.Actor('custom-manager', frozenset({'CustomManager'}), frozenset({key}))
            self.assertEqual(api.DiaryInstance.from_key(actor=manager, key=key).close().key, key)
        with self.settings(DIARY_PERMISSION_GROUPS={}):
            with self.assertRaises(PermissionDenied):
                api.DiaryInstance.from_key(actor=self.officer, key=key).close()

    def test_closed_calendar_rejects_api_changes(self):
        key = self.calendar()
        api.DiaryInstance.from_key(actor=self.officer, key=key).close()
        operations = (
            lambda: api.DiaryInstance.from_key(actor=self.officer, key=key).add_entry(
                spec=api.EntrySpec('New task', DateKind.ONCE, fixed_date=date(2027, 7, 1))),
            lambda: api.DiaryInstance.from_key(actor=self.officer, key=key).set_milestone_dates(
                milestone_dates={'event_date': date(2027, 7, 1)}),
            lambda: api.DiaryInstance.from_key(actor=self.officer, key=key).set_predecessors(
                entry_key=self.second.entry_key, predecessor_keys=[]),
        )
        before = api.DiaryInstance.from_key(actor=self.officer, key=key).read()
        for operation in operations:
            with self.assertRaisesMessage(ValidationError, 'This diary is closed.'):
                operation()
        self.assertEqual(api.DiaryInstance.from_key(actor=self.officer, key=key).read(), before)

    def test_models_have_no_foreign_keys_to_other_apps(self):
        from django.apps import apps
        for model in apps.get_app_config('Diary').get_models():
            for field in model._meta.get_fields():
                if field.is_relation:
                    self.assertEqual(field.related_model._meta.app_label, 'Diary')

    def test_required_milestones_are_distinct_and_template_specific(self):
        duplicate = api.EntrySpec('Another board task', DateKind.RELATIVE, milestone_name='add_board_bookings_open',
                                  day_offset=-7)
        api.DiaryTemplateVersion.from_key(actor=self.officer, key=self.version).add_entry(spec=duplicate)
        result = api.DiaryAPI(actor=self.officer).template_version(key=self.version).required_milestones()
        self.assertEqual([m['name'] for m in result], ['add_board_bookings_open', 'event_date'])
        other = api.DiaryTemplate.from_key(actor=self.officer, key=self.template).create_version(number=2).key
        self.assertEqual(api.DiaryAPI(actor=self.officer).template_version(key=other).required_milestones(), ())

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
        api.DiaryInstance.from_key(actor=self.officer, key=key).set_milestone_dates(
            milestone_dates={'add_board_bookings_open': date(2027, 5, 8)})
        self.assertEqual(first.due_date, date(2027, 6, 19))
        annual = CalendarEntry.objects.get(calendar_id=key, entry_key=self.annual.entry_key)
        self.assertEqual(annual.due_date, date(2027, 3, 1))

    def test_leap_day_and_previous_year(self):
        leap = replace(self.annual, name='Leap day', entry_key=uuid4(), month=2, day=29)
        previous = replace(self.annual, name='Previous year', entry_key=uuid4(), month=12, day=1, year_offset=-1)
        for spec in (leap, previous):
            api.DiaryTemplateVersion.from_key(actor=self.officer, key=self.version).add_entry(spec=spec)
        key = self.calendar()
        self.assertIsNone(CalendarEntry.objects.get(calendar_id=key, entry_key=leap.entry_key).due_date)
        self.assertEqual(CalendarEntry.objects.get(calendar_id=key, entry_key=previous.entry_key).due_date,
                         date(2026, 12, 1))

    def test_invalid_rules_and_one_time_template_dates_are_rejected(self):
        for spec in [replace(self.annual, day=31, month=4),
                     replace(self.first, milestone_name=''),
                     api.EntrySpec('Once', DateKind.ONCE, fixed_date=date(2027, 5, 1))]:
            with self.assertRaises(ValidationError):
                api.DiaryTemplateVersion.from_key(actor=self.officer, key=self.version).add_entry(
                    spec=replace(spec, entry_key=uuid4()))

    def test_duplicate_names_and_keys_are_rejected(self):
        with self.assertRaises(ValidationError):
            api.DiaryTemplateVersion.from_key(actor=self.officer, key=self.version).add_entry(
                spec=replace(self.first, name=self.first.name.upper(), entry_key=uuid4()))
        self.assertEqual(
            api.DiaryTemplateVersion.from_key(actor=self.officer, key=self.version).add_entry(spec=self.first),
            self.first.entry_key)
        with self.assertRaises(ValidationError):
            api.DiaryTemplateVersion.from_key(actor=self.officer, key=self.version).add_entry(
                spec=replace(self.first, day_offset=99))

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
            api.DiaryTemplateVersion.from_key(actor=self.officer, key=self.version).set_predecessors(
                entry_key=self.second.entry_key, predecessor_keys=[])

    def test_personal_entries_are_self_owned_and_repeat_calls_are_safe(self):
        key = self.calendar()
        spec = api.EntrySpec('My preparation', DateKind.ONCE, fixed_date=date(2027, 6, 1), owner_kind=OwnerKind.PERSON,
                             person_ref=self.exec_member.reference)
        result = api.DiaryInstance.from_key(actor=self.exec_member, key=key).add_entry(spec=spec)
        self.assertEqual(api.DiaryInstance.from_key(actor=self.exec_member, key=key).add_entry(spec=spec), result)
        for bad in [replace(spec, person_ref='person:1'), replace(spec, owner_kind=OwnerKind.TEAM, person_ref=''),
                    replace(spec, owner_kind=OwnerKind.ROLE, person_ref='', role_ref='SponsorshipManager')]:
            with self.assertRaises(PermissionDenied):
                api.DiaryInstance.from_key(actor=self.exec_member, key=key).add_entry(
                    spec=replace(bad, entry_key=uuid4()))

    def test_officer_can_assign_person_role_and_whole_team(self):
        key = self.calendar()
        for index, spec in enumerate([
            api.EntrySpec('Person', DateKind.ANNUAL, month=1, day=1, owner_kind=OwnerKind.PERSON,
                          person_ref='person:2'),
            api.EntrySpec('Role', DateKind.ANNUAL, month=1, day=1, owner_kind=OwnerKind.ROLE,
                          role_ref='SponsorshipManager'),
            api.EntrySpec('Team', DateKind.ANNUAL, month=1, day=1),
        ]):
            api.DiaryInstance.from_key(actor=self.officer, key=key).add_entry(spec=spec, directory=Directory())
        with self.assertRaises(ValidationError):
            api.DiaryInstance.from_key(actor=self.officer, key=key).add_entry(directory=Directory(),
                                                                              spec=api.EntrySpec('Invalid owner',
                                                                                                 DateKind.ANNUAL,
                                                                                                 month=1, day=1,
                                                                                                 owner_kind=OwnerKind.PERSON,
                                                                                                 person_ref='unknown'))

    def test_role_and_person_are_mutually_exclusive_at_database_level(self):
        key = self.calendar()
        entry = CalendarEntry.objects.get(calendar_id=key, entry_key=self.first.entry_key)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CalendarEntry.objects.filter(pk=entry.pk).update(owner_kind='person', person_ref='p', role_ref='g')

    def test_role_assignment_requires_a_configured_role_for_entries_and_templates(self):
        key = self.calendar()
        spec = api.EntrySpec('Unconfigured role', DateKind.ANNUAL, month=1, day=1, owner_kind=OwnerKind.ROLE,
                             role_ref='SponsorshipManager')
        draft = api.DiaryTemplate.from_key(actor=self.officer, key=self.template).create_version(number=2).key
        with self.settings(DIARY_TASK_OWNER_ROLES=('AnotherRole',)):
            with self.assertRaisesMessage(ValidationError, 'DIARY_TASK_OWNER_ROLES'):
                api.DiaryInstance.from_key(actor=self.officer, key=key).add_entry(spec=spec, directory=Directory())
            with self.assertRaisesMessage(ValidationError, 'DIARY_TASK_OWNER_ROLES'):
                api.DiaryTemplateVersion.from_key(actor=self.officer, key=draft).add_entry(spec=spec,
                                                                                           directory=Directory())
        self.assertFalse(CalendarEntry.objects.filter(calendar_id=key, entry_key=spec.entry_key).exists())
        self.assertFalse(TemplateEntry.objects.filter(version_id=draft, entry_key=spec.entry_key).exists())

    def test_permission_groups_are_configurable_and_missing_configuration_denies(self):
        with override_settings(DIARY_PERMISSION_GROUPS={}):
            with self.assertRaises(PermissionDenied):
                api.DiaryAPI(actor=self.officer).template_version(key=self.version).required_milestones()
        custom = api.Actor('custom:1', frozenset({'DiaryReviewer'}))
        with override_settings(DIARY_PERMISSION_GROUPS={'view_template': ['DiaryReviewer']}):
            self.assertEqual(len(api.DiaryAPI(actor=custom).template_version(key=self.version).required_milestones()),
                             2)
        with override_settings(DIARY_PERMISSION_GROUPS={'view_template': 'Officer'}):
            with self.assertRaises(ValidationError):
                api.DiaryAPI.permission_groups()

    def test_view_and_calendar_scope_are_checked(self):
        key = self.calendar()
        with self.assertRaises(PermissionDenied):
            api.DiaryInstance.from_key(actor=replace(self.exec_member, calendar_keys=frozenset()), key=key).read()
        with self.assertRaises(PermissionDenied):
            api.DiaryAPI(actor=self.exec_member).template_version(key=self.version).required_milestones()
        result = api.DiaryInstance.from_key(actor=self.exec_member, key=key).read()
        self.assertEqual(result['key'], key)
        self.assertEqual(len(result['entries']), 3)

    def test_selector_excludes_self_and_transitive_successors(self):
        api.DiaryTemplateVersion.from_key(actor=self.officer, key=self.version).set_predecessors(
            entry_key=self.annual.entry_key, predecessor_keys=[self.second.entry_key])
        self.assertEqual(api.DiaryTemplateVersion.from_key(actor=self.officer, key=self.version).available_predecessors(
            entry_key=self.first.entry_key), ())
        choices = api.DiaryTemplateVersion.from_key(actor=self.officer, key=self.version).available_predecessors(
            entry_key=self.annual.entry_key)
        self.assertEqual({item['entry_key'] for item in choices}, {self.first.entry_key, self.second.entry_key})
        with self.assertRaises(ValidationError):
            api.DiaryTemplateVersion.from_key(actor=self.officer, key=self.version).set_predecessors(
                entry_key=self.first.entry_key, predecessor_keys=[self.annual.entry_key])

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
            api.DiaryTemplateVersion.from_key(actor=self.officer, key=self.version).set_predecessors(
                entry_key=self.second.entry_key, predecessor_keys=[self.second.entry_key])
        entry = TemplateEntry.objects.get(version_id=self.version, entry_key=self.second.entry_key)
        self.assertEqual(list(entry.predecessors.values_list('entry_key', flat=True)), [self.first.entry_key])

    def test_failed_calendar_creation_is_atomic(self):
        api.DiaryTemplateVersion.from_key(actor=self.officer, key=self.version).approve()
        with self.assertRaises(Milestone.DoesNotExist):
            api.DiaryInstance.create(actor=self.officer, template_version_key=self.version, event_ref='bad',
                                     name='Bad calendar', event_year=2027,
                                     milestone_dates={'unknown': date(2027, 1, 1)}).key
        self.assertFalse(EventCalendar.objects.exists())

    def test_active_tasks_can_be_blocked_and_late_and_exclude_completed_tasks(self):
        key = self.calendar()
        entries = {item['entry_key']: item for item in
                   api.DiaryInstance.from_key(actor=self.exec_member, key=key).active_tasks(today=date(2027, 7, 1))}
        self.assertEqual(entries[self.second.entry_key]['state'], 'blocked')
        self.assertTrue(entries[self.second.entry_key]['late'])
        self.assertEqual(entries[self.first.entry_key]['state'], 'ready')
        first = CalendarEntry.objects.get(calendar_id=key, entry_key=self.first.entry_key)
        first.completed_at = timezone.now()
        first.completed_by_ref = self.officer.reference
        first.save()
        entries = {item['entry_key']: item for item in
                   api.DiaryInstance.from_key(actor=self.exec_member, key=key).active_tasks(today=date(2027, 6, 27))}
        self.assertNotIn(self.first.entry_key, entries)
        self.assertEqual(entries[self.second.entry_key]['state'], 'ready')
        self.assertTrue(entries[self.second.entry_key]['late'])

    def test_task_list_marks_missing_dates_and_has_constant_query_count(self):
        key = self.calendar(dates={})
        diary = api.DiaryInstance.from_key(actor=self.exec_member, key=key)
        with self.assertNumQueries(4):
            result = diary.active_tasks(today=date(2027, 1, 1))
        entry = next(item for item in result if item['entry_key'] == self.first.entry_key)
        self.assertTrue(entry['date_not_set'])
        self.assertFalse(entry['late'])
        for index in range(5):
            api.DiaryInstance.from_key(actor=self.officer, key=key).add_entry(
                spec=api.EntrySpec(f'Extra {index}', DateKind.ANNUAL, month=1, day=1))
        with self.assertNumQueries(4):
            diary.active_tasks(today=date(2027, 1, 1))

    def test_personal_tasks_include_matching_roles_without_duplicate_entries(self):
        key = self.calendar()
        mine = api.EntrySpec('My task', DateKind.ANNUAL, month=5, day=1, owner_kind=OwnerKind.PERSON,
                             person_ref=self.exec_member.reference)
        role = api.EntrySpec('Role task', DateKind.ANNUAL, month=5, day=1, owner_kind=OwnerKind.ROLE,
                             role_ref='SponsorshipManager')
        other = replace(mine, name='Another person task', person_ref=self.officer.reference, entry_key=uuid4())
        for spec in (mine, role, other):
            api.DiaryInstance.from_key(actor=self.officer, key=key).add_entry(spec=spec, directory=Directory())
        member = replace(self.exec_member, groups=frozenset({'ExecMember', 'SponsorshipManager'}))
        tasks = api.DiaryInstance.from_key(actor=member, key=key).personal_tasks(today=date(2027, 1, 1))
        self.assertEqual({item['entry_key'] for item in tasks}, {mine.entry_key, role.entry_key})
        tasks = api.DiaryInstance.from_key(actor=self.exec_member, key=key).personal_tasks(today=date(2027, 1, 1))
        self.assertEqual([item['entry_key'] for item in tasks], [mine.entry_key])

    def test_completed_due_date_stays_fixed_when_milestone_changes(self):
        key = self.calendar()
        entry = CalendarEntry.objects.get(calendar_id=key, entry_key=self.first.entry_key)
        entry.completed_at = timezone.now()
        entry.completed_by_ref = self.officer.reference
        entry.save()
        api.DiaryInstance.from_key(actor=self.officer, key=key).set_milestone_dates(
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
        self.assertEqual(len(api.DiaryAPI(actor=self.officer).template_version().required_milestones()), 2)
        second = api.DiaryTemplate.from_key(actor=self.officer, key=self.template).create_version(number=2).key
        self.assertEqual(api.DiaryAPI(actor=self.officer).template_version().read()['key'], self.version)
        api.DiaryTemplateVersion.from_key(actor=self.officer, key=second).add_entry(
            spec=api.EntrySpec('Other date', DateKind.SOURCE, milestone_name='unused_date'))
        api.DiaryTemplateVersion.from_key(actor=self.officer, key=second).approve()
        self.assertEqual([m['name'] for m in api.DiaryAPI(actor=self.officer).template_version().required_milestones()],
                         ['unused_date'])
        key = api.DiaryInstance.create(actor=self.officer, event_ref='new-default', name='New default', event_year=2028,
                                       milestone_dates={'unused_date': date(2028, 1, 1)}).key
        self.assertEqual(EventCalendar.objects.get(pk=key).template_version_id, second)
        self.assertEqual(EventCalendar.objects.get(event_ref='event:2027').template_version_id, self.version)

    def test_missing_configured_template_has_a_clear_error(self):
        with override_settings(DIARY_TEMPLATE_NAME='Unknown template'):
            with self.assertRaises(ValidationError):
                api.DiaryAPI(actor=self.officer).template_version().required_milestones()
        with override_settings(DIARY_TEMPLATE_NAME=''):
            with self.assertRaises(ValidationError):
                api.DiaryAPI(actor=self.officer).template_version().read()

    @override_settings(DIARY_TEMPLATE_NAME='Reusable project calendar')
    def test_template_creation_uses_the_configured_name(self):
        from Diary.models import CalendarTemplate
        key = api.DiaryTemplate.create(actor=self.officer).key
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
