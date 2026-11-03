"""Validate the complete predecessor graph submitted by a template editor."""
from uuid import UUID

from django.core.exceptions import ValidationError


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
