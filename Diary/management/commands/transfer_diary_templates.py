"""DV1-054: Transfer template fixtures through validated Diary operations."""
import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction

from Diary.api import Actor, DiaryAPI, EntrySpec
from Diary.choices import OwnerKind, VersionStatus
from Diary.entry_mapping import EntryMapper, validate_entry_owner
from Diary.models import CalendarTemplate, Milestone, TemplateDependency, TemplateEntry, TemplateVersion, TemplateMilestone
from Diary.roles import access_groups, validate_task_owner_roles
from Diary.template_graph import validate_template_graph
from Diary.views import DjangoOwnerDirectory


class Command(BaseCommand):
    """Export approved templates and validate fixture imports without preserving source database identities."""

    help = 'Export and import Diary template JSON fixtures with ownership and dependency validation.'

    def add_arguments(self, parser):
        """Define the operation, fixture path, destination actor, and explicit person mappings."""
        parser.add_argument('operation', choices=('export', 'import'))
        parser.add_argument('fixture', type=Path)
        parser.add_argument('--actor', required=True, help='Username of an active local DiaryManager.')
        parser.add_argument('--template', action='append', help='Export this template name. Repeat to select several.')
        parser.add_argument('--person-map', action='append', default=[], metavar='SOURCE_EMAIL=LOCAL_EMAIL',
                            help='Map a source owner email to a different local email address.')
        parser.add_argument('--new-version', action='store_true', help='Approve a new version when existing content differs.')
        parser.add_argument('--dry-run', action='store_true', help='Validate an import and roll back all changes.')

    def handle(self, *args, **options):
        """Check the local actor and report import or export failures as CommandError."""
        try:
            model = get_user_model()
            user = model._default_manager.get(**{model.USERNAME_FIELD: options['actor']}, is_active=True)
            groups = frozenset(user.groups.values_list('name', flat=True))

            # A management invocation must identify a current local manager for its audit records.
            if access_groups()['manager'] not in groups:
                raise ValueError('The actor must belong to the configured DiaryManager group.')
            self.actor = Actor(f'user:{user.pk}', groups)

            # Export options must not imply import behavior or silently discard requested validation.
            if options['operation'] == 'export':

                # Reject import-only flags instead of producing an export with different implied behavior.
                if options['person_map'] or options['new_version'] or options['dry_run']:
                    raise ValueError('Person mappings, --new-version, and --dry-run apply only to import.')
                self.export_fixture(options)
            else:

                # Import scope comes from the complete fixture rather than an export-only name filter.
                if options['template']:
                    raise ValueError('--template applies only to export.')
                self.import_fixture(options)
        except (ValueError, TypeError, KeyError, OSError, ObjectDoesNotExist, PermissionDenied,
                ValidationError, ImproperlyConfigured, IntegrityError, serializers.base.DeserializationError) as error:
            raise CommandError(f'Diary template transfer failed: {error}') from error

    @transaction.atomic
    def export_fixture(self, options):
        """Write a new Django JSON fixture containing each selected template's latest approved version."""
        templates = CalendarTemplate.objects.order_by('name', 'pk')

        # Explicit names must all exist instead of silently producing an incomplete export.
        if options['template']:
            requested = set(options['template'])
            templates = templates.filter(name__in=requested)
            if set(templates.values_list('name', flat=True)) != requested:
                raise ValueError('One or more selected templates do not exist.')
        records, milestone_ids = [], set()
        for template in templates:
            CalendarTemplate.objects.select_for_update().get(pk=template.pk)
            version = template.versions.filter(status=VersionStatus.APPROVED).order_by('-number').first()

            # Draft and unversioned templates cannot supply an approved portable definition.
            if version is None:
                raise ValueError(f'Template {template.name!r} has no approved version.')
            entries = list(version.entries.order_by('entry_key'))
            records.extend((template, version, *entries))
            records.extend(version.milestone_declarations.order_by('pk'))
            milestone_ids.update(version.milestones.values_list('pk', flat=True))
            records.extend(TemplateDependency.objects.filter(entry__version=version).order_by('pk'))
            for entry in entries:

                # Portable person ownership uses an email address rather than a source database user key.
                if entry.owner_kind == OwnerKind.PERSON:
                    entry.person_ref = self.export_person_email(entry.person_ref)

                # Fixed-date rules do not reference a milestone definition.
                if entry.milestone_id is not None:
                    milestone_ids.add(entry.milestone_id)

        # An empty export must not be mistaken for a usable template delivery.
        if not records:
            raise ValueError('No templates are available for export.')
        records = [*Milestone.objects.filter(pk__in=milestone_ids).order_by('name'), *records]
        payload = serializers.serialize('json', records, indent=2)
        with options['fixture'].open('x', encoding='utf-8') as destination:
            destination.write(payload + '\n')
        self.stdout.write('Exported approved Diary templates. Existing files are not overwritten.')

    def read_fixture(self, path):
        """Deserialize only the six template model types without saving any source objects."""
        payload = json.loads(path.read_text(encoding='utf-8'))
        allowed = {model._meta.label_lower: model for model in
                   (CalendarTemplate, TemplateVersion, TemplateEntry, TemplateDependency, Milestone, TemplateMilestone)}

        # Reject other application data before Django constructs any objects from the fixture.
        if not isinstance(payload, list) or not payload:
            raise ValueError('Supply a nonempty Django JSON template fixture.')
        for item in payload:

            # Explicit model limits exclude live diaries, users, groups, and unrelated application records.
            if not isinstance(item, dict) or item.get('model') not in allowed:
                raise ValueError('The fixture contains an unsupported model.')
        objects = {model: {} for model in allowed.values()}
        for record in serializers.deserialize('json', json.dumps(payload)):
            obj = record.object
            bucket = objects[type(obj)]

            # Source primary keys identify fixture references only and must not be ambiguous.
            if obj.pk is None or obj.pk in bucket:
                raise ValueError('Fixture records require distinct source primary keys.')
            bucket[obj.pk] = obj
        return objects

    def export_person_email(self, reference):
        """Resolve a Django person reference to a valid, unambiguous source email without changing stored ownership."""

        # Opaque references cannot be converted safely without a source identity adapter.
        if not reference.startswith('user:'):
            raise ValueError('Export requires Django user references for person owners.')
        model = get_user_model()
        user = model._default_manager.get(pk=reference[5:])
        email_field = model.get_email_field_name()
        email = getattr(user, email_field).strip().casefold()
        validate_email(email)

        # A shared source email cannot identify one portable person assignment.
        if model._default_manager.filter(**{f'{email_field}__iexact': email}).exclude(pk=user.pk).exists():
            raise ValueError(f'Person email {email!r} is ambiguous on the source deployment.')
        return email

    def person_mappings(self, values):
        """Normalize optional source-to-destination email overrides without using database user identifiers."""
        result = {}
        for value in values:
            source, separator, destination = value.partition('=')
            source, destination = source.strip().casefold(), destination.strip().casefold()

            # Explicit overrides must provide distinct source emails and valid destination emails.
            if not separator or source in result:
                raise ValueError('Use distinct --person-map SOURCE_EMAIL=LOCAL_EMAIL values.')
            validate_email(source)
            validate_email(destination)
            result[source] = destination
        return result

    def import_person_reference(self, email, mappings):
        """Resolve one exported email to exactly one active, eligible destination person."""
        source = email.strip().casefold()
        validate_email(source)
        destination = mappings.get(source, source)
        model = get_user_model()
        users = list(model._default_manager.filter(
            **{f'{model.get_email_field_name()}__iexact': destination}, is_active=True)[:2])

        # A missing or shared destination email must never assign the task to an unintended person.
        if len(users) != 1:
            raise ValueError(f'Person email {destination!r} must match exactly one active destination user.')
        return f'user:{users[0].pk}'

    @transaction.atomic
    def import_fixture(self, options):
        """Validate and save the entire fixture atomically, with optional rollback and explicit revision consent."""
        objects = self.read_fixture(options['fixture'])
        validate_task_owner_roles()
        mappings = self.person_mappings(options['person_map'])
        directory = DjangoOwnerDirectory()
        templates = objects[CalendarTemplate]
        versions = objects[TemplateVersion]
        entries = objects[TemplateEntry]
        milestones = objects[Milestone]

        # Duplicate logical milestone names could silently merge different source definitions.
        if len({item.name for item in milestones.values()}) != len(milestones):
            raise ValueError('Milestone names must be distinct in the fixture.')
        plans, used_versions, used_entries, used_milestones = [], set(), set(), set()
        used_declarations = set()
        names = set()
        for template in templates.values():
            name = template.name.strip()

            # Destination templates use case-insensitive names, so source definitions must be unambiguous.
            if not name or name.casefold() in names:
                raise ValueError('Template names must be nonempty and distinct.')
            names.add(name.casefold())

            # Source versions from other templates must not enter this template's import plan.
            selected = [version for version in versions.values() if version.template_id == template.pk]

            # A portable definition contains one approved snapshot rather than source audit history.
            if len(selected) != 1 or selected[0].status != VersionStatus.APPROVED:
                raise ValueError('Each template must contain exactly one approved version.')
            version = selected[0]
            used_versions.add(version.pk)
            specs, graph, definitions = [], {}, {}
            declared = set()
            for declaration in objects[TemplateMilestone].values():
                if declaration.version_id != version.pk:
                    continue
                if declaration.milestone_id in declared:
                    raise ValueError('Duplicate milestone declarations are not permitted.')
                declared.add(declaration.milestone_id)
                used_declarations.add(declaration.pk)
                milestone = milestones[declaration.milestone_id]
                definitions[milestone.name] = (milestone.label, milestone.description)
                used_milestones.add(milestone.pk)
            for entry in entries.values():

                # Only entries in this source version belong to the current import plan.
                if entry.version_id != version.pk:
                    continue
                used_entries.add(entry.pk)
                values = EntryMapper.snapshot_fields(entry)
                milestone_id = values.pop('milestone_id')
                values['milestone_name'] = ''

                # Resolve source milestone IDs by logical name, without reusing source database identities.
                if milestone_id is not None:
                    if milestone_id not in declared:
                        raise ValueError('Every task milestone must be explicitly declared by its template version.')
                    milestone = milestones[milestone_id]
                    values['milestone_name'] = milestone.name
                    definitions[milestone.name] = (milestone.label, milestone.description)
                    used_milestones.add(milestone_id)

                # Resolve portable emails to local person references before normal Diary ownership validation.
                if entry.owner_kind == OwnerKind.PERSON:
                    values['person_ref'] = self.import_person_reference(entry.person_ref, mappings)
                spec = EntrySpec(**values)
                validate_entry_owner(spec, directory)
                specs.append(spec)
                graph[entry.entry_key] = []
            plans.append((template, version, specs, graph, definitions))

        # Reject dangling or unselected definitions rather than silently ignoring parts of the fixture.
        if (not templates or used_versions != versions.keys() or used_entries != entries.keys()
                or used_milestones != milestones.keys() or used_declarations != objects[TemplateMilestone].keys()):
            raise ValueError('Every fixture record must belong to a selected template definition.')
        for link in objects[TemplateDependency].values():
            entry, predecessor = entries[link.entry_id], entries[link.predecessor_id]

            # A predecessor must come from the same source version as its dependent task.
            if entry.version_id != predecessor.version_id:
                raise ValueError('Dependencies cannot cross template versions.')
            for template, version, specs, graph, definitions in plans:

                # Each dependency belongs to exactly one planned version.
                if version.pk == entry.version_id:

                    # Repeated links must not disappear silently during graph normalization.
                    if predecessor.entry_key in graph[entry.entry_key]:
                        raise ValueError('Duplicate predecessor links are not permitted.')
                    graph[entry.entry_key].append(predecessor.entry_key)
        for template, version, specs, graph, definitions in plans:
            validate_template_graph((spec.entry_key for spec in specs), graph)
            self.save_plan(template, specs, graph, definitions, options, directory)

        # Dry runs execute the same model and API validation but never retain database writes.
        if options['dry_run']:
            transaction.set_rollback(True)
        self.stdout.write('Validated Diary template fixture.' if options['dry_run'] else 'Imported Diary template fixture.')

    def save_plan(self, source, specs, graph, definitions, options, directory):
        """Preserve identical definitions or approve an explicitly requested new destination version."""
        client = DiaryAPI(actor=self.actor)
        existing = CalendarTemplate.objects.select_for_update().filter(name__iexact=source.name.strip()).first()
        for name, (label, description) in definitions.items():
            milestone = Milestone.objects.filter(name=name).first()

            # Shared milestone names must not silently acquire different labels during transfer.
            if milestone is not None and (milestone.label != label or milestone.description != description):
                raise ValueError(f'Milestone {name!r} has different destination text.')

            # New milestone definitions use model validation and receive fresh destination identifiers.
            if milestone is None:
                Milestone.objects.create(name=name, label=label, description=description)
        expected = None

        # Existing templates retain their version history and all live diary copies.
        if existing is not None:
            reference = client.template(key=existing.pk)
            data = reference.editor_data()
            expected = data['version_key']
            stored = {entry.entry_key: entry for entry in TemplateEntry.objects.filter(version_id=expected)}
            same = (len(stored) == len(specs)
                    and {item['name'] for item in data['milestones']} == set(definitions))
            for spec in specs:

                # Stable entry keys and every reusable task field must match for a safe repeated import.
                if spec.entry_key not in stored:
                    same = False
                    continue
                values = EntryMapper.snapshot_fields(stored[spec.entry_key])
                values.pop('milestone_id')

                # Fixed-date tasks have no milestone name in their reusable specification.
                old = stored[spec.entry_key]
                values['milestone_name'] = old.milestone.name if old.milestone_id else ''

                # Any reusable field change requires a new approved destination version.
                if EntrySpec(**values) != spec:
                    same = False
            current_graph = {item['entry_key']: set(item['predecessors']) for item in data['entries']}

            # Identical approved content needs no extra version, but ownership and graph checks still ran above.
            if (same and data['status'] == VersionStatus.APPROVED and current_graph == {key: set(value) for key, value in graph.items()}
                    and existing.description == source.description):
                return

            # Different content needs explicit consent and never overwrites an existing version.
            if not options['new_version']:
                raise ValueError(f'Template {source.name!r} differs. Use --new-version to approve another version.')
        else:
            reference = client.create_template(name=source.name.strip(), description=source.description)
        reference.save_version(entries=specs, predecessors=graph, expected_version_key=expected,
                               description=source.description, milestone_names=tuple(definitions), directory=directory)
