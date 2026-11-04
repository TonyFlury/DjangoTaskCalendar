"""DV1-054: Verify portable fixtures, destination ownership checks, and atomic template imports."""
import json
from dataclasses import replace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from Diary.api import DiaryAPI
from Diary.views import DjangoOwnerDirectory
from Diary.choices import OwnerKind
from Diary.models import CalendarEntry, CalendarTemplate, Milestone, TemplateVersion
from Diary.tests.test_task_creation import TaskCreationFixtures


@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',))
class TemplateTransferTests(TaskCreationFixtures, TestCase):
    """Transfer definitions while preserving destination identity, version history, and existing diaries."""

    def setUp(self):
        """Create a source template and an isolated temporary fixture file."""
        super().setUp()
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.fixture = Path(folder.name) / 'diary.json'
        self.actor_name = self.manager.get_username()
        for user in (self.user, self.other, self.manager, self.outsider):
            user.email = user.get_username()
            user.save(update_fields=('email',))

    def command(self, operation, **options):
        """Invoke the public command with an active local manager and captured output."""
        output = StringIO()
        call_command('transfer_diary_templates', operation, str(self.fixture), actor=options.pop('actor', self.actor_name),
                     stdout=output, **options)
        return output.getvalue()

    def export(self, name='Imported definition'):
        """Export a genuine Django fixture and give the imported template a new destination name."""
        self.command('export', template=['Creation template'])
        payload = json.loads(self.fixture.read_text())
        for item in payload:

            # Different destination names exercise import without deleting the source or its live diaries.
            if item['model'] == CalendarTemplate._meta.label_lower:
                item['fields']['name'] = name
        self.fixture.write_text(json.dumps(payload))
        return payload

    def imported_version(self, name='Imported definition'):
        """Return the latest imported version for direct identity and dependency assertions."""
        return TemplateVersion.objects.filter(template__name=name).order_by('-number').first()

    def test_round_trip_preserves_graph_and_skips_identical_reimports(self):
        """Rebuild task definitions with fresh database keys while keeping stable task keys and dependency links."""
        self.export()
        before = list(CalendarEntry.objects.order_by('pk').values())
        self.command('import')
        version = self.imported_version()
        self.assertNotEqual(version.pk, self.version_key())
        copied = version.entries.get(entry_key=self.second.entry_key)
        self.assertEqual(list(copied.predecessors.values_list('entry_key', flat=True)), [self.first.entry_key])
        self.assertEqual(version.approved_by_ref, f'user:{self.manager.pk}')
        count = TemplateVersion.objects.count()
        self.command('import')
        self.assertEqual(TemplateVersion.objects.count(), count)
        self.assertEqual(list(CalendarEntry.objects.order_by('pk').values()), before)

    def version_key(self):
        """Return the original source version key without assuming source and destination database keys match."""
        return self.version.key

    def test_transfer_preserves_unused_requirements_and_detects_declaration_changes(self):
        client = DiaryAPI(actor=self.actor)
        client.define_milestones(definitions={'unused': 'Unused requirement'})
        self.template.save_version(entries=(self.first, self.second),
            predecessors={self.second.entry_key: (self.first.entry_key,)},
            expected_version_key=self.version.key, milestone_names=('target', 'unused'))
        self.export()
        self.command('import')
        imported = self.imported_version()
        self.assertEqual(set(imported.milestones.values_list('name', flat=True)), {'target', 'unused'})
        count = TemplateVersion.objects.count()
        self.command('import')
        self.assertEqual(TemplateVersion.objects.count(), count)
        # Removing only an unused requirement is a real version change.
        reference = client.template(key=imported.template_id)
        reference.save_version(entries=(self.first, self.second),
            predecessors={self.second.entry_key: (self.first.entry_key,)},
            expected_version_key=imported.pk, milestone_names=('target',))
        with self.assertRaises(CommandError):
            self.command('import')
        self.command('import', new_version=True)
        self.assertEqual(set(self.imported_version().milestones.values_list('name', flat=True)), {'target', 'unused'})

    def test_transfer_rejects_tasks_without_explicit_declarations(self):
        payload = self.export()
        payload = [item for item in payload if item['model'] != 'Diary.templatemilestone']
        self.fixture.write_text(json.dumps(payload))
        with self.assertRaises(CommandError):
            self.command('import')
        self.assertIsNone(self.imported_version())

    def test_dry_run_rolls_back_and_existing_export_files_are_not_overwritten(self):
        """Exercise normal validation without retaining imported records or replacing an existing fixture file."""
        self.export()
        original = self.fixture.read_bytes()
        self.command('import', dry_run=True)
        self.assertFalse(CalendarTemplate.objects.filter(name='Imported definition').exists())
        with self.assertRaises(CommandError):
            self.command('export')
        self.assertEqual(self.fixture.read_bytes(), original)

    def test_cycle_rejection_rolls_back_every_template_in_the_fixture(self):
        """Reject a circular graph and preserve both template records and version history."""
        payload = self.export()

        # Select the relevant exported model because the fixture also contains related definitions.
        link = next(item for item in payload if item['model'] == 'Diary.templatedependency')
        reverse = {'model': link['model'], 'pk': link['pk'] + 1,
                   'fields': {'entry': link['fields']['predecessor'], 'predecessor': link['fields']['entry']}}
        payload.append(reverse)
        self.fixture.write_text(json.dumps(payload))
        before = TemplateVersion.objects.count()
        with self.assertRaisesMessage(CommandError, 'circular dependency'):
            self.command('import')
        self.assertFalse(CalendarTemplate.objects.filter(name='Imported definition').exists())
        self.assertEqual(TemplateVersion.objects.count(), before)

    def test_person_email_overrides_require_local_eligibility(self):
        """Reject missing emails and accept only eligible destination owners for explicit email overrides."""
        payload = self.export()

        # Select the relevant exported model because the fixture also contains related definitions.
        entry = next(item for item in payload if item['model'] == 'Diary.templateentry')
        entry['fields'].update(owner_kind=OwnerKind.PERSON, person_ref='source-owner@example.test')
        self.fixture.write_text(json.dumps(payload))
        with self.assertRaises(CommandError):
            self.command('import')
        with self.assertRaisesMessage(CommandError, 'DiaryUser or DiaryManager'):
            self.command('import', person_map=[f'source-owner@example.test={self.outsider.get_username()}'])
        self.command('import', person_map=[f'source-owner@example.test={self.other.get_username()}'])
        owner = self.imported_version().entries.get(entry_key=entry['fields']['entry_key'])
        self.assertEqual(owner.person_ref, f'user:{self.other.pk}')

    def test_role_checks_reject_unconfigured_missing_and_empty_groups(self):
        """Validate role configuration and current target membership before saving imported templates."""
        payload = self.export()

        # Select the relevant exported model because the fixture also contains related definitions.
        entry = next(item for item in payload if item['model'] == 'Diary.templateentry')
        entry['fields'].update(owner_kind=OwnerKind.ROLE, role_ref='Unconfigured')
        self.fixture.write_text(json.dumps(payload))
        with self.assertRaisesMessage(CommandError, 'DIARY_TASK_OWNER_ROLES'):
            self.command('import')
        entry['fields']['role_ref'] = 'Helpers'
        self.fixture.write_text(json.dumps(payload))
        Group.objects.get(name='Helpers').user_set.clear()
        with self.assertRaises(CommandError):
            self.command('import')
        self.assertFalse(CalendarTemplate.objects.filter(name='Imported definition').exists())

    def test_different_content_requires_explicit_new_version(self):
        """Preserve existing versions until the operator explicitly requests another approved version."""
        payload = self.export()
        self.command('import')

        # Select the relevant exported model because the fixture also contains related definitions.
        entry = next(item for item in payload if item['model'] == 'Diary.templateentry')
        entry['fields']['name'] = 'Changed definition'
        self.fixture.write_text(json.dumps(payload))
        with self.assertRaisesMessage(CommandError, '--new-version'):
            self.command('import')
        self.command('import', new_version=True)
        template = CalendarTemplate.objects.get(name='Imported definition')
        self.assertEqual(template.versions.count(), 2)
        self.assertTrue(template.versions.get(number=2).entries.filter(name='Changed definition').exists())

    def test_wrong_models_invalid_dates_and_nonmanager_actors_are_rejected(self):
        """Reject unrelated fixture records, invalid task dates, and unauthorized local actors."""
        payload = self.export()
        with self.assertRaises(CommandError):
            self.command('import', actor=self.user.get_username())
        self.fixture.write_text(json.dumps([{'model': 'auth.user', 'pk': 1, 'fields': {}}]))
        with self.assertRaisesMessage(CommandError, 'unsupported model'):
            self.command('import')

        # Select the relevant exported model because the fixture also contains related definitions.
        entry = next(item for item in payload if item['model'] == 'Diary.templateentry')
        entry['fields'].update(date_kind='annual', milestone=None, month=2, day=30)
        self.fixture.write_text(json.dumps(payload))
        with self.assertRaises(CommandError):
            self.command('import')
        self.assertFalse(CalendarTemplate.objects.filter(name='Imported definition').exists())

    def test_late_model_failure_rolls_back_earlier_template_saves(self):
        """Keep the whole fixture atomic when a later template fails model validation."""
        api = DiaryAPI(actor=self.actor)
        second = api.create_template(name='Second source')
        second.save_version(entries=(self.first,), predecessors={self.first.entry_key: ()}, expected_version_key=None, milestone_names=('target',))
        self.command('export')
        payload = json.loads(self.fixture.read_text())
        versions = {}
        for item in payload:

            # Give both imported definitions fresh names while preserving source relationships.
            if item['model'] == 'Diary.calendartemplate':
                item['fields']['name'] += ' imported'

            # Locate the later source version without depending on object ordering in the file.
            if item['model'] == 'Diary.templateversion':
                versions[item['fields']['template']] = item['pk']
        for item in payload:

            # A bad date in the second template fails after the first definition was saved.
            if item['model'] == 'Diary.templateentry' and item['fields']['version'] == versions[str(second.key)]:
                item['fields'].update(date_kind='annual', milestone=None, month=2, day=30)
        self.fixture.write_text(json.dumps(payload))
        before = TemplateVersion.objects.count()
        with self.assertRaises(CommandError):
            self.command('import')
        self.assertEqual(TemplateVersion.objects.count(), before)
        self.assertFalse(CalendarTemplate.objects.filter(name__endswith=' imported').exists())

    def test_milestone_text_and_new_definition_import(self):
        """Preserve milestone text and reject changes to an existing destination definition."""
        payload = self.export()

        # Select the relevant exported model because the fixture also contains related definitions.
        milestone = next(item for item in payload if item['model'] == 'Diary.milestone')
        milestone['fields'].update(name='portable_target', label='Portable target', description='A portable date definition.')
        self.fixture.write_text(json.dumps(payload))
        self.command('import')
        stored = Milestone.objects.get(name='portable_target')
        self.assertEqual(stored.description, 'A portable date definition.')
        self.assertNotEqual(str(stored.pk), str(milestone['pk']))
        milestone['fields']['label'] = 'Different target'
        self.fixture.write_text(json.dumps(payload))
        with self.assertRaisesMessage(CommandError, 'different destination text'):
            self.command('import', new_version=True)

    def test_person_export_uses_email_and_import_resolves_it_without_mapping(self):
        """Export a portable email and resolve it to a local user without changing source ownership."""
        owned = replace(self.first, owner_kind=OwnerKind.PERSON, person_ref=f'user:{self.other.pk}')
        self.template.save_version(entries=(owned, self.second),
            predecessors={owned.entry_key: (), self.second.entry_key: (owned.entry_key,)},
            expected_version_key=self.version.key, directory=DjangoOwnerDirectory())
        payload = self.export()

        # Select the relevant exported model because the fixture also contains related definitions.
        entry = next(item for item in payload if item['model'] == 'Diary.templateentry'
                     and item['fields']['owner_kind'] == OwnerKind.PERSON)
        self.assertEqual(entry['fields']['person_ref'], self.other.email.casefold())
        self.command('import')
        stored = self.imported_version().entries.get(entry_key=owned.entry_key)
        self.assertEqual(stored.person_ref, f'user:{self.other.pk}')
        original = TemplateVersion.objects.get(pk=self.template.editor_data()['version_key'])
        self.assertEqual(original.entries.get(entry_key=owned.entry_key).person_ref, f'user:{self.other.pk}')

    def test_duplicate_destination_emails_stop_import(self):
        """Reject ambiguous destination emails instead of selecting an arbitrary eligible user."""
        payload = self.export()

        # Select the relevant exported model because the fixture also contains related definitions.
        entry = next(item for item in payload if item['model'] == 'Diary.templateentry')
        entry['fields'].update(owner_kind=OwnerKind.PERSON, person_ref=self.other.email)
        self.fixture.write_text(json.dumps(payload))
        model = get_user_model()
        fields = {model.USERNAME_FIELD: 'duplicate@example.test', model.get_email_field_name(): self.other.email.upper()}
        model._default_manager.create_user(**fields)
        with self.assertRaisesMessage(CommandError, 'exactly one active destination user'):
            self.command('import')
        self.assertFalse(CalendarTemplate.objects.filter(name='Imported definition').exists())
