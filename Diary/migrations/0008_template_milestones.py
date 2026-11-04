"""Declare version milestone requirements without changing existing diaries."""

import django.db.models.deletion
from django.db import migrations, models


def declare_existing_milestones(apps, schema_editor):
    entries = apps.get_model('Diary', 'TemplateEntry')
    declarations = apps.get_model('Diary', 'TemplateMilestone')
    alias = schema_editor.connection.alias
    pairs = entries.objects.using(alias).exclude(milestone_id=None).order_by().values_list(
        'version_id', 'milestone_id').distinct()
    declarations.objects.using(alias).bulk_create([
        declarations(version_id=version, milestone_id=milestone) for version, milestone in pairs
    ])


GUARD_SQL = r'''
CREATE FUNCTION diary_guard_template_milestone_write() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    version_key uuid;
    version_status varchar;
    used boolean;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'Delete a milestone declaration before replacing it.' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN version_key := OLD.version_id;
    ELSE version_key := NEW.version_id;
    END IF;
    EXECUTE format('SELECT status FROM %I."Diary_templateversion" WHERE id = $1 FOR UPDATE', TG_TABLE_SCHEMA)
        INTO version_status USING version_key;
    IF version_status IS DISTINCT FROM 'draft' THEN
        RAISE EXCEPTION 'Milestones in an approved template version cannot change.' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN
        EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I."Diary_templateentry" WHERE version_id = $1 AND milestone_id = $2)', TG_TABLE_SCHEMA)
            INTO used USING OLD.version_id, OLD.milestone_id;
        IF used THEN
            RAISE EXCEPTION 'This milestone is still used by template tasks.' USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER diary_template_milestone_write_guard
BEFORE INSERT OR UPDATE OR DELETE ON "Diary_templatemilestone"
FOR EACH ROW EXECUTE FUNCTION diary_guard_template_milestone_write();
'''


class Migration(migrations.Migration):

    dependencies = [
        ('Diary', '0007_freeze_live_milestones'),
    ]

    operations = [
        migrations.CreateModel(
            name='TemplateMilestone',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('milestone', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='Diary.milestone')),
                ('version', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='milestone_declarations', to='Diary.templateversion')),
            ],
        ),
        migrations.AddField(
            model_name='templateversion',
            name='milestones',
            field=models.ManyToManyField(related_name='template_versions', through='Diary.TemplateMilestone', to='Diary.milestone'),
        ),
        migrations.AddConstraint(
            model_name='templatemilestone',
            constraint=models.UniqueConstraint(fields=('version', 'milestone'), name='diary_template_milestone_unique'),
        ),
        migrations.RunPython(declare_existing_milestones, migrations.RunPython.noop),
        migrations.RunSQL(GUARD_SQL, '''
            DROP TRIGGER diary_template_milestone_write_guard ON "Diary_templatemilestone";
            DROP FUNCTION diary_guard_template_milestone_write();
        '''),
    ]
