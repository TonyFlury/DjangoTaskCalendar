"""Rebuild version requirements from task rules, preserving all existing diaries."""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('Diary', '0010_optional_diary_template')]
    operations = [migrations.RunSQL('''
        ALTER TABLE "Diary_templatemilestone" DISABLE TRIGGER diary_template_milestone_write_guard;
        DELETE FROM "Diary_templatemilestone" d
        WHERE NOT EXISTS (SELECT 1 FROM "Diary_templateentry" e
                          WHERE e.version_id = d.version_id AND e.milestone_id = d.milestone_id);
        INSERT INTO "Diary_templatemilestone" (version_id, milestone_id)
        SELECT DISTINCT version_id, milestone_id FROM "Diary_templateentry"
        WHERE milestone_id IS NOT NULL
        ON CONFLICT (version_id, milestone_id) DO NOTHING;
        ALTER TABLE "Diary_templatemilestone" ENABLE TRIGGER diary_template_milestone_write_guard;
    ''', migrations.RunSQL.noop)]
