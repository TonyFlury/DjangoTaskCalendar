"""DV1-040: Verify explicit ownership recovery without changing task dates or identity."""
from dataclasses import replace
from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings

from Diary.api import DiaryAPI, EntrySpec
from Diary.choices import DateKind, OwnerKind
from Diary.models import CalendarEntry, TemplateVersion
from Diary.tests.test_task_creation import TaskCreationFixtures
from Diary.views import DjangoOwnerDirectory


@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',))
class OwnershipRecoveryTests(TaskCreationFixtures, TestCase):
    """Check manager recovery, replacement eligibility, stale input, and template transaction rollback."""

    def orphan(self):
        """Assign a template copy to a person and remove that person's DiaryUser membership."""
        entry = CalendarEntry.objects.get(calendar_id=self.diary.key, entry_key=self.first.entry_key)
        entry.owner_kind = OwnerKind.PERSON
        entry.person_ref = f'user:{self.other.pk}'
        entry.save()
        self.other.groups.clear()
        return entry

    def recover(self, entry, **kwargs):
        """Request whole-team recovery with the inspected revision and optional template settings."""
        return self.diary.reassign_task(entry_key=entry.entry_key, owner_kind=OwnerKind.TEAM,
                                       expected_revision=entry.revision, directory=DjangoOwnerDirectory(), **kwargs)

    def test_recovery_preserves_dates_and_rejects_repeated_or_unauthorized_edits(self):
        """Keep task dates and identity while requiring current orphan status and manager scope."""
        entry = self.orphan()
        user = replace(self.actor, reference=f'user:{self.user.pk}', groups=frozenset({'Participants'}))
        with self.assertRaises(PermissionDenied):
            DiaryAPI(actor=user).diary(key=self.diary.key).reassign_task(
                entry_key=entry.entry_key, owner_kind=OwnerKind.TEAM, expected_revision=entry.revision)
        self.recover(entry)
        entry.refresh_from_db()
        self.assertEqual(entry.owner_kind, OwnerKind.TEAM)
        self.assertEqual(entry.due_date, date(2027, 6, 20))
        self.assertEqual(entry.revision, 1)
        with self.assertRaisesMessage(ValidationError, 'no longer orphaned'):
            self.recover(entry)

    def test_missing_template_task_rolls_back_diary_reassignment(self):
        """Preserve ownership and revisions when the requested template change cannot complete."""
        entry = self.orphan()
        self.template.save_version(entries=(self.second,), predecessors={self.second.entry_key: ()},
            expected_version_key=self.version.key, directory=DjangoOwnerDirectory())
        count = TemplateVersion.objects.count()
        with self.assertRaisesMessage(ValidationError, 'absent from the latest template'):
            self.recover(entry, update_template=True, expected_version_key=self.version.key)
        entry.refresh_from_db()
        self.assertEqual(entry.owner_kind, OwnerKind.PERSON)
        self.assertEqual(entry.revision, 0)
        self.assertEqual(TemplateVersion.objects.count(), count)

    def test_replacement_role_requires_eligible_active_members(self):
        """Reject a configured role whose remaining members have no Diary access."""
        entry = self.orphan()
        self.user.groups.clear()
        with self.assertRaisesMessage(ValidationError, 'active eligible person'):
            self.diary.reassign_task(entry_key=entry.entry_key, owner_kind=OwnerKind.ROLE,
                role_ref='Helpers', expected_revision=entry.revision, directory=DjangoOwnerDirectory())
        entry.refresh_from_db()
        self.assertEqual(entry.owner_kind, OwnerKind.PERSON)

    def test_recovery_rejects_stale_revision_and_closed_diary(self):
        """Reject stale form values and changes after diary closure."""
        entry = self.orphan()
        with self.assertRaisesMessage(ValidationError, 'changed or completed'):
            self.diary.reassign_task(entry_key=entry.entry_key, owner_kind=OwnerKind.TEAM,
                expected_revision=entry.revision + 1, directory=DjangoOwnerDirectory())
        self.diary.close()
        with self.assertRaisesMessage(ValidationError, 'This diary is closed'):
            self.recover(entry)

    def test_template_recovery_preserves_other_diaries_and_template_fields(self):
        """Approve one ownership revision while retaining dates, graph links, and existing diary copies."""
        directory = DjangoOwnerDirectory()
        spec = replace(self.first, owner_kind=OwnerKind.PERSON, person_ref=f'user:{self.other.pk}')
        version = self.template.save_version(entries=(spec, self.second),
            predecessors={self.first.entry_key: (), self.second.entry_key: (self.first.entry_key,)},
            expected_version_key=self.version.key, directory=directory)
        unscoped = replace(self.actor, calendar_keys=frozenset())
        diary = DiaryAPI(actor=unscoped).create_diary(name='Recovery snapshot', milestone_dates={'target': date(2027, 6, 20)},
                                                    template_version_key=version.key)
        scoped = replace(self.actor, calendar_keys=frozenset({diary.key}))
        diary = DiaryAPI(actor=scoped).diary(key=diary.key)
        entry = CalendarEntry.objects.get(calendar_id=diary.key, entry_key=self.first.entry_key)
        self.other.groups.clear()
        diary.reassign_task(entry_key=entry.entry_key, owner_kind=OwnerKind.TEAM,
            expected_revision=entry.revision, update_template=True, expected_version_key=version.key,
            directory=directory)
        latest = self.template.editor_data()
        revised = next(item for item in latest['entries'] if item['entry_key'] == self.first.entry_key)
        self.assertEqual(revised['owner_kind'], OwnerKind.TEAM)
        self.assertEqual(revised['milestone_name'], self.first.milestone_name)
        self.assertEqual(CalendarEntry.objects.get(calendar_id=self.diary.key,
            entry_key=self.first.entry_key).owner_kind, OwnerKind.TEAM)
        self.assertEqual(version.key, CalendarEntry.objects.get(pk=entry.pk).calendar.template_version_id)

    def test_diary_additions_are_not_orphaned_or_reassigned(self):
        """Exclude personally added tasks from template ownership recovery."""
        spec = EntrySpec('Private addition', DateKind.ONCE, fixed_date=date(2027, 6, 20),
                         owner_kind=OwnerKind.PERSON, person_ref=f'user:{self.other.pk}')
        self.diary.add_entry(spec=spec, directory=DjangoOwnerDirectory())
        self.other.groups.clear()
        entry = CalendarEntry.objects.get(calendar_id=self.diary.key, entry_key=spec.entry_key)
        with self.assertRaisesMessage(ValidationError, 'no longer orphaned'):
            self.recover(entry)

    def test_manager_only_person_is_not_a_replacement(self):
        """Require DiaryUser membership even when a proposed person has manager access."""
        entry = self.orphan()
        with self.assertRaisesMessage(ValidationError, 'active eligible person'):
            self.diary.reassign_task(entry_key=entry.entry_key, owner_kind=OwnerKind.PERSON,
                person_ref=f'user:{self.manager.pk}', expected_revision=entry.revision,
                directory=DjangoOwnerDirectory())

    def test_restored_membership_prevents_stale_recovery(self):
        """Repeat current membership checks before changing an inspected orphan assignment."""
        from django.contrib.auth.models import Group
        entry = self.orphan()
        self.other.groups.add(Group.objects.get(name='Participants'))
        with self.assertRaisesMessage(ValidationError, 'no longer orphaned'):
            self.recover(entry)


