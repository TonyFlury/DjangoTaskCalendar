"""DFUT-019: Manager-only graph records with scoped identities and fixed-date provenance."""
from types import SimpleNamespace

from django.core.exceptions import ValidationError

from .choices import DateKind
from .models import CalendarEntry
from .ownership import orphaned_entry_keys


def task_key(diary_key, entry_key):
    """Return an opaque renderer key that cannot collide with a milestone node."""
    return f'{diary_key}:task:{entry_key}'


def diary_graph(instance, *, include_completed, exclude_blocked, exclude_non_late, today, directory):
    """Calculate status from the full authorised graph, then expose only matching endpoints."""
    from .api import _require, _comparison_date
    _require(instance.actor, 'edit')
    for flag in (include_completed, exclude_blocked, exclude_non_late):
        if type(flag) is not bool:
            raise ValidationError('Graph filter flags must be booleans.')
    today = _comparison_date(today)
    calendar, tasks = instance._calendar_tasks(today=today)
    tasks = tuple(row for row in tasks if not (
        row['completed_at'] is not None and not include_completed
        or row['state'] == 'blocked' and exclude_blocked
        or not row['late'] and exclude_non_late))
    # The default Django adapter can batch person eligibility; custom adapters retain their protocol.
    batch = getattr(directory, 'people_in_groups', None)
    ownership_directory = directory
    if callable(batch):
        from .roles import access_groups
        eligibility = batch({row['person_ref'] for row in tasks if row['person_ref']}, frozenset({access_groups()['user']}))
        # Keep batching local to this read; never leave stale access decisions on a host adapter.
        ownership_directory = SimpleNamespace(person_in_groups=lambda reference, groups: eligibility.get(reference, False))
    orphaned = orphaned_entry_keys(tasks, directory=ownership_directory)
    visible = {row['entry_key'] for row in tasks}
    fields = {row['entry_key']: row for row in CalendarEntry.objects.filter(calendar_id=instance.key, entry_key__in=visible).values(
        'entry_key', 'date_kind', 'milestone__name', 'milestone__label', 'day_offset', 'source_task_key',
        'task_due_date', 'due_date_override')}
    nodes, edges, milestones = [], [], {}
    by_key = {row['entry_key']: row for row in tasks}
    for row in tasks:
        completed = row['completed_at'] is not None
        state = ('completed' if completed else 'late' if row['late'] else 'blocked-late' if row['blocked_late']
                 and not row['ready'] else row['state'])
        label = ('Completed' if completed else 'Late · Blocked' if row['late'] and not row['ready'] else 'Late'
                 if row['late'] else 'Blocked · late prerequisite' if state == 'blocked-late' else row['state'].capitalize())
        if row['late'] and row['date'] == today:
            label += ' · Due today'
        nodes.append({'key': task_key(instance.key, row['entry_key']), 'kind': 'task', 'diary_key': instance.key,
            'entry_key': row['entry_key'], 'name': row['name'], 'description': row['description'], 'date': row['date'],
            'state': state, 'status_label': label, 'completed': completed, 'completed_at': row['completed_at'],
            'completed_by_ref': row['completed_by_ref'], 'blocked': not completed and not row['ready'],
            'late': row['late'], 'blocked_late': row['blocked_late'] and not completed,
            'orphaned': row['entry_key'] in orphaned, 'undated': row['date'] is None,
            'source': row['source'], 'owner_kind': row['owner_kind'], 'person_ref': row['person_ref'],
            'role_ref': row['role_ref'], 'revision': row['revision'], 'context_outside_view': False})
    node_map = {node['entry_key']: node for node in nodes}
    for row in tasks:
        target = task_key(instance.key, row['entry_key'])
        node = node_map[row['entry_key']]
        for predecessor in row['predecessors']:
            if predecessor not in visible:
                node['context_outside_view'] = True
                continue
            active = not node['completed'] and by_key[predecessor]['completed_at'] is None
            edges.append({'source': task_key(instance.key, predecessor), 'target': target,
                          'kind': 'dependency', 'active_blocker': active,
                          'description': 'Completion prerequisite' + (' · active blocker' if active else ' · not an active blocker')})
        spec = fields[row['entry_key']]
        if spec['date_kind'] in {DateKind.SOURCE, DateKind.RELATIVE} and spec['milestone__name']:
            name = spec['milestone__name']
            source = f'{instance.key}:milestone:{name}'
            milestones[source] = {'key': source, 'kind': 'milestone', 'diary_key': instance.key,
                'milestone_name': name, 'name': spec['milestone__label'], 'date': calendar['milestones'].get(name)}
            offset = spec['day_offset'] if spec['date_kind'] == DateKind.RELATIVE else 0
            description = f'Milestone date source · offset {offset:+d} calendar days'
        elif spec['date_kind'] == DateKind.TASK:
            if spec['source_task_key'] not in visible:
                node['context_outside_view'] = True
                continue
            source = task_key(instance.key, spec['source_task_key'])
            offset = spec['day_offset']
            description = f'Task date source · original offset {offset:+d} calendar days · initialized due {spec["task_due_date"]}; snapshot stays fixed'
        else:
            continue
        if spec['due_date_override'] is not None:
            description += f' · explicit due date override {spec["due_date_override"]}'
        edges.append({'source': source, 'target': target, 'kind': 'date', 'offset': offset,
                      'description': description, 'active_blocker': False})
    return {'diary': {'key': instance.key, 'name': calendar['name'], 'closed': calendar['closed']},
            'today': today, 'count': len(tasks), 'milestone_count': len(milestones),
            'undated_count': sum(node['undated'] for node in nodes),
            'nodes': tuple([*nodes, *milestones.values()]), 'edges': tuple(edges)}
