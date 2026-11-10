"""DFUT-007: Payloads, UI identity, commit boundaries, retries and failures."""
import json
from dataclasses import replace
from datetime import date
from uuid import UUID, uuid4
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from Diary.api import DiaryAPI, EntrySpec
from Diary.choices import DateKind, OwnerKind
from Diary.models import CalendarEntry, TemplateEntry
from Diary.signals import (task_created, task_note_added, task_dependency_changed, task_closed,
                          task_ownership_changed)
from Diary.tests.test_task_editing import TaskEditingFixtures
from Diary.tests import test_ownership_recovery
from Diary.views import DiaryDataView, DjangoOwnerDirectory


TASK_SIGNALS = (task_created, task_note_added, task_dependency_changed, task_closed, task_ownership_changed)


class SignalFixtures(TaskEditingFixtures):
    def setUp(self):
        super().setUp()
        self.events = []
        self.actor = replace(self.actor, email='manager@example.test')
        self.diary = DiaryAPI(actor=self.actor).diary(key=self.diary.key)
        self.template = DiaryAPI(actor=self.actor).template(key=self.template.key)
        for signal in TASK_SIGNALS:
            signal.connect(self.receive, weak=False)
            self.addCleanup(signal.disconnect, self.receive)

    def receive(self, sender, signal, **payload):
        self.events.append((signal, sender, payload))

    def event(self, signal, key, name, *, sender=CalendarEntry, user='manager@example.test',
              diary_key=None, template_version_key=None):
        diary_key = (diary_key or self.diary.key) if sender is CalendarEntry else None
        template_version_key = ((template_version_key or self.template.latest_version().key)
                                if sender is TemplateEntry else None)
        return signal, sender, {'user': user, 'task': key, 'task-name': name,
                               'diary_key': diary_key, 'template_version_key': template_version_key}

    orphan = test_ownership_recovery.OwnershipRecoveryTests.orphan

    def recover(self, entry, **kwargs):
        return self.diary.reassign_task(entry_key=entry.entry_key, owner_kind=OwnerKind.TEAM,
            expected_revision=entry.revision, directory=DjangoOwnerDirectory(), **kwargs)


@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',),
                   ROOT_URLCONF='Diary.tests.test_task_editing')
