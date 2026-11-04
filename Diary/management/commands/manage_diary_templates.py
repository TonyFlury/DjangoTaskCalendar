"""Enumerate and administer template definitions and version lifecycles."""
from django.db import transaction
from django.db.models import Count, Prefetch

from Diary.api import DiaryAPI, EntrySpec
from Diary.management.administration import OperatorCommand, delete_template
from Diary.models import CalendarTemplate, TemplateVersion


class Command(OperatorCommand):
    help = 'Manage Diary templates. Lists show names; use --details for versions and usage or --json for scripts.'

    def add_arguments(self, parser):
        parser.add_argument('operation', choices=('list', 'show', 'versions', 'create', 'create-version',
                                                'approve', 'delete-version', 'delete'))
        self.add_operator_arguments(parser)
        output = parser.add_mutually_exclusive_group()
        output.add_argument('--details', '--full', action='store_true', help='List descriptions, versions, declared milestones, and diary usage.')
        output.add_argument('--json', action='store_true', help='Return full list records as JSON for scripts.')
        parser.add_argument('--template', help='Exact template name (case insensitive). Required except for list.')
        parser.add_argument('--template-version', type=int, help='Version number for show, approve, or delete-version.')
        parser.add_argument('--copy-version', type=int, help='Copy this version into a new draft, preserving its requirements and tasks.')
        parser.add_argument('--milestone', action='append', default=[], help='Declare an existing milestone name on a new empty draft. Repeat as needed.')
        parser.add_argument('--description', default='', help='Description for template creation.')

    @transaction.atomic
    def execute_operation(self, options):
        operation = options['operation']
        allowed = {'template'}
        if operation == 'list':
            allowed.update(('details', 'json'))
        if operation in {'show', 'approve', 'delete-version'}:
            allowed.add('template_version')
        if operation == 'create-version':
            allowed.update(('copy_version', 'milestone'))
        if operation == 'create':
            allowed.add('description')
        self.reject_unused(options, allowed, {'template_version': None, 'copy_version': None, 'milestone': [],
                                             'description': '', 'details': False, 'json': False})
        if options['details'] and options['json']:
            raise ValueError('--details and --json cannot be combined.')
        api = DiaryAPI(actor=self.actor)
        if operation == 'list':
            templates = CalendarTemplate.objects.order_by('name')
            if options['template']:
                templates = templates.filter(name__iexact=options['template'])
            if options['details']:
                versions = TemplateVersion.objects.annotate(diary_count=Count('calendars')).order_by('number').prefetch_related('milestones')
                templates = templates.prefetch_related(Prefetch('versions', queryset=versions))
                return [{'name': item.name, 'description': item.description,
                         'versions': [{'number': version.number, 'status': version.status,
                                       'diary_count': version.diary_count,
                                       'milestones': [(milestone.name, milestone.label) for milestone in version.milestones.all()]}
                                      for version in item.versions.all()]}
                        for item in templates]
            if options['json']:
                return list(templates.annotate(version_count=Count('versions')).values('id', 'name', 'description', 'version_count'))
            return list(templates.values('name'))
        self.require(options, 'template')
        if operation == 'create':
            template = api.create_template(name=options['template'], description=options['description'])
            return template.editor_data()
        template = api.template(name=options['template'])
        if operation == 'show':
            return template.version(number=options['template_version']).read() if options['template_version'] is not None else template.editor_data()
        if operation == 'versions':
            return list(CalendarTemplate.objects.get(pk=template.key).versions.annotate(
                task_count=Count('entries', distinct=True), diary_count=Count('calendars', distinct=True),
                milestone_count=Count('milestones', distinct=True)).order_by('number').values(
                    'id', 'number', 'status', 'created_by_ref', 'created_at', 'approved_by_ref', 'approved_at',
                    'task_count', 'diary_count', 'milestone_count'))
        if operation == 'create-version':
            CalendarTemplate.objects.select_for_update().get(pk=template.key)
            source = None
            if options['copy_version'] is not None:
                if options['milestone']:
                    raise ValueError('--milestone cannot be combined with --copy-version.')
                TemplateVersion.objects.select_for_update().get(template_id=template.key, number=options['copy_version'])
                source = template.version(number=options['copy_version']).read()
            latest = CalendarTemplate.objects.get(pk=template.key).versions.order_by('-number').first()
            number = latest.number + 1 if latest else 1
            names = tuple(item['name'] for item in source['milestones']) if source else tuple(options['milestone'])
            version = template.create_version(number=number, milestone_names=names)
            if source:
                from Diary.views import DjangoOwnerDirectory
                for item in source['entries']:
                    values = {name: item[name] for name in EntrySpec.__dataclass_fields__ if name in item}
                    values['milestone_name'] = values.get('milestone_name') or ''
                    version.add_entry(spec=EntrySpec(**values), directory=DjangoOwnerDirectory())
                for item in source['entries']:
                    version.set_predecessors(entry_key=item['entry_key'], predecessor_keys=item['predecessors'])
            return version.read()
        if operation == 'approve':
            self.require(options, 'template_version')
            return template.version(number=options['template_version']).approve().read()
        if operation == 'delete-version':
            self.require(options, 'template_version')
        return delete_template(key=template.key, actor=self.actor,
            number=options['template_version'] if operation == 'delete-version' else None,
            execute=options['yes'] and not options['dry_run'])

    def write_result(self, result, options):
        if options['operation'] != 'list' or options['json']:
            return super().write_result(result, options)
        for index, template in enumerate(result):
            if options['details'] and index:
                self.stdout.write('')
            self.stdout.write(template['name'])
            if options['details']:
                description = '\n                 '.join(template['description'].splitlines()) or '(none)'
                self.stdout.write(f'  Description:   {description}')
                count = sum(version['diary_count'] for version in template['versions'])
                self.stdout.write(f'  In use:        {self.usage_label(count)}')
                if not template['versions']:
                    self.stdout.write('  Versions:      None')
                for version in template['versions']:
                    self.stdout.write(f"  Version {version['number']} ({version['status']})")
                    milestones = ', '.join(f'{label} ({name})' for name, label in version['milestones']) or 'None'
                    self.stdout.write(f'    Milestones:  {milestones}')
                    self.stdout.write(f"    In use:      {self.usage_label(version['diary_count'])}")

    @staticmethod
    def usage_label(count):
        if not count:
            return 'No'
        return f'Yes ({count} {"diary" if count == 1 else "diaries"})'
