"""Allow personal diaries before a single, atomic template application."""
from importlib import import_module

import django.db.models.deletion
from django.db import migrations, models


original_function = import_module('Diary.migrations.0009_administrative_deletion').original_function
OLD_UNLOCK = original_function('0006_freeze_live_dependencies', 'FORWARD_SQL', 'diary_guard_dependency_unlock')
NEW_UNLOCK = OLD_UNLOCK.replace(
    'IF OLD.dependencies_locked AND NOT NEW.dependencies_locked THEN',
    '''IF OLD.dependencies_locked AND NOT NEW.dependencies_locked AND NOT (
        OLD.template_version_id IS NULL AND NEW.template_version_id IS NOT NULL
        AND OLD.closed_at IS NULL AND NEW.closed_at IS NULL
    ) THEN''')

ASSIGNMENT_SQL = r'''
CREATE FUNCTION diary_guard_template_assignment() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    populated boolean;
    approved boolean;
BEGIN
    IF OLD.template_version_id IS NOT DISTINCT FROM NEW.template_version_id THEN RETURN NEW; END IF;
    IF OLD.template_version_id IS NOT NULL THEN
        RAISE EXCEPTION 'An applied template cannot be removed or replaced.' USING ERRCODE = '23514';
    END IF;
    IF OLD.closed_at IS NOT NULL OR NEW.closed_at IS NOT NULL OR NOT OLD.dependencies_locked OR NEW.dependencies_locked THEN
        RAISE EXCEPTION 'Apply a template only while initializing an open template-free diary.' USING ERRCODE = '23514';
    END IF;
    EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I."Diary_templateversion" WHERE id = $1 AND status = ''approved'')', TG_TABLE_SCHEMA)
        INTO approved USING NEW.template_version_id;
    IF NOT approved THEN
        RAISE EXCEPTION 'Select an approved template version.' USING ERRCODE = '23514';
    END IF;
    EXECUTE format(
        'SELECT EXISTS(SELECT 1 FROM %I."Diary_calendarentry" WHERE calendar_id = $1 AND source_entry_id IS NOT NULL)
             OR EXISTS(SELECT 1 FROM %I."Diary_calendarmilestone" WHERE calendar_id = $1)
             OR EXISTS(SELECT 1 FROM %I."Diary_entrydependency" d JOIN %I."Diary_calendarentry" e ON e.id = d.entry_id WHERE e.calendar_id = $1)',
        TG_TABLE_SCHEMA, TG_TABLE_SCHEMA, TG_TABLE_SCHEMA, TG_TABLE_SCHEMA)
        INTO populated USING OLD.id;
    IF populated THEN
        RAISE EXCEPTION 'Template application cannot replace existing template data.' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER diary_template_assignment_guard
BEFORE UPDATE OF template_version_id ON "Diary_eventcalendar"
FOR EACH ROW EXECUTE FUNCTION diary_guard_template_assignment();
'''


class Migration(migrations.Migration):
    dependencies = [('Diary', '0009_administrative_deletion')]
    operations = [
        migrations.AlterField(
            model_name='eventcalendar', name='template_version',
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='calendars', to='Diary.templateversion')),
        migrations.RunSQL(NEW_UNLOCK + ASSIGNMENT_SQL, '''
            DROP TRIGGER diary_template_assignment_guard ON "Diary_eventcalendar";
            DROP FUNCTION diary_guard_template_assignment();
        ''' + OLD_UNLOCK),
    ]
