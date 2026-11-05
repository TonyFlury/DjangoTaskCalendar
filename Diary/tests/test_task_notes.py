"""Append-only notes preserve task state and enforce current assignment and scope."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from io import StringIO
from uuid import uuid4
from unittest.mock import patch

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, IntegrityError, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from Diary.api import Actor, DiaryAPI, EntrySpec
from Diary.choices import DateKind, OwnerKind
from Diary.models import CalendarEntry, EventCalendar, TaskNote
from Diary.tests.test_task_editing import TaskEditingFixtures
from Diary.views import TaskDetailView


class NoteFixtures(TaskEditingFixtures):
    def setUp(self):
        super().setUp()
        self.user.first_name, self.user.last_name = 'Alice', 'Smith'
        self.user.save()
        self.manager.first_name, self.manager.last_name = 'Mary', 'Jones'
        self.manager.save()

    def note_payload(self, **changes):
        page = self.client.get(self.task_url())
        self.assertEqual(page.status_code, 200)
        data = {'action': 'add_note', 'note_key': str(page.context['note_form']['note_key'].value()),
                'text': 'Work is progressing.', 'diary_target': page.context['diary_target']}
        data.update(changes)
        return data


@override_settings(ROOT_URLCONF='Diary.tests.test_task_editing', DIARY_MANAGER='Planners',
                   DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',))
class TaskNoteTests(NoteFixtures, TestCase):
    def test_notes_append_stamps_and_repeat_keys_preserve_originals(self):
        before = list(CalendarEntry.objects.order_by('pk').values())
        start = timezone.now()
        key = uuid4()
        first = self.user_diary.add_note(entry_key=self.personal, text='  First note\nMore detail  ', note_key=key)
        self.assertEqual(first['author_ref'], f'user:{self.user.pk}')
        self.assertEqual(first['author_label'], 'Alice Smith')
        self.assertGreaterEqual(first['created_at'], start)
        self.assertLessEqual(first['created_at'], timezone.now())
        self.assertEqual(first['text'], 'First note\nMore detail')
        replay = self.user_diary.add_note(entry_key=self.personal, text=first['text'], note_key=key)
        self.assertEqual(first, replay)
        second = self.diary.add_note(entry_key=self.personal, text='Manager note')
        self.assertEqual(second['author_label'], 'Mary Jones')
        self.assertEqual(self.user_diary.notes(entry_key=self.personal), (first, second))
        self.assertEqual(self.user_diary.task(entry_key=self.personal)['notes'], (first, second))
        self.assertEqual(list(CalendarEntry.objects.order_by('pk').values()), before)
        for text in ('changed', 'other'):
            with self.assertRaises(ValidationError):
                self.diary.add_note(entry_key=self.personal, text=text, note_key=key)
        self.assertEqual(TaskNote.objects.count(), 2)

    def test_completed_tasks_and_closed_diaries_still_accept_notes(self):
        self.user_diary.complete(entry_key=self.personal, expected_revision=0)
        self.diary.close()
        before = CalendarEntry.objects.get(entry_key=self.personal)
        self.user_diary.add_note(entry_key=self.personal, text='Follow-up after closure')
        self.diary.add_note(entry_key=self.personal, text='Manager follow-up')
        after = CalendarEntry.objects.get(entry_key=self.personal)
        self.assertEqual((before.revision, before.completed_at, before.completed_by_ref),
                         (after.revision, after.completed_at, after.completed_by_ref))
        page = self.client.get(self.task_url())
        self.assertContains(page, 'Follow-up after closure')
        self.assertContains(page, 'diary-note-form')
        self.assertNotContains(page, 'diary-detail-completion-form')
        self.assertEqual(self.client.post(self.task_url(), self.note_payload(text='Another update')).status_code, 302)

    def test_assignment_group_team_and_private_task_permissions(self):
        role = self.diary.add_entry(spec=EntrySpec('Group', DateKind.ONCE, fixed_date=date(2027, 6, 1),
                                                   owner_kind=OwnerKind.ROLE, role_ref='Helpers'))
        team = self.diary.add_entry(spec=EntrySpec('Team', DateKind.ONCE, fixed_date=date(2027, 6, 1)))
        self.user_diary.add_note(entry_key=role, text='Group member note')
        self.user_diary.add_note(entry_key=team, text='Team member note')
        other_actor = Actor(f'user:{self.other.pk}', frozenset({'Participants'}), frozenset({self.diary.key}))
        other = DiaryAPI(actor=other_actor).diary(key=self.diary.key)
        with self.assertRaises(PermissionDenied):
            other.add_note(entry_key=role, text='Not a group member')
        self.assertFalse(other.task(entry_key=role)['can_add_note'])
        with self.assertRaises(ObjectDoesNotExist):
            other.notes(entry_key=self.personal)
        with self.assertRaises(ObjectDoesNotExist):
            other.add_note(entry_key=self.personal, text='Private')
        self.assertEqual(len(other.notes(entry_key=team)), 1)
        other.add_note(entry_key=team, text='Another team member')
        removed = DiaryAPI(actor=replace(self.user_actor, groups=frozenset({'Participants'}))).diary(key=self.diary.key)
        with self.assertRaises(PermissionDenied):
            removed.add_note(entry_key=role, text='Former group member')
        for actor in (replace(self.user_actor, calendar_keys=frozenset()),
                      replace(self.user_actor, groups=frozenset())):
            with self.assertRaises(PermissionDenied):
                DiaryAPI(actor=actor).diary(key=self.diary.key).add_note(entry_key=team, text='Denied')
        self.diary.add_note(entry_key=role, text='Manager is not assigned but may contribute')

    def test_known_and_deleted_author_names_never_fall_back_to_email(self):
        note = self.user_diary.add_note(entry_key=self.personal, text='History')
        self.assertEqual(note['author_label'], 'Alice Smith')
        self.user.delete()
        stored = self.diary.notes(entry_key=self.personal)[0]
        self.assertEqual(stored['author_label'], 'deleted user')
        self.assertEqual(stored['author_ref'], note['author_ref'])
        self.assertEqual(stored['created_at'], note['created_at'])
        opaque = DiaryAPI(actor=replace(self.actor, reference='external:missing')).diary(key=self.diary.key)
        self.assertEqual(opaque.add_note(entry_key=self.personal, text='Unknown author')['author_label'], 'deleted user')

    def test_blank_notes_invalid_keys_and_conflicting_retries_do_not_write(self):
        for text in ('', ' \n\t ', None, 42):
            with self.assertRaises(ValidationError):
                self.user_diary.add_note(entry_key=self.personal, text=text)
        with self.assertRaises(ValidationError):
            self.user_diary.add_note(entry_key=self.personal, text='Valid text', note_key='invalid')
        self.assertFalse(TaskNote.objects.exists())

    def test_model_and_bulk_updates_and_deletes_are_rejected(self):
        result = self.user_diary.add_note(entry_key=self.personal, text='Original')
        note = TaskNote.objects.get(pk=result['key'])
        note.text = 'Changed'
        with self.assertRaises(ValidationError):
            note.save()
        with self.assertRaises(ValidationError):
            note.delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            TaskNote.objects.filter(pk=note.pk).update(text='Changed')
        with self.assertRaises(IntegrityError), transaction.atomic():
            TaskNote.objects.filter(pk=note.pk).delete()
        self.assertEqual(TaskNote.objects.get(pk=note.pk).text, 'Original')

    def test_task_page_escapes_notes_preserves_history_and_uses_success_contract(self):
        data = self.note_payload(text='<script>alert(1)</script>\nUpdate', created_at='forged', author_ref='forged')
        with patch.object(TaskDetailView, 'on_success') as notify:
            response = self.client.post(self.task_url(), data)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('?', response['Location'])
        result = notify.call_args.kwargs['result']
        self.assertEqual(result.operation, 'task_note_added')
        self.assertEqual(result.entry_key, self.personal)
        self.assertEqual(TaskNote.objects.get().author_ref, f'user:{self.user.pk}')
        self.assertEqual(self.client.post(self.task_url(), data).status_code, 302)
        self.assertEqual(TaskNote.objects.count(), 1)
        page = self.client.get(self.task_url())
        self.assertContains(page, '&lt;script&gt;')
        self.assertNotContains(page, '<script>alert(1)</script>')
        self.assertContains(page, 'Alice Smith')
        self.assertNotContains(page, self.user.get_username())
        self.assertContains(page, 'diary-note-time')

    def test_note_validation_does_not_invoke_success_or_other_task_forms(self):
        data = self.note_payload(text='  ')
        with patch.object(TaskDetailView, 'on_success') as notify:
            response = self.client.post(self.task_url(), data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.context['note_form']['note_key'].value(), data['note_key'])
        self.assertTrue(response.context['note_form'].errors)
        notify.assert_not_called()
        self.assertFalse(TaskNote.objects.exists())
        self.assertEqual(self.client.post(self.task_url(), self.note_payload(revision='invalid',
                                      blocker_token='invalid')).status_code, 302)

    def test_cross_tab_signed_target_mismatch_rejects_note(self):
        payload = self.note_payload()
        self.assertEqual(self.client.post(self.task_url(entry_key=self.first.entry_key), payload).status_code, 400)
        self.assertFalse(TaskNote.objects.exists())

    def test_whole_diary_deletion_cleans_notes_with_preview_and_rollback(self):
        self.user_diary.add_note(entry_key=self.personal, text='Keep until diary is deleted')
        output = StringIO()
        call_command('manage_diaries', 'delete', '--dry-run', '--json', diary=self.diary.key, stdout=output)
        self.assertIn('"notes": 1', output.getvalue())
        self.assertEqual(TaskNote.objects.count(), 1)
        with patch('Diary.management.administration.delete_rows', side_effect=ValidationError('Fail')):
            with self.assertRaises(CommandError):
                call_command('manage_diaries', 'delete', '--force', diary=self.diary.key, stdout=StringIO())
        self.assertEqual(TaskNote.objects.count(), 1)
        call_command('manage_diaries', 'delete', '--force', diary=self.diary.key, stdout=StringIO())
        self.assertFalse(TaskNote.objects.exists())
        self.assertFalse(EventCalendar.objects.filter(pk=self.diary.key).exists())


@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',))
class NoteConcurrencyTests(NoteFixtures, TransactionTestCase):
    def test_same_key_concurrent_requests_preserve_one_stamped_note(self):
        key = uuid4()
        def save(unused):
            close_old_connections()
            try:
                return DiaryAPI(actor=self.user_actor).diary(key=self.diary.key).add_note(
                    entry_key=self.personal, text='Concurrent note', note_key=key)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(save, range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(TaskNote.objects.count(), 1)
