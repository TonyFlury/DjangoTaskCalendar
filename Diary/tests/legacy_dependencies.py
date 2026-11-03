"""Prepare historical dependency graphs that existed before the V1 dependency freeze."""
from django.db import connection, transaction

from Diary.models import CalendarEntry, EntryDependency


# DV1-028: Legacy fixtures need historical graph shapes without restoring a production edit interface.
@transaction.atomic
def seed_legacy_dependencies(calendar_key, selections):
    """Set controlled test-fixture links that represent records saved before migration 0006.
    Temporarily disable only the new row trigger in the separate PostgreSQL test database.
    Restore it before returning. Production code must not import this helper.
    """
    with connection.cursor() as cursor:
        cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
        cursor.execute('SET CONSTRAINTS ALL DEFERRED')
        cursor.execute('ALTER TABLE "Diary_entrydependency" DISABLE TRIGGER diary_live_dependency_write_guard')
    try:
        for entry_key, predecessor_keys in selections:
            entry = CalendarEntry.objects.get(calendar_id=calendar_key, entry_key=entry_key)
            EntryDependency.objects.filter(entry=entry).delete()
            predecessors = CalendarEntry.objects.filter(calendar_id=calendar_key, entry_key__in=predecessor_keys)
            EntryDependency.objects.bulk_create([EntryDependency(entry=entry, predecessor=predecessor)
                                                 for predecessor in predecessors])
    finally:
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            cursor.execute('SET CONSTRAINTS ALL DEFERRED')
            cursor.execute('ALTER TABLE "Diary_entrydependency" ENABLE TRIGGER diary_live_dependency_write_guard')
