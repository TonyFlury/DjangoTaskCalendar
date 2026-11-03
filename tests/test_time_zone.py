"""Verify the optional Diary time zone at a local-date boundary."""
from datetime import date, datetime, timezone as datetime_timezone
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone

from Diary.api import Actor, DiaryAPI, EntrySpec
from Diary.choices import DateKind


# Verifies DV1-050: Optional Diary time zone with the project default.
@override_settings(DIARY_MANAGER='Managers', DIARY_USER='Users', DIARY_TASK_OWNER_ROLES=(),
                   TIME_ZONE='America/Los_Angeles')
class DiaryTimeZoneTests(TestCase):
    """Compare task lateness using project settings rather than the active user time zone."""

    def setUp(self):
        """Create one annual task due after midnight UTC but before midnight in Los Angeles."""
        actor = Actor('manager', frozenset({'Managers'}))
        client = DiaryAPI(actor=actor)
        template = client.create_template(name='Time zone test')
        version = template.create_version(number=1)
        version.add_entry(spec=EntrySpec('Annual task', DateKind.ANNUAL, month=1, day=1))
        version.approve()
        diary = client.create_diary(event_ref='time-zone:1', name='Time zone diary', event_year=2027,
                                    milestone_dates={}, template_version_key=version.key)
        scoped = Actor(actor.reference, actor.groups, frozenset({diary.key}))
        self.diary = DiaryAPI(actor=scoped).diary(key=diary.key)
        self.instant = datetime(2027, 1, 1, 0, 30, tzinfo=datetime_timezone.utc)

    def test_absent_override_uses_project_time_zone_despite_active_user_zone(self):
        """Use TIME_ZONE when the Diary setting is absent, even during user-zone activation."""
        with self.settings(DIARY_TIME_ZONE=None):
            del settings.DIARY_TIME_ZONE
            with timezone.override('Asia/Tokyo'), patch('Diary.api.timezone.now', return_value=self.instant):
                self.assertFalse(self.diary.active_tasks()[0]['late'])

    def test_configured_diary_zone_overrides_project_zone(self):
        """Use a configured Diary override when its local date differs from the project date."""
        with self.settings(DIARY_TIME_ZONE='Asia/Tokyo'):
            with patch('Diary.api.timezone.now', return_value=self.instant):
                self.assertTrue(self.diary.active_tasks()[0]['late'])

    def test_absent_override_follows_a_different_project_default(self):
        """Read the current project default rather than a fixed regional fallback."""
        with self.settings(DIARY_TIME_ZONE=None, TIME_ZONE='Asia/Tokyo'):
            del settings.DIARY_TIME_ZONE
            with timezone.override('America/Los_Angeles'), patch('Diary.api.timezone.now', return_value=self.instant):
                self.assertTrue(self.diary.active_tasks()[0]['late'])

    def test_explicit_comparison_date_preserves_caller_control(self):
        """Use the supplied date without computing today from either time zone."""
        with self.settings(DIARY_TIME_ZONE='Asia/Tokyo'):
            with patch('Diary.api.timezone.now', return_value=self.instant):
                self.assertFalse(self.diary.active_tasks(today=date(2026, 12, 31))[0]['late'])
