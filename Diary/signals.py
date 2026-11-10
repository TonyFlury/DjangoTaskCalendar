"""DFUT-007: Committed task events for host applications.

Receivers accept sender, user, task, and **kwargs (including 'task-name').
The sender is CalendarEntry or TemplateEntry; task is the stable UUID.
"""
from django.db import transaction
from django.dispatch import Signal

task_created = Signal()
task_note_added = Signal()
task_dependency_changed = Signal()
task_closed = Signal()
task_ownership_changed = Signal()


def _queue_task_event(signal, *, actor, entry):
    """Snapshot the payload now; notify all receivers after the outer commit.

    Receiver failures are logged by Django and cannot undo a committed change.
    Email is trusted caller context, never a submitted form value.
    """
    payload = {'user': actor.email, 'task': entry.entry_key, 'task-name': entry.name}
    sender = type(entry)

    def dispatch():
        # Catch receiver exceptions individually so other receivers still run.
        signal.send_robust(sender=sender, **payload)

    # Commit first. Also catch dispatch errors so the caller still receives success.
    # Use a named callback: Django 5.0 logs its __qualname__ on failure.
    transaction.on_commit(dispatch, using=entry._state.db, robust=True)
