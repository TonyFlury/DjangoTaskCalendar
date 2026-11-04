"""Enumerate, inspect, create, close, and remove diary instances."""
from dataclasses import replace
from datetime import date
from uuid import UUID

from django.db.models import Count, Q
from django.utils import timezone

from Diary.api import DiaryAPI
from Diary.management.administration import OperatorCommand, delete_diary
from Diary.models import EventCalendar


class Command(OperatorCommand):
    help = 'Manage Diary instances. Lists show names; use --details for readable metadata or --json for scripts.'

    def add_arguments(self, parser):
        parser.add_argument('operation', choices=('list', 'show', 'create', 'close', 'delete'))
        self.add_operator_arguments(parser)
        parser.add_argument('--uuid', action='store_true', help='Show each item UUID alongside its name when listing.')
        output = parser.add_mutually_exclusive_group()
        output.add_argument('--details', '--full', action='store_true', help='Show formatted dates, task counts, and identifiers when listing.')
        output.add_argument('--json', action='store_true', help='Return full list records as JSON for scripts.')
        parser.add_argument('--diary', type=UUID, help='Exact diary UUID for show, close, or delete; names are not unique.')
        parser.add_argument('--state', choices=('all', 'open', 'closed'), default='all', help='Filter list results.')
        parser.add_argument('--template', help='Template name for creation or filtering list results.')
        parser.add_argument('--template-version', type=int, help='Use this template version for creation; otherwise latest approved.')
        parser.add_argument('--name', help='Display name for a new diary.')
        parser.add_argument('--event-ref', help='Host reference for creation retries or filtering list results.')
        parser.add_argument('--milestone', action='append', default=[], metavar='NAME=YYYY-MM-DD',
                            help='Supply a milestone date for creation. Repeat for every required milestone.')

    def execute_operation(self, options):
        operation = options['operation']
        allowed = {'list': {'state', 'template', 'event_ref', 'details', 'json', 'uuid'},
                   'create': {'template', 'template_version', 'name', 'event_ref', 'milestone'},
                   'show': {'diary'}, 'close': {'diary'}, 'delete': {'diary'}}[operation]
        self.reject_unused(options, allowed, {'diary': None, 'state': 'all', 'template': None,
            'template_version': None, 'name': None, 'event_ref': None, 'milestone': [], 'details': False, 'json': False, 'uuid': False})
        if options['details'] and options['json']:
            raise ValueError('--details and --json cannot be combined.')
        if operation == 'list':
            diaries = EventCalendar.objects.all()
            if options['state'] != 'all':
                diaries = diaries.filter(closed_at__isnull=options['state'] == 'open')
            if options['template']:
                diaries = diaries.filter(template_version__template__name__iexact=options['template'])
            if options['event_ref']:
                diaries = diaries.filter(event_ref=options['event_ref'])
            if not (options['details'] or options['json']):
                return list(diaries.order_by('name', 'pk').values('id', 'name'))
            diaries = diaries.annotate(
                task_count=Count('entries'), completed_count=Count('entries', filter=Q(entries__completed_at__isnull=False)))
            return list(diaries.order_by('name', 'pk').values(
                'id', 'name', 'event_ref', 'template_version_id', 'template_version__template__name',
                'template_version__number', 'created_at', 'closed_at', 'task_count', 'completed_count'))
        api = DiaryAPI(actor=self.actor)
        if operation == 'create':
            self.require(options, 'name', 'template')
            dates = {}
            for value in options['milestone']:
                name, separator, text = value.partition('=')
                if not separator or not name or name in dates:
                    raise ValueError('Use distinct --milestone NAME=YYYY-MM-DD values.')
                dates[name] = date.fromisoformat(text)
            selection = {'template_name': options['template']}
            if options['template_version'] is not None:
                selection = {'template_version_key': api.template(name=options['template']).version(number=options['template_version']).key}
            diary = api.create_diary(name=options['name'], event_ref=options['event_ref'], milestone_dates=dates, **selection)
            # Operator access is explicit for the selected object, not derived from host session policy.
            return DiaryAPI(actor=replace(self.actor, calendar_keys=frozenset({diary.key}))).diary(key=diary.key).read()
        self.require(options, 'diary')
        options['diary'] = UUID(str(options['diary']))
        if operation == 'delete':
            return delete_diary(key=options['diary'], actor=self.actor, execute=options['yes'] and not options['dry_run'])
        diary = DiaryAPI(actor=replace(self.actor, calendar_keys=frozenset({options['diary']}))).diary(key=options['diary'])
        if operation == 'close':
            diary.close()
        return diary.read()

    def write_result(self, result, options):
        if options['operation'] != 'list' or options['json']:
            return super().write_result(result, options)
        for index, diary in enumerate(result):
            if options['details'] and index:
                self.stdout.write('')
            self.stdout.write(f"{diary['id']}  {diary['name']}" if options['uuid'] else diary['name'])
            if options['details']:
                fields = [('ID', diary['id']),
                          ('Status', 'Closed' if diary['closed_at'] else 'Open'),
                          ('Created', self.format_timestamp(diary['created_at'])),
                          ('Template', f"{diary['template_version__template__name']} (version {diary['template_version__number']})"),
                          ('Tasks', f"{diary['task_count']} total, {diary['completed_count']} completed, "
                                    f"{diary['task_count'] - diary['completed_count']} open"),
                          ('Host reference', diary['event_ref'])]
                if diary['closed_at']:
                    fields.append(('Closed', self.format_timestamp(diary['closed_at'])))
                if options['uuid']:
                    fields = [(label, value) for label, value in fields if label != 'ID']
                for label, value in fields:
                    self.stdout.write(f'  {label + ":":15} {value}')

    @staticmethod
    def format_timestamp(value):
        if timezone.is_aware(value):
            value = timezone.localtime(value, timezone.get_default_timezone())
        return value.strftime('%d %b %Y %H:%M %Z').rstrip()
