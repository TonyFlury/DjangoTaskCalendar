# Weekly and monthly task calendars

DFUT-018 provides List, Week and Month presentations of actual diary task dates.
The calendar is separate from the template relationship graph. It uses existing
task records, permissions, notes and completion operations; no migration is needed.

## Using the calendar

Choose **Week** for seven days, **Month** for complete calendar weeks around the
selected month, or **List** for the same period as a chronological agenda. Switch
views without losing the selected date and filters. Previous/Next moves one period;
Today uses the Diary time zone; Go to date jumps to an ISO calendar date.

Personal mode shows tasks assigned to you or your groups across the host's
permitted open diaries. Whole-team tasks are optional. Manager mode requires one
selected permitted diary and shows all tasks visible there. Archived manager
diaries retain unfinished work and optional history. Existing write restrictions
on archived diaries still apply; notes retain their existing permission rules.

Use the filter icon to find tasks, hide blocked tasks, show completed tasks,
include whole-team tasks, or select an owner in manager mode. Reset filters clears
these choices. Blocked tasks are shown initially in calendar views; this does not
change My Diary's existing ready-only list default.

Day cards show a bounded preview and the complete matching count. Select a date
or **+N more** to expand the day, with pagination for busy dates. Open task details
to add notes, complete tasks or perform another permitted action. **Back to
calendar** retains the selected period/day and filters, including after a write.
Closing the day panel returns to the same calendar with that day selected.

**Late outside this period** and **Date not set** open separate paginated panels.
A task displayed on a grid date is not repeated in the late panel. Due-today
tasks follow the existing `late` rule and display **Due today**. Completed tasks
appear on their recorded due date, not the timestamp of completion. Annual rules
do not generate additional yearly occurrences. Task-relative snapshots never move
merely because their source task is late.

At narrow widths, the calendar becomes a chronological agenda. Keyboard users can
reach the same day links, task links, filters and help; dialogs support Escape.
Without JavaScript, filters/help remain inline and expanded days use page sections.

## Host integration

The package routes are `Diary:task-calendar`, `Diary:data-calendar`, and
`Diary:diary-task-calendar` (the last includes a diary UUID in its path).
As with existing task views, these routes grant no diary access by themselves.
Hosts must supply trusted permitted keys via `get_diary_keys()`, the
`permitted_diary_keys` view attribute, or trusted view context.

Use the same host scope mixin as the existing list and task-detail views:

```python
from django.urls import path, reverse_lazy
from Diary.calendar_views import TaskCalendarView, TaskCalendarDataView
from Diary.views import PersonalDiaryView, TaskDetailView

# YourExistingDiaryScope is your host's current get_diary_keys() policy mixin.
class HostCalendar(YourExistingDiaryScope, TaskCalendarView):
    extra_context = {'task_detail_url_name': 'host-calendar-task'}

class HostCalendarData(YourExistingDiaryScope, TaskCalendarDataView):
    pass

class HostCalendarTask(YourExistingDiaryScope, TaskDetailView):
    pass

class HostPersonalDiary(YourExistingDiaryScope, PersonalDiaryView):
    extra_context = {'calendar_url': reverse_lazy('host-calendar')}

urlpatterns = [
    path('tasks/calendar/', HostCalendar.as_view(), name='host-calendar'),
    path('tasks/calendar/data/', HostCalendarData.as_view(), name='host-calendar-data'),
    path('tasks/detail/<uuid:entry_key>/', HostCalendarTask.as_view(), name='host-calendar-task'),
]
```

The task detail route name in this example accepts `entry_key`; the calendar adds
the matching `diary_key` as a query parameter. Override `task_url()` for a different
host route shape. A `calendar_url` context value adds Week/Month links to existing
personal and manager lists. Preserve any other host context values when adding it.
Set `calendar_mode = 'manager'` on a calendar subclass to lock it to manager mode.
That mode still requires a selected, authorised diary; it does not expand scope.

The normal `diary_base_template` context hook is supported. The content fragment
is `Diary/partials/task_calendar.html`; it needs the context from `TaskCalendarView`.
Include `Diary/scripts/task_calendar.js` once for dialog enhancement. Templates,
CSS and JS are shipped through the existing package-data patterns. No external
calendar dependency, CDN, or frontend build step is required.