class TaskSignalTests(SignalFixtures, TestCase):
    def test_reused_task_key_is_distinguished_across_diaries_and_api_records(self):
        actor = replace(self.actor, calendar_keys=frozenset({self.diary.key, self.other_diary.key}))
        api = DiaryAPI(actor=actor)
        diaries = [api.diary(key=key) for key in (self.diary.key, self.other_diary.key)]
        with self.captureOnCommitCallbacks(execute=True):
            for diary in diaries:
                note = diary.add_note(entry_key=self.first.entry_key, text='Scoped note')
                self.assertEqual((note['diary_key'], note['entry_key']), (diary.key, self.first.entry_key))
                diary.complete(entry_key=self.first.entry_key, expected_revision=0)
        self.assertCountEqual(self.events, [self.event(signal, self.first.entry_key, self.first.name, diary_key=diary.key)
            for diary in diaries for signal in (task_note_added, task_closed)])
        for diary in diaries:
            for row in diary.read()['entries']:
                self.assertEqual(row['diary_key'], diary.key)
            self.assertEqual(diary.task(entry_key=self.first.entry_key)['diary_key'], diary.key)
            self.assertEqual(diary.notes(entry_key=self.first.entry_key)[0]['diary_key'], diary.key)
            self.assertEqual(diary.available_predecessors(entry_key=self.second.entry_key),
                ({'entry_key': self.first.entry_key, 'name': self.first.name,
                  'diary_key': diary.key, 'template_version_key': None},))
            for row in diary.active_tasks():
                self.assertEqual(row['diary_key'], diary.key)
        found = api.search_tasks(query=self.first.name)
        self.assertEqual({(row['diary_key'], row['entry_key']) for row in found},
                         {(diary.key, self.first.entry_key) for diary in diaries})

    def test_template_events_distinguish_reused_keys_by_version(self):
        with self.captureOnCommitCallbacks(execute=True):
            second = self.template.save_version(entries=[self.first, self.second], predecessors={},
                                                expected_version_key=self.version.key)
            third = self.template.save_version(entries=[self.first, self.second],
                predecessors={self.second.entry_key: [self.first.entry_key]}, expected_version_key=second.key)
        self.assertEqual(self.events, [self.event(task_dependency_changed, self.second.entry_key, self.second.name,
            sender=TemplateEntry, template_version_key=version.key) for version in (second, third)])
        for version in (second, third):
            self.assertTrue(all(row['template_version_key'] == version.key for row in version.read()['entries']))
        self.assertEqual(third.available_predecessors(entry_key=self.second.entry_key),
            ({'entry_key': self.first.entry_key, 'name': self.first.name,
              'diary_key': None, 'template_version_key': third.key},))

    def test_http_task_records_expose_the_selected_diary_task_pair(self):
        keys = (self.diary.key, self.other_diary.key)
        view = DiaryDataView.as_view(resource='task', permitted_diary_keys=keys)
        for diary_key in keys:
            request = RequestFactory().get('/task-data/', {'diary_key': str(diary_key)})
            request.user = self.manager
            response = view(request, entry_key=self.first.entry_key)
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.content)['data']
            self.assertEqual((data['diary_key'], data['entry_key']),
                             (str(diary_key), str(self.first.entry_key)))

    def test_creation_note_and_completion_payloads_and_retries(self):
        spec = EntrySpec('New task', DateKind.ONCE, fixed_date=date(2027, 6, 22))
        note_key = uuid4()
        with self.captureOnCommitCallbacks(execute=True):
            for _ in range(2):
                self.diary.add_entry(spec=spec)
                self.diary.add_note(entry_key=spec.entry_key, text='A note', note_key=note_key)
                self.diary.complete(entry_key=spec.entry_key, expected_revision=0)
            self.assertEqual(self.events, [])
        self.assertEqual(self.events, [self.event(signal, spec.entry_key, spec.name)
                                      for signal in (task_created, task_note_added, task_closed)])

    def test_rollback_discards_all_queued_events(self):
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaisesMessage(ValueError, 'rollback'), transaction.atomic():
                spec = EntrySpec('Rolled back', DateKind.ONCE, fixed_date=date(2027, 6, 22))
                self.diary.add_entry(spec=spec)
                self.diary.add_note(entry_key=spec.entry_key, text='Rolled back')
                self.diary.complete(entry_key=spec.entry_key, expected_revision=0)
                self.template.save_version(entries=[self.first, self.second], predecessors={},
                                           expected_version_key=self.version.key)
                raise ValueError('rollback')
        self.assertEqual(self.events, [])
        self.assertFalse(CalendarEntry.objects.filter(entry_key=spec.entry_key).exists())

    def test_invalid_and_forbidden_changes_emit_nothing(self):
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(ValidationError):
                self.diary.add_note(entry_key=self.personal, text=' ')
            with self.assertRaises(ValidationError):
                self.diary.complete(entry_key=self.second.entry_key, expected_revision=0)
            with self.assertRaises(ValidationError):
                self.diary.set_predecessors(entry_key=self.second.entry_key, predecessor_keys=[])
        self.assertEqual(self.events, [])

    def test_close_all_emits_one_event_per_newly_completed_task(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.diary.complete(entry_key=self.first.entry_key, expected_revision=0)
        self.events.clear()
        self.block_personal()
        token = self.diary.task(entry_key=self.personal)['blocker_token']
        with self.captureOnCommitCallbacks(execute=True):
            self.diary.complete(entry_key=self.personal, expected_revision=0, close_all=True,
                                expected_blockers=token)
        self.assertCountEqual(self.events, [self.event(task_closed, self.second.entry_key, self.second.name),
                                           self.event(task_closed, self.personal, 'Personal target')])

    def test_template_approval_compares_stable_keys_and_dependency_sets(self):
        specs = [self.first, self.second]
        with self.captureOnCommitCallbacks(execute=True):
            unchanged = self.template.save_version(entries=specs,
                predecessors={self.second.entry_key: [self.first.entry_key]}, expected_version_key=self.version.key)
        self.assertEqual(self.events, [])
        with self.captureOnCommitCallbacks(execute=True):
            changed = self.template.save_version(entries=specs, predecessors={}, expected_version_key=unchanged.key)
            changed.approve()
        self.assertEqual(self.events, [self.event(task_dependency_changed, self.second.entry_key,
                                                 self.second.name, sender=TemplateEntry)])
        self.events.clear()
        third = EntrySpec('Third', DateKind.ANNUAL, month=7, day=1)
        with self.captureOnCommitCallbacks(execute=True):
            self.template.save_version(entries=[*specs, third],
                predecessors={third.entry_key: [self.first.entry_key]}, expected_version_key=changed.key)
        self.assertEqual(self.events, [self.event(signal, third.entry_key, third.name, sender=TemplateEntry)
                                      for signal in (task_created, task_dependency_changed)])

    def test_draft_events_wait_for_approval(self):
        draft = self.template.create_version(number=2)
        spec = EntrySpec('Draft task', DateKind.ANNUAL, month=7, day=1)
        with self.captureOnCommitCallbacks(execute=True):
            draft.add_entry(spec=spec)
            draft.set_predecessors(entry_key=spec.entry_key, predecessor_keys=[])
        self.assertEqual(self.events, [])
        with self.captureOnCommitCallbacks(execute=True):
            draft.approve()
            draft.approve()
        self.assertEqual(self.events, [self.event(task_created, spec.entry_key, spec.name, sender=TemplateEntry)])

    def test_copying_template_emits_creation_and_initial_dependency_events_once(self):
        api = DiaryAPI(actor=self.actor)
        with self.captureOnCommitCallbacks(execute=True):
            for _ in range(2):
                diary = api.create_diary(name='Signal copy', event_ref='signal-copy', template_version_key=self.version.key,
                                 milestone_dates={'target': date(2027, 7, 1)})
        self.assertCountEqual(self.events, [self.event(task_created, spec.entry_key, spec.name, diary_key=diary.key)
                                           for spec in (self.first, self.second)] +
                              [self.event(task_dependency_changed, self.second.entry_key, self.second.name, diary_key=diary.key)])

    def test_task_relative_template_copy_preserves_dates_and_signal_identity(self):
        """Merge regression: copying in date order must retain each task's own fields."""
        api = DiaryAPI(actor=self.actor)
        template = api.create_template(name='Signal date chain')
        source = EntrySpec('Source date', DateKind.RELATIVE, milestone_name='target', day_offset=0)
        dependent = EntrySpec('Dependent date', DateKind.TASK, source_task_key=source.entry_key, day_offset=3)
        version = template.save_version(entries=[dependent, source],
            predecessors={dependent.entry_key: [source.entry_key]}, expected_version_key=None)
        with self.captureOnCommitCallbacks(execute=True):
            for _ in range(2):
                diary = api.create_diary(name='Signal dates', event_ref='signal-date-chain',
                    template_version_key=version.key, milestone_dates={'target': date(2027, 7, 1)})
        self.assertEqual(self.events, [self.event(task_created, source.entry_key, source.name, diary_key=diary.key),
                                      self.event(task_created, dependent.entry_key, dependent.name, diary_key=diary.key),
                                      self.event(task_dependency_changed, dependent.entry_key, dependent.name, diary_key=diary.key)])
        entries = {entry.entry_key: entry for entry in CalendarEntry.objects.filter(calendar_id=diary.key)}
        self.assertEqual((entries[source.entry_key].name, entries[source.entry_key].due_date),
                         (source.name, date(2027, 7, 1)))
        self.assertEqual((entries[dependent.entry_key].name, entries[dependent.entry_key].due_date),
                         (dependent.name, date(2027, 7, 4)))

    def test_ui_notes_and_completion_use_authenticated_email(self):
        self.user.email = 'actual-user@example.test'
        self.user.save()
        page = self.client.get(self.task_url())
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.task_url(), {'action': 'add_note', 'text': 'UI note',
                'note_key': str(uuid4()), 'diary_target': page.context['diary_target'],
                'user': 'forged@example.test', 'email': 'forged@example.test'})
        self.assertEqual(response.status_code, 302)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.task_url(), self.action_data('complete'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.events, [self.event(signal, self.personal, 'Personal target', user=self.user.email)
                                      for signal in (task_note_added, task_closed)])

    @override_settings(ROOT_URLCONF='Diary.tests.test_task_creation')
    def test_ui_creation_uses_authenticated_email(self):
        self.user.email = 'creator-email@example.test'
        self.user.save()
        data = self.payload(user='forged@example.test')
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.url(), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.events, [self.event(task_created, UUID(data['entry_key']), data['name'],
                                                 user=self.user.email)])

    def test_receiver_failure_does_not_skip_other_receivers_or_later_events(self):
        def broken(sender, **kwargs):
            raise RuntimeError('Receiver failed')
        task_note_added.disconnect(self.receive)
        task_note_added.connect(broken, weak=False)
        task_note_added.connect(self.receive, weak=False)
        self.addCleanup(task_note_added.disconnect, broken)
        with self.assertLogs('django.dispatch', level='ERROR'), self.captureOnCommitCallbacks(execute=True):
            self.diary.add_note(entry_key=self.personal, text='Committed note')
            self.diary.complete(entry_key=self.personal, expected_revision=0)
        self.assertEqual(len(self.events), 2)
        self.assertEqual(len(self.diary.notes(entry_key=self.personal)), 1)

    def test_ui_template_dependency_and_ownership_changes_use_manager_email(self):
        self.manager.email = 'ui-manager@example.test'
        self.manager.save()
        self.client.force_login(self.manager)
        data = {'name': 'Creation template', 'description': '', 'expected_version_key': str(self.version.key),
                'tasks-TOTAL_FORMS': '2', 'tasks-INITIAL_FORMS': '2',
                'tasks-MIN_NUM_FORMS': '0', 'tasks-MAX_NUM_FORMS': '200', 'action': 'save',
                'user': 'forged@example.test'}
        for index, spec in enumerate((self.first, self.second)):
            for field, value in {'entry_key': spec.entry_key, 'name': spec.name, 'date_kind': spec.date_kind,
                                 'milestone_name': 'target', 'day_offset': spec.day_offset,
                                 'year_offset': 0, 'owner_kind': spec.owner_kind}.items():
                data[f'tasks-{index}-{field}'] = str(value)
        data['tasks-0-owner_kind'] = OwnerKind.PERSON
        data['tasks-0-person_ref'] = f'user:{self.user.pk}'
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('Diary:template-edit', kwargs={'template_name': 'Creation template'}), data)
        self.assertEqual(response.status_code, 302)
        self.assertCountEqual(self.events, [
            self.event(task_dependency_changed, self.second.entry_key, self.second.name,
                       sender=TemplateEntry, user=self.manager.email),
            self.event(task_ownership_changed, self.first.entry_key, self.first.name,
                       sender=TemplateEntry, user=self.manager.email)])

    def test_callable_without_email_emits_empty_user(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.user_diary.add_note(entry_key=self.personal, text='API caller')
        self.assertEqual(self.events, [self.event(task_note_added, self.personal, 'Personal target', user='')])

    def test_ownership_recovery_payload_and_rejected_retry(self):
        entry = self.orphan()
        with self.captureOnCommitCallbacks(execute=True):
            self.recover(entry)
            self.assertEqual(self.events, [])
        self.assertEqual(self.events, [self.event(task_ownership_changed, entry.entry_key, entry.name)])
        self.events.clear()
        entry.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(ValidationError):
                self.recover(entry)
        self.assertEqual(self.events, [])

    def test_ownership_rejections_emit_nothing(self):
        entry = self.orphan()
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(PermissionDenied):
                self.user_diary.reassign_task(entry_key=entry.entry_key, owner_kind=OwnerKind.TEAM,
                                              expected_revision=entry.revision)
            with self.assertRaises(ValidationError):
                self.diary.reassign_task(entry_key=entry.entry_key, owner_kind=OwnerKind.TEAM,
                                          expected_revision=entry.revision + 1)
            with self.assertRaises(ValidationError):
                self.diary.reassign_task(entry_key=entry.entry_key, owner_kind=OwnerKind.PERSON,
                    person_ref=f'user:{self.other.pk}', expected_revision=entry.revision,
                    directory=DjangoOwnerDirectory())
        self.assertEqual(self.events, [])
        entry.refresh_from_db()
        self.assertEqual(entry.person_ref, f'user:{self.other.pk}')

    def test_ownership_rollback_discards_diary_and_template_events(self):
        entry = self.orphan()
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(ValueError), transaction.atomic():
                self.recover(entry, update_template=True, expected_version_key=self.version.key)
                raise ValueError('Abort combined change')
        self.assertEqual(self.events, [])
        entry.refresh_from_db()
        self.assertEqual(entry.owner_kind, OwnerKind.PERSON)
        self.assertEqual(self.template.latest_version().key, self.version.key)
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(ValidationError):
                self.recover(entry, update_template=True, expected_version_key=uuid4())
        self.assertEqual(self.events, [])
        entry.refresh_from_db()
        self.assertEqual(entry.revision, 0)

    def test_template_ownership_kind_person_and_role_changes_and_unchanged_saves(self):
        version = self.version
        # Check owner kind, person identity, and role identity independently.
        owners = [dict(owner_kind=OwnerKind.PERSON, person_ref=f'user:{self.user.pk}'),
                  dict(owner_kind=OwnerKind.PERSON, person_ref=f'user:{self.other.pk}'),
                  dict(owner_kind=OwnerKind.ROLE, role_ref='Helpers'),
                  dict(owner_kind=OwnerKind.ROLE, role_ref='Participants'),
                  dict(owner_kind=OwnerKind.TEAM)]
        with override_settings(DIARY_TASK_OWNER_ROLES=('Helpers', 'Participants')):
            for owner in owners:
                spec = replace(self.first, **owner)
                with self.subTest(owner=owner):
                    self.events.clear()
                    with self.captureOnCommitCallbacks(execute=True):
                        version = self.template.save_version(entries=[spec, self.second],
                            predecessors={self.second.entry_key: [self.first.entry_key]},
                            expected_version_key=version.key, directory=DjangoOwnerDirectory())
                    self.assertEqual(self.events, [self.event(task_ownership_changed, spec.entry_key,
                                                               spec.name, sender=TemplateEntry)])
                    self.events.clear()
                    with self.captureOnCommitCallbacks(execute=True):
                        version = self.template.save_version(entries=[spec, self.second],
                            predecessors={self.second.entry_key: [self.first.entry_key]},
                            expected_version_key=version.key, directory=DjangoOwnerDirectory())
                        version.approve()
                    self.assertEqual(self.events, [])

    def test_combined_recovery_emits_one_event_for_each_changed_copy(self):
        spec = replace(self.first, owner_kind=OwnerKind.PERSON, person_ref=f'user:{self.other.pk}')
        with self.captureOnCommitCallbacks(execute=True):
            version = self.template.save_version(entries=[spec, self.second],
                predecessors={self.second.entry_key: [self.first.entry_key]},
                expected_version_key=self.version.key, directory=DjangoOwnerDirectory())
        entry = self.orphan()
        self.events.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.recover(entry, update_template=True, expected_version_key=version.key)
        self.assertCountEqual(self.events, [self.event(task_ownership_changed, entry.entry_key, entry.name,
                                                       sender=sender) for sender in (CalendarEntry, TemplateEntry)])

    def test_ui_ownership_recovery_uses_authenticated_manager_email(self):
        entry = self.orphan()
        self.manager.email = 'owner-manager@example.test'
        self.manager.save()
        self.client.force_login(self.manager)
        data = self.action_data('save_owner', entry_key=entry.entry_key, owner_kind=OwnerKind.TEAM,
                                person_ref='', role_ref='', user='forged@example.test')
        data['entry_key'] = str(entry.entry_key)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.task_url(entry.entry_key), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.events, [self.event(task_ownership_changed, entry.entry_key, entry.name,
                                                  user=self.manager.email)])


