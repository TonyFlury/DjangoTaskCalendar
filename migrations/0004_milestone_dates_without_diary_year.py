"""Remove the diary year and preserve existing annual task dates. DV1-051."""
from datetime import date

from django.db import migrations, models


def preserve_annual_dates(apps, schema_editor):
    """Save each existing annual date before removing its diary year.
    Keep invalid leap-day occurrences unset and preserve completion records.
    """
    entries = apps.get_model('Diary', 'CalendarEntry').objects.using(schema_editor.connection.alias)
    for entry in entries.filter(date_kind='annual').select_related('calendar').iterator():
        try:
            due = date(entry.calendar.event_year + entry.year_offset, entry.month, entry.day)
        except (ValueError, TypeError, OverflowError):

            # Existing invalid dates must remain unset after the migration.
            due = None
        entries.filter(pk=entry.pk).update(annual_due_date=due)


class Migration(migrations.Migration):
    """Preserve annual dates and remove the required diary year in one transaction."""

    dependencies = [('Diary', '0003_calendar_closure')]

    operations = [
        migrations.AddField(
            model_name='calendarentry', name='annual_due_date',
            field=models.DateField(blank=True, null=True, editable=False),
        ),
        migrations.RunPython(preserve_annual_dates),
        migrations.AlterModelOptions(name='eventcalendar', options={'ordering': ('name',)}),
        migrations.RemoveConstraint(model_name='eventcalendar', name='diary_calendar_year_valid'),
        migrations.RemoveField(model_name='eventcalendar', name='event_year'),
    ]
