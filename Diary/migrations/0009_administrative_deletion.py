"""Allow whole-object removal while retaining guards on surviving objects."""
from importlib import import_module

from django.db import migrations


def original_function(module, constant, function):
    sql = getattr(import_module('Diary.migrations.' + module), constant)
    return sql[sql.index('CREATE FUNCTION ' + function):].split('CREATE TRIGGER', 1)[0].replace(
        'CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION', 1)


DEPENDENCY = original_function('0006_freeze_live_dependencies', 'FORWARD_SQL', 'diary_guard_live_dependency_write')
MILESTONE = original_function('0007_freeze_live_milestones', 'FORWARD_SQL', 'diary_guard_live_milestone_write')
DECLARATION = original_function('0008_template_milestones', 'GUARD_SQL', 'diary_guard_template_milestone_write')

DEPENDENCY_DELETE = '''
    -- A whole-diary deletion removes its parent first, in the same transaction.
    IF TG_OP = 'DELETE' THEN
        EXECUTE format(
            'SELECT c.id IS NULL FROM %I."Diary_calendarentry" e
             JOIN %I."Diary_calendarentry" p ON p.id = $2 AND p.calendar_id = e.calendar_id
             LEFT JOIN %I."Diary_eventcalendar" c ON c.id = e.calendar_id WHERE e.id = $1',
            TG_TABLE_SCHEMA, TG_TABLE_SCHEMA, TG_TABLE_SCHEMA)
            INTO graph_locked USING OLD.entry_id, OLD.predecessor_id;
        IF graph_locked IS TRUE THEN RETURN OLD; END IF;
    END IF;
'''
MILESTONE_DELETE = '''
    IF TG_OP = 'DELETE' THEN
        EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I."Diary_eventcalendar" WHERE id = $1)', TG_TABLE_SCHEMA)
            INTO graph_locked USING OLD.calendar_id;
        IF NOT graph_locked THEN RETURN OLD; END IF;
    END IF;
'''
DECLARATION_DELETE = '''
    IF TG_OP = 'DELETE' THEN
        EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I."Diary_templateversion" WHERE id = $1)', TG_TABLE_SCHEMA)
            INTO used USING OLD.version_id;
        IF NOT used THEN RETURN OLD; END IF;
    END IF;
'''


class Migration(migrations.Migration):
    dependencies = [('Diary', '0008_template_milestones')]
    operations = [migrations.RunSQL(
        DEPENDENCY.replace('BEGIN', 'BEGIN\n' + DEPENDENCY_DELETE, 1)
        + MILESTONE.replace('BEGIN', 'BEGIN\n' + MILESTONE_DELETE, 1)
        + DECLARATION.replace('BEGIN', 'BEGIN\n' + DECLARATION_DELETE, 1),
        DEPENDENCY + MILESTONE + DECLARATION,
    )]
