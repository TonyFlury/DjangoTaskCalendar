"""DV1-043: Verify the milestone boundary through API, model, and PostgreSQL operations."""
from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from Diary.models import CalendarMilestone
from Diary.tests.test_task_creation import TaskCreationFixtures


@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',))
class LiveMilestoneTests(TaskCreationFixtures, TestCase):
    """Keep saved milestone rows unchanged after diary creation."""

    def test_api_and_model_reject_changes(self):
        """Reject open-diary edits and preserve the original milestone date."""
        row = CalendarMilestone.objects.get(calendar_id=self.diary.key)
        original = row.date
        with self.assertRaisesMessage(ValidationError, 'V1 does not allow milestone changes'):
            self.diary.set_milestone_dates(milestone_dates={'target': date(2030, 1, 1)})
        row.date = date(2030, 1, 1)
        with self.assertRaises(ValidationError):
            row.save()
        with self.assertRaises(ValidationError):
            row.delete()
        row.refresh_from_db()
        self.assertEqual(row.date, original)

    def test_database_rejects_bulk_changes_and_late_insertions(self):
        """Reject queryset writes without bypassing the PostgreSQL guards."""
        row = CalendarMilestone.objects.get(calendar_id=self.diary.key)
        before = list(CalendarMilestone.objects.order_by('pk').values())
        with self.assertRaises(IntegrityError), transaction.atomic():
            CalendarMilestone.objects.filter(pk=row.pk).update(date=date(2030, 1, 1))
        with self.assertRaises(IntegrityError), transaction.atomic():
            CalendarMilestone.objects.filter(pk=row.pk).delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CalendarMilestone.objects.bulk_create([
                CalendarMilestone(calendar_id=self.diary.key, milestone_id=row.milestone_id, date=None)])
        self.assertEqual(list(CalendarMilestone.objects.order_by('pk').values()), before)