@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',),
                   ROOT_URLCONF='Diary.tests.test_task_editing')
class ManagerOwnershipRecoveryTests(TaskCreationFixtures, TestCase):
    """DV1-040: Verify the manager list and its scoped, explicit ownership form."""

    orphan = OwnershipRecoveryTests.orphan

    def setUp(self):
        """Supply the manager route with trusted scope and an authenticated manager."""
        super().setUp()
        self.scope = override_settings(EDIT_TEST_KEYS=(self.diary.key,))
        self.scope.enable()
        self.addCleanup(self.scope.disable)
        self.client.force_login(self.manager)
        self.url = f'/host/manager/?diary_key={self.diary.key}'

    def test_orphaned_template_tasks_sort_first_and_get_does_not_reassign(self):
        """Put a later orphan before earlier tasks while preserving ownership and blocking."""
        entry = self.orphan()
        entry.due_date_override = date(2030, 1, 1)
        entry.save()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['tasks'][0]['entry_key'], entry.entry_key)
        self.assertTrue(response.context['tasks'][0]['orphaned'])
        self.assertNotContains(response, 'diary-recovery-form')
        detail = self.client.get(f'/host/tasks/{entry.entry_key}/?diary_key={self.diary.key}')
        self.assertContains(detail, 'Assign owner')
        self.assertContains(response, 'Tasks that depend on it remain blocked.')
        entry.refresh_from_db()
        self.assertEqual(entry.person_ref, f'user:{self.other.pk}')
        self.assertTrue(self.diary.task(entry_key=self.second.entry_key)['blocking_predecessors'])

    def test_form_reassigns_to_user_and_rejects_manager_only_person(self):
        """Accept a DiaryUser replacement and reject a forged manager-only reference."""
        entry = self.orphan()
        url = f'/host/tasks/{entry.entry_key}/?diary_key={self.diary.key}'
        values = {'action': 'save_owner', 'entry_key': entry.entry_key, 'revision': entry.revision,
                  'owner_kind': OwnerKind.PERSON, 'person_ref': f'user:{self.manager.pk}'}
        self.assertEqual(self.client.post(url, values).status_code, 400)
        values['person_ref'] = f'user:{self.user.pk}'
        self.assertEqual(self.client.post(url, values).status_code, 302)
        entry.refresh_from_db()
        self.assertEqual(entry.person_ref, f'user:{self.user.pk}')
        self.assertEqual(self.client.post(url, values).status_code, 400)

    def test_user_and_untrusted_scope_cannot_reassign(self):
        """Reject ordinary users and manager requests outside trusted diary scope."""
        entry = self.orphan()
        url = f'/host/tasks/{entry.entry_key}/?diary_key={self.diary.key}'
        values = {'action': 'save_owner', 'entry_key': entry.entry_key, 'revision': entry.revision, 'owner_kind': OwnerKind.TEAM}
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(url, values).status_code, 403)
        self.client.force_login(self.manager)
        with self.settings(EDIT_TEST_KEYS=()):
            self.assertEqual(self.client.post(url, values).status_code, 403)
        entry.refresh_from_db()
        self.assertEqual(entry.owner_kind, OwnerKind.PERSON)
