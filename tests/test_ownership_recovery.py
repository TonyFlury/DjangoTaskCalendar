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
        """Add a person task and remove its owner's access membership."""
        spec = EntrySpec('Lost owner', DateKind.ONCE, fixed_date=date(2027, 6, 20),
                         owner_kind=OwnerKind.PERSON, person_ref=f'user:{self.other.pk}')
        self.diary.add_entry(spec=spec, directory=DjangoOwnerDirectory())
        self.other.groups.clear()
        return CalendarEntry.objects.get(calendar_id=self.diary.key, entry_key=spec.entry_key)

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
        self.assertEqual(entry.fixed_date, date(2027, 6, 20))
        self.assertEqual(entry.revision, 1)
        with self.assertRaisesMessage(ValidationError, 'no longer orphaned'):
            self.recover(entry)

    def test_missing_template_task_rolls_back_diary_reassignment(self):
        """Preserve ownership and revisions when the requested template change cannot complete."""
        entry = self.orphan()
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
        diary = DiaryAPI(actor=unscoped).create_diary(name='Recovery snapshot', milestone_dates={},
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
