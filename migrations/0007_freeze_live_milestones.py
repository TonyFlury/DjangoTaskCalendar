"""DV1-043: Prevent milestone changes after the initial diary creation transaction."""
from django.db import migrations


FORWARD_SQL = r'''
CREATE FUNCTION diary_guard_live_milestone_write() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    graph_locked boolean;
BEGIN

    -- Existing milestone rows cannot be replaced or removed in V1.
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'V1 does not allow milestone changes in an existing diary.' USING ERRCODE = '23514';
    END IF;
    EXECUTE format('SELECT dependencies_locked FROM %I."Diary_eventcalendar" WHERE id = $1', TG_TABLE_SCHEMA)
        INTO graph_locked USING NEW.calendar_id;

    -- Only the initial diary transaction can add milestone rows before its graph is locked.
    IF graph_locked IS DISTINCT FROM FALSE THEN
        RAISE EXCEPTION 'V1 does not allow milestone changes in an existing diary.' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER diary_live_milestone_write_guard
BEFORE INSERT OR UPDATE OR DELETE ON "Diary_calendarmilestone"
FOR EACH ROW EXECUTE FUNCTION diary_guard_live_milestone_write();
'''

REVERSE_SQL = r'''
DROP TRIGGER diary_live_milestone_write_guard ON "Diary_calendarmilestone";
DROP FUNCTION diary_guard_live_milestone_write();
'''


class Migration(migrations.Migration):
    """Install the milestone guard without changing saved dates or completion records."""

    dependencies = [('Diary', '0006_freeze_live_dependencies')]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
