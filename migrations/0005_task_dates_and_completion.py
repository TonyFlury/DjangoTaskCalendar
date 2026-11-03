"""DV1-032, DV1-036, DV1-037, DV1-038: Store date overrides and completion audit data."""
from django.db import migrations, models


class Migration(migrations.Migration):
    """Add optional task date overrides, revision numbers, and completion audit fields."""

    dependencies = [('Diary', '0004_milestone_dates_without_diary_year')]

    operations = [
        migrations.AddField(model_name='calendarentry', name='due_date_override',
                            field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name='calendarentry', name='revision',
                            field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='calendarentry', name='completion_action',
                            field=models.CharField(blank=True, max_length=24)),
        migrations.AddField(model_name='calendarentry', name='completion_comment',
                            field=models.TextField(blank=True)),
        migrations.AddField(model_name='calendarentry', name='completion_target_key',
                            field=models.UUIDField(blank=True, null=True)),
    ]
