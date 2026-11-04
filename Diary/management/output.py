"""Human-readable command results with an explicit JSON format for scripts."""
import json
from datetime import date, datetime

from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone


LABELS = {
    'id': 'UUID', 'key': 'UUID', 'entry_key': 'Task UUID', 'version_key': 'Version UUID',
    'template_key': 'Template UUID', 'diary_key': 'Diary UUID', 'number': 'Version',
    'entries': 'Tasks', 'event_ref': 'Host reference', 'date_kind': 'Date rule',
    'template_version__template__name': 'Template', 'template_version__number': 'Version',
}


def text_value(value):
    if value is None or value == '':
        return 'Not set'
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value, timezone.get_default_timezone())
        return value.strftime('%d %b %Y %H:%M %Z').rstrip()
    if isinstance(value, date):
        return value.strftime('%d %b %Y')
    return str(value)


def write_command_result(stdout, result, *, as_json=False):
    """Keep successful JSON output free of progress messages and human labels."""
    if as_json:
        stdout.write(json.dumps(result, cls=DjangoJSONEncoder, indent=2))
        return
    if isinstance(result, dict) and 'deleted' in result:
        stdout.write('Deletion completed.' if result['deleted'] else 'Deletion preview (no records deleted).')
    _write_value(stdout, result)


def _write_value(stdout, value, indent=0):
    padding = ' ' * indent
    if isinstance(value, dict):
        remaining = dict(value)
        if remaining.get('message'):
            stdout.write(padding + str(remaining.pop('message')))
        if remaining.get('name'):
            stdout.write(padding + str(remaining.pop('name')))
            indent += 2
            padding = ' ' * indent
        for key, item in remaining.items():
            label = LABELS.get(key, key.replace('_', ' ').capitalize())
            if isinstance(item, (dict, list, tuple)):
                if item:
                    stdout.write(f'{padding}{label}:')
                    _write_value(stdout, item, indent + 2)
                else:
                    stdout.write(f'{padding}{label}: None')
            else:
                lines = text_value(item).splitlines()
                stdout.write(f'{padding}{label}: {lines[0]}')
                for line in lines[1:]:
                    stdout.write(' ' * (indent + len(label) + 2) + line)
    elif isinstance(value, (list, tuple)):
        if not value:
            stdout.write(padding + 'None')
        for index, item in enumerate(value):
            if isinstance(item, dict):
                if index:
                    stdout.write('')
                if 'number' in item and 'name' not in item:
                    stdout.write(f"{padding}Version {item['number']}")
                    _write_value(stdout, {key: value for key, value in item.items() if key != 'number'}, indent + 2)
                else:
                    _write_value(stdout, item, indent)
            else:
                stdout.write(padding + '- ' + text_value(item))
    else:
        stdout.write(padding + text_value(value))