Calendar links carry a signed, user-bound `calendar_return` token. It stores
validated navigation state, grants no permissions, and expires after seven days.
Task forms carry it across permitted writes. Without a custom success destination,
calendar-originated writes stay on the authorised task route. Hosts that replace
`get_success_url()` or the complete response flow should preserve this token or
provide their own return navigation. Invalid, expired, cross-user and external
return destinations are ignored.

## Callable and JSON interfaces

```python
from datetime import date
from Diary.api import DiaryAPI

period = DiaryAPI(actor=actor).task_period(
    view='month', anchor_date=date(2027, 6, 20),
    mode='personal', include_completed=False, show_blocked=True,
    include_whole_team=False, query='',
)
```

Arguments include `view` (`list`, `week`, `month`), `anchor_date`, optional
`diary_key`, `mode`, the filters above, `selected_day`, and separate positive
`page`, `late_page`, `undated_page` values. `period` retains the selected `week`
or `month` interval in List view. `today` is an optional date for deterministic
callers/tests. Dates passed to the callable API are `datetime.date`, not datetimes.
Manager calls may pass `directory` for person-owner eligibility, just as existing
ownership review operations do; the web view supplies a Django owner directory.
Manager `owner` values are `person:<person_ref>`, `role:<role_name>`, or `team`.

The result includes date-only half-open displayed bounds `[start, end)`, primary
period bounds, local Today/time-zone/weekday metadata, previous/next anchors,
selected diary metadata, bounded day previews with complete counts, selected-day
pagination, attention-panel pagination, and visible manager owner choices.
Every task carries `(diary_key, entry_key)`; repeated template keys in different
diaries remain distinct. Permissions and private predecessor masking run before
public counts and previews. Readiness considers predecessors outside the period.

JSON views use the same selection and return `{'data': ...}` with UUID/date
serialization and private/no-store headers. Invalid selectors/filters return 400,
unavailable records 404, and unauthorised access 403. Query values never grant scope.
HTTP options use `view`, `period`, `date`, `day`, `mode`, `query`, `owner`,
`include_completed`, `hide_blocked`, `include_whole_team`, `page`, `late_page`,
`undated_page`, `panel`, and optional `diary_key`. Flags use `1`; omit for false.
The `panel` choices are `day`, `late`, and `undated`. Range bounds are derived on
the server, not accepted as an arbitrary unbounded date interval.

## Settings and styles

| Setting | Default | Allowed values |
| --- | --- | --- |
| `DIARY_WEEK_START` | `0` (Monday) | Integer 0–6; 6 is Sunday. |
| `DIARY_CALENDAR_WEEK_PREVIEW` | `5` | Integer 1–50. |
| `DIARY_CALENDAR_MONTH_PREVIEW` | `3` | Integer 1–50. |
| `DIARY_CALENDAR_PAGE_SIZE` | `25` | Integer 1–100. |

`DIARY_TIME_ZONE`, otherwise Django's `TIME_ZONE`, determines Today. Date-only
boundaries are not converted through UTC midnight; DST does not change week length.

Stable classes include `diary-task-calendar`, `diary-calendar-toolbar`,
`diary-calendar-grid`, `diary-calendar-day`, `diary-calendar-task`,
`diary-calendar-day-panel`, and `diary-calendar-dialog`. Existing Diary palette
variables apply. Hosts can override `--diary-calendar-gap`,
`--diary-calendar-day-height`, and `--diary-calendar-name-lines`; preview counts
come from the settings above, not CSS. Filters and Help reuse the navigator's
toolbar icon/label/tooltip properties. For example:

```css
.diary.diary-task-calendar { width: 95%; max-width: none; }
.diary .diary-calendar-filters-open {
    --diary-toolbar-icon: url('../images/filters.svg');
    --diary-toolbar-tooltip: "Choose calendar tasks";
}
```

## Verification and limits

Server checks: `Diary.tests.test_task_calendar`. Optional Chrome checks:
`Diary.tests.browser_task_calendar`, using the same isolated PostgreSQL test
database setup as the other browser checks. Coverage includes boundaries, leap/DST
dates, scoped identity, history, private tasks, earlier blockers, pagination,
query-count stability, signed returns, responsive layout and no-JavaScript use.

Manager multi-diary aggregation, milestone markers, time slots, recurring task
generation, dragging to reschedule, and automatic forward-impact changes remain
outside this feature. A calendar is a view of stored task dates, not a new scheduler.
