"""Add append-only, author-stamped task notes without changing existing tasks."""
import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('Diary', '0011_derive_template_milestones')]
    operations = [
        migrations.CreateModel(
            name='TaskNote',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('text', models.TextField()),
                ('author_ref', models.CharField(max_length=200)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('entry', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notes', to='Diary.calendarentry')),
            ],
            options={'ordering': ('created_at', 'id')},
        ),
        migrations.AddConstraint(
            model_name='tasknote',
            constraint=models.CheckConstraint(check=~models.Q(text=''), name='diary_task_note_text_present'),
        ),
        migrations.RunSQL('''
            CREATE FUNCTION diary_guard_task_note_history() RETURNS trigger
            LANGUAGE plpgsql AS $$
            DECLARE parent_exists boolean;
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I."Diary_calendarentry" e
                        JOIN %I."Diary_eventcalendar" c ON c.id = e.calendar_id WHERE e.id = $1)',
                        TG_TABLE_SCHEMA, TG_TABLE_SCHEMA) INTO parent_exists USING OLD.entry_id;
                    IF NOT parent_exists THEN RETURN OLD; END IF;
                END IF;
                RAISE EXCEPTION 'Saved task notes cannot be changed or deleted.' USING ERRCODE = '23514';
            END;
            $$;
            CREATE TRIGGER diary_task_note_history_guard
            BEFORE UPDATE OR DELETE ON "Diary_tasknote"
            FOR EACH ROW EXECUTE FUNCTION diary_guard_task_note_history();
        ''', '''
            DROP TRIGGER diary_task_note_history_guard ON "Diary_tasknote";
            DROP FUNCTION diary_guard_task_note_history();
        '''),
    ]