@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',))
class TaskSignalCommitTests(SignalFixtures, TransactionTestCase):
    def test_real_commit_delivers_and_autocommit_note_keeps_payload_snapshot(self):
        with transaction.atomic():
            self.diary.add_note(entry_key=self.personal, text='Commit boundary')
            self.assertEqual(self.events, [])
        self.assertEqual(self.events, [self.event(task_note_added, self.personal, 'Personal target')])

    def test_failing_receivers_for_all_signals_cannot_prevent_commit(self):
        failures = []

        def broken(sender, signal, **kwargs):
            self.assertFalse(connection.in_atomic_block)
            failures.append(signal)
            raise RuntimeError('Receiver failed after commit')

        for signal in TASK_SIGNALS:
            signal.disconnect(self.receive)
            signal.connect(broken, weak=False)
            signal.connect(self.receive, weak=False)
            self.addCleanup(signal.disconnect, broken)

        spec = EntrySpec('Saved despite receiver errors', DateKind.ONCE, fixed_date=date(2027, 7, 1))
        orphan = self.orphan()
        with self.assertLogs('django.dispatch', level='ERROR'):
            with transaction.atomic():
                self.diary.add_entry(spec=spec)
                self.diary.add_note(entry_key=spec.entry_key, text='Saved note')
                self.diary.complete(entry_key=spec.entry_key, expected_revision=0)
                self.recover(orphan)
                version = self.template.save_version(entries=[self.first, self.second], predecessors={},
                                                     expected_version_key=self.version.key)
                self.assertEqual(failures, [])

        self.assertCountEqual(failures, TASK_SIGNALS)
        self.assertEqual(len(self.events), 5)
        saved = CalendarEntry.objects.get(calendar_id=self.diary.key, entry_key=spec.entry_key)
        self.assertIsNotNone(saved.completed_at)
        self.assertEqual(saved.notes.get().text, 'Saved note')
        orphan.refresh_from_db()
        self.assertEqual(orphan.owner_kind, OwnerKind.TEAM)
        self.assertEqual(self.template.latest_version().key, version.key)
        self.assertFalse(TemplateEntry.objects.get(version_id=version.key,
                                                  entry_key=self.second.entry_key).predecessors.exists())

    def test_dispatch_failure_is_logged_and_later_callbacks_still_run(self):
        with patch.object(task_note_added, 'send_robust', side_effect=RuntimeError('Dispatch failed')):
            with self.assertLogs('django.db.backends.base', level='ERROR'):
                with transaction.atomic():
                    self.diary.add_note(entry_key=self.personal, text='Saved despite dispatch error')
                    self.diary.complete(entry_key=self.personal, expected_revision=0)
        saved = CalendarEntry.objects.get(calendar_id=self.diary.key, entry_key=self.personal)
        self.assertIsNotNone(saved.completed_at)
        self.assertEqual(saved.notes.get().text, 'Saved despite dispatch error')
        self.assertEqual(self.events, [self.event(task_closed, self.personal, 'Personal target')])
