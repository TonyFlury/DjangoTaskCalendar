# Weekly and monthly task calendars

DFUT-018 provides List, Week and Month presentations of actual diary task dates.
The calendar is separate from the template relationship graph. It uses existing
task records, permissions, notes and completion operations; no migration is needed.

## Using the calendar

Use the presentation selector on the existing personal or manager diary page.
Choose **Day** for a dated, paginated agenda, **Week** for seven days, or **Month**
for complete calendar weeks around the selected month. **List** retains the
original diary task list and its normal all-dates scope. Filters are unchanged
when switching presentation; date navigation applies to Day/Week/Month. Previous/Next moves one period;
Today uses the Diary time zone; Go to date jumps to an ISO calendar date.

Personal mode shows tasks assigned to you or your groups across the host's
permitted open diaries. Whole-team tasks are optional. Manager mode requires one
selected permitted diary and shows all tasks visible there. Archived manager
diaries retain unfinished work and optional history. Existing write restrictions
on archived diaries still apply; notes retain their existing permission rules.

The same existing filters apply to every presentation. Personal pages retain
status, show-blocked, and whole-team choices; manager pages retain completion,
blocked, and late-only choices. Personal ready-only defaults are preserved across
all presentations. Changing the layout never silently changes a filter.

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

**Existing personal and manager diary views are the integration point.** Hosts
continue to subclass `PersonalDiaryView` and `ManagerDiaryView`, supply the same
trusted diary scope, and expose one URL per role. No calendar-specific URL,
`calendar_url` context value, presentation controller, or new permission hook is
required. The package resolves List/Day/Week/Month, renders its presentation
fragment, and retains the current `diary_base_template` wrapper.

For example, an existing host declaration remains sufficient:

```python
class HostPersonalDiary(YourExistingDiaryScope, PersonalDiaryView):
    pass

class HostManagerDiary(YourExistingDiaryScope, ManagerDiaryView):
    pass

urlpatterns = [
    path('diary/', HostPersonalDiary.as_view(), name='personal-diary'),
    path('diary/manager/', HostManagerDiary.as_view(), name='manager-diary'),
]
```

Here `YourExistingDiaryScope` is the host's existing access/context mixin, not
new calendar code. The host continues to own access, business context, and its
outer page. The package owns the current presentation and its controls.

### Presentation preference

An explicit `?view=list`, `?view=day`, `?view=week`, or `?view=month` wins.
After an authorised successful response, the selected value is saved in
`request.session['diary.presentation.v1']`. Omitting `view` reuses that preference.
List remains the initial default. Preferences are separated by user identity and
personal/manager role. Only the presentation name is stored: permitted diary
keys, task data, and filters are never taken from this preference. Scope and
membership are rechecked on every request. A login change cannot inherit another
user's preference. Without a session, explicit URL navigation still works.

### Host task selection and return navigation

The package honours existing `diary_ui.trusted_scope` and
`diary_ui.selection_url` conventions. Trusted-scope calendar controls omit diary
identifiers from query strings. Calendar cards submit through the existing
CSRF-protected POST task-selection form when the host supplies one. Hosts that
use ordinary links keep the existing `task_url()` / `task_detail_url_name` hooks.

A signed, user-bound `calendar_return` token restores period, presentation, and
filters after task actions. The shared `DiaryScopeMixin` carries a valid token
through successful local POST redirects, including existing host selection and
success hooks that return only a path. Tokens expire after seven days and grant
no diary access. Invalid, cross-user, expired or external destinations are ignored.
No host logic needs to interpret the selected calendar presentation.

### Templates, assets and compatibility routes

The package shares filters, toolbar, help and task actions across presentation
fragments: `calendar_day.html`, `calendar_week.html`, and `calendar_month.html`
under `Diary/partials/`. The original personal/manager templates remain the
List presentation. `calendar_template_name` can override the complete calendar
document if needed; `diary_base_template` remains the normal wrap-around hook.
The package's document loads `Diary/scripts/task_calendar.js` automatically.
An explicitly embedded calendar fragment needs that script once after its content.
The existing package-data patterns ship all assets; no external library is needed.

The earlier `TaskCalendarView`, `TaskCalendarDataView`, and package calendar/data
routes remain available for compatibility and specialist integrations. They are
not required to add presentation switching to an existing diary page. Their
standalone filters remain available independently of the original list forms.

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

Arguments include `view` (`list`, `day`, `week`, `month`), `anchor_date`, optional
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
The `panel` choices are `day`, `late`, and `undated`. Optional callable filters
`task_status` and `only_late` let the shared renderer honour the original personal
and manager filter forms. Range bounds are derived on
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

Server checks: `Diary.tests.test_task_calendar` and
`Diary.tests.test_diary_presentations`. Optional Chrome checks:
`Diary.tests.browser_task_calendar` and `Diary.tests.browser_diary_presentations`,
using the same isolated PostgreSQL test
database setup as the other browser checks. Coverage includes boundaries, leap/DST
dates, scoped identity, history, private tasks, earlier blockers, pagination,
query-count stability, signed returns, responsive layout and no-JavaScript use.

Manager multi-diary aggregation, milestone markers, time slots, recurring task
generation, dragging to reschedule, and automatic forward-impact changes remain
outside this feature. A calendar is a view of stored task dates, not a new scheduler.

## Diary Manager graph

Version 0.1.12.1 adds **Graph** to the same Manager URL and presentation preference.
It reuses the existing manager filters and host task navigation; no extra host
route is required. See [Manager graph](MANAGER_GRAPH.md) for usage and shared
list/calendar/graph state-colour CSS properties. Personal presentations are unchanged.
