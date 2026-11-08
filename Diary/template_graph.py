"""Validate the complete predecessor graph submitted by a template editor."""
from uuid import UUID
from collections import deque

from django.core.exceptions import ValidationError


def ordered_task_choices(entries, *, date_sources=False):
    """Group visible tasks by connected subgraph, then put sources before dependants.

    Preserve input order for ties and unrelated groups. This is presentation only:
    missing references are ignored and cyclic/invalid input remains visible for
    normal form validation. Completion and date-reference graphs stay independent.
    """
    entries = tuple(entries)
    if date_sources:
        entries = ordered_task_choices(entries)
    keys = [str(entry['entry_key']) for entry in entries]
    if len(set(keys)) != len(keys):
        return entries
    known = set(keys)
    incoming = {}
    outgoing = {key: [] for key in keys}
    neighbors = {key: set() for key in keys}
    for key, entry in zip(keys, entries):
        references = ((entry.get('source_task_key'),) if date_sources
                      else (entry.get('predecessors') or ()))
        incoming[key] = {str(reference) for reference in references if reference is not None} & known
        for source in incoming[key]:
            outgoing[source].append(key)
            neighbors[key].add(source)
            neighbors[source].add(key)
    by_key = dict(zip(keys, entries))
    seen, ordered = set(), []
    for key in keys:
        if key in seen:
            continue
        component, pending = {key}, [key]
        while pending:
            current = pending.pop()
            for neighbor in neighbors[current] - component:
                component.add(neighbor)
                pending.append(neighbor)
        members = [candidate for candidate in keys if candidate in component]
        remaining = {candidate: len(incoming[candidate]) for candidate in members}
        ready = deque(candidate for candidate in members if not remaining[candidate])
        while ready:
            current = ready.popleft()
            seen.add(current)
            ordered.append(by_key[current])
            for successor in outgoing[current]:
                remaining[successor] -= 1
                if remaining[successor] == 0:
                    ready.append(successor)
        # Keep all choices available when an unsaved date graph contains a cycle.
        for current in members:
            if current not in seen:
                seen.add(current)
                ordered.append(by_key[current])
    return tuple(ordered)


# DV1-027: Safe template predecessor editor.
def validate_template_graph(entry_keys, predecessors):
    """Return normalized predecessor sets for all entries.
    Reject duplicate keys, unknown tasks, self links, and circular dependencies.
    """
    keys = [UUID(str(key)) for key in entry_keys]

    # Duplicate identities would combine two different tasks during graph validation.
    if len(set(keys)) != len(keys):
        raise ValidationError('Each task must have a different entry key.')
    graph = {key: set() for key in keys}
    for key, values in predecessors.items():
        key = UUID(str(key))

        # Every endpoint must belong to the submitted version, including tasks removed in this edit.
        if key not in graph:
            raise ValidationError('Predecessors must refer to tasks in this template version.')
        graph[key] = {UUID(str(value)) for value in values}

        # Unknown endpoints and self links cannot form valid dependencies.
        if not graph[key] <= graph.keys() or key in graph[key]:
            raise ValidationError('Select other tasks in this template as predecessors.')
    successors = {key: set() for key in keys}
    remaining = {key: len(values) for key, values in graph.items()}
    for key, values in graph.items():
        for predecessor in values:
            successors[predecessor].add(key)

    # Only tasks without predecessors can start a valid dependency order.
    pending = [key for key, count in remaining.items() if count == 0]
    visited = 0

    # Process each dependency once without a recursion limit for large templates.
    while pending:
        key = pending.pop()
        visited += 1
        for successor in successors[key]:
            remaining[successor] -= 1

            # A task becomes available after all its predecessors have been processed.
            if remaining[successor] == 0:
                pending.append(successor)

    # Unprocessed tasks identify a cycle in the proposed graph.
    if visited != len(keys):
        raise ValidationError('The proposed predecessors create a circular dependency.')
    return graph
