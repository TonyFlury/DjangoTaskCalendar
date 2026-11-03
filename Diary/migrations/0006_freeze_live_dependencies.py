"""DV1-028: Freeze diary dependencies after their initial template snapshot."""
from django.db import migrations, models


FORWARD_SQL = r'''
-- DV1-028: Permit only initial links in a new diary and reject later row mutations.
CREATE FUNCTION diary_guard_live_dependency_write() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    graph_locked boolean;
BEGIN

    -- Existing links cannot change, even during initialization.
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'V1 does not allow dependency changes in an existing diary.'
            USING ERRCODE = '23514';
    END IF;

    -- Only entries in the same new diary can receive initial snapshot links.
    EXECUTE format(
        'SELECT calendar.dependencies_locked
         FROM %I."Diary_calendarentry" AS entry
         JOIN %I."Diary_calendarentry" AS predecessor
           ON predecessor.id = $2 AND predecessor.calendar_id = entry.calendar_id
         JOIN %I."Diary_eventcalendar" AS calendar ON calendar.id = entry.calendar_id
         WHERE entry.id = $1',
        TG_TABLE_SCHEMA, TG_TABLE_SCHEMA, TG_TABLE_SCHEMA
    ) INTO graph_locked USING NEW.entry_id, NEW.predecessor_id;

    -- Missing entries, cross-diary links, and locked diaries cannot accept a dependency.
    IF graph_locked IS DISTINCT FROM FALSE THEN
        RAISE EXCEPTION 'V1 does not allow dependency changes in an existing diary.'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER diary_live_dependency_write_guard
BEFORE INSERT OR UPDATE OR DELETE ON "Diary_entrydependency"
FOR EACH ROW EXECUTE FUNCTION diary_guard_live_dependency_write();

-- DV1-028: Prevent a live diary from returning to dependency initialization.
CREATE FUNCTION diary_guard_dependency_unlock() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN

    -- A completed initialization cannot be reopened through model, bulk, or direct SQL updates.
    IF OLD.dependencies_locked AND NOT NEW.dependencies_locked THEN
        RAISE EXCEPTION 'A diary dependency graph cannot be unlocked in V1.'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER diary_dependency_unlock_guard
BEFORE UPDATE OF dependencies_locked ON "Diary_eventcalendar"
FOR EACH ROW EXECUTE FUNCTION diary_guard_dependency_unlock();

-- DV1-028: Require every new diary to finish initialization before its transaction commits.
CREATE FUNCTION diary_require_dependency_lock() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    graph_locked boolean;
BEGIN
    EXECUTE format('SELECT dependencies_locked FROM %I."Diary_eventcalendar" WHERE id = $1', TG_TABLE_SCHEMA)
        INTO graph_locked USING NEW.id;

    -- Read the final row state because creation inserts an unlocked row before locking it in the same transaction.
    IF graph_locked IS FALSE THEN
        RAISE EXCEPTION 'Diary dependency initialization must finish in its creation transaction.'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER diary_dependency_initialization_complete
AFTER INSERT OR UPDATE ON "Diary_eventcalendar"
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION diary_require_dependency_lock();

-- DV1-028: Keep referenced task identities and diary membership unchanged.
CREATE FUNCTION diary_guard_dependency_endpoint_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    has_dependencies boolean;
BEGIN

    -- Unchanged task identities do not affect the frozen graph or prevent normal task updates.
    IF (NEW.id, NEW.entry_key, NEW.calendar_id) IS NOT DISTINCT FROM (OLD.id, OLD.entry_key, OLD.calendar_id) THEN
        RETURN NEW;
    END IF;
    EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I."Diary_entrydependency" WHERE entry_id = $1 OR predecessor_id = $1)',
                   TG_TABLE_SCHEMA) INTO has_dependencies USING OLD.id;

    -- A referenced task cannot move to another diary or change the identity used by its dependency links.
    IF has_dependencies THEN
        RAISE EXCEPTION 'A task referenced by a diary dependency cannot change its identity.'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER diary_dependency_endpoint_identity_guard
BEFORE UPDATE OF id, entry_key, calendar_id ON "Diary_calendarentry"
FOR EACH ROW EXECUTE FUNCTION diary_guard_dependency_endpoint_identity();
'''

REVERSE_SQL = r'''
DROP TRIGGER diary_dependency_endpoint_identity_guard ON "Diary_calendarentry";
DROP FUNCTION diary_guard_dependency_endpoint_identity();
DROP TRIGGER diary_dependency_initialization_complete ON "Diary_eventcalendar";
DROP FUNCTION diary_require_dependency_lock();
DROP TRIGGER diary_dependency_unlock_guard ON "Diary_eventcalendar";
DROP FUNCTION diary_guard_dependency_unlock();
DROP TRIGGER diary_live_dependency_write_guard ON "Diary_entrydependency";
DROP FUNCTION diary_guard_live_dependency_write();
'''


class Migration(migrations.Migration):
    """Lock existing graphs without changing links and enforce creation-only initialization in PostgreSQL."""

    dependencies = [('Diary', '0005_task_dates_and_completion')]
    operations = [
        migrations.AddField(model_name='eventcalendar', name='dependencies_locked',
                            field=models.BooleanField(default=True, editable=False)),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
