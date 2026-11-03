# Diary UI mock-up

Open [index.html](index.html) in a browser.
No server or database is necessary.
The preview uses the packaged Diary stylesheet and a separate preview stylesheet.
Keep this directory inside the checkout so the relative paths remain valid.

The default page is **My tasks**.
It shows tasks owned by the selected person or by a role that includes that person.
It excludes whole-team tasks unless the user selects **Include whole-team tasks**.
The default status filter shows open tasks.
**Calendar** remains an explicit navigation choice for the full event list.
Changing the preview user or resetting the sample also opens **My tasks**.

The [dashboard mock-up](../dashboard/index.html) shows compact personal Late, Ready, and Blocked counts within the existing dashboard design.
It shares this preview's sample data.
Its links select the same user and the corresponding task filter.

## Main pages

The navigation opens these pages within one standalone browser document:

| Page | Purpose |
| --- | --- |
| Calendar | Inspect ready, blocked, late, and completed tasks. Search tasks and change the status filter. |
| My tasks | Inspect tasks for the selected person and their roles. Include whole-team tasks through an explicit option. |
| Task details | Inspect the date rule, owner, predecessors, and successors. Record sample completion when the task is ready. |
| Add or edit entry | Select a date rule and owner. Officers can also add an entry to the template draft. |
| Template | Inspect an approved version or change a draft. Select predecessors from a list that excludes circular choices. |
| Milestones | Set the dates used by the selected template. Open task due dates change with their source milestones. |

The preview date is 12 June 2027.
An incomplete task is late when its due date is today or earlier.
A blocked task can also be late.
The summary and status filters put that task in Late only.
Ready and Blocked counts exclude late tasks, so each open task contributes to one count.
The task details still show its predecessor state.

## Task highlights

Late tasks have a red shadowed border.
Blocked tasks have an amber shadowed border when a direct predecessor is late.
Red takes priority when the task itself is late.
Other Blocked tasks have a dashed border.
Completed tasks have no highlight.
Text labels identify the states without color alone.
The same rules apply to personal lists, the calendar, task details, entry edit forms, and dependency lists.
Template definitions have no instance dates and do not receive lateness highlights.

Open **Calendar** to inspect the sample highlights.
**Confirm sponsor list** is red because it is late.
**Prepare sponsor artwork** is amber because that late task blocks it.
**Approve sponsor artwork** has a dashed border because its direct predecessor is not late.
Complete **Confirm sponsor list** to remove its red highlight.
**Prepare sponsor artwork** then becomes Ready and loses its amber highlight.

Saved preview images:

- [Default personal view on desktop](previews/my-tasks-desktop.png).
- [Calendar on desktop](previews/calendar-desktop.png).
- [Template editor on desktop](previews/template-desktop.png).
- [Calendar on a phone](previews/calendar-mobile.png).

## Review paths

1. Open **Calendar**.
2. Open **Prepare sponsor artwork**.
3. Check that the task is blocked by **Confirm sponsor list**.
4. Open **Confirm sponsor list**.
5. Complete the task with an optional note.
6. Open **Prepare sponsor artwork** again.
7. Check that the task is now ready.

Use **Preview as** to select a different person.
Sam Patel can add a personal entry.
Jess Morgan sees tasks for the SponsorshipManager role as well as personal tasks.
Riley Evans can inspect the Officer pages.

Open **Template** and select **Confirm sponsor list**.
Its predecessor choices exclude itself and its direct and indirect successors.
Save a changed task name in the draft.
The current event keeps its original task name.

Select an approved version to inspect its read-only fields.
Create a draft before a change.
Approval in this preview does not change the existing event calendar.

## Limits and open design decisions

This is a UI proposal, not a routed Django interface.
It does not call `Diary.api`, modify PostgreSQL, or send emails.
Changes use browser session storage when available.
The preview uses memory if that storage is unavailable.
Use **Reset sample** to restore the original data.

The role selector is a demonstration control, not authentication.
Completion and event entry edit permissions are sample behavior for discussion.
They do not approve the production completion or edit policy.
The preview blocks completion when predecessors are incomplete.
It does not provide an Officer override or per-person confirmation of a role-owned task.

The template editor has a predecessor list and a read-only connection list.
It does not use a graphical connection editor.
It keeps selected predecessor checkboxes visible during a search.

A draft addition from an event entry requires its predecessors to exist in that template.
The preview rejects the combined addition if a predecessor exists only in the event calendar.
It does not remove a dependency silently.

Milestone names and the sample template are local preview data.
The configured application template and the database remain unchanged.

## Styling

The preview uses `../../static/Diary/styles/diary.css` followed by `preview.css`.
It then loads `task-states.css` for shared task highlights.
`sample-state.js` supplies the shared task data and date calculations for both previews.
The second file adds page layout and preview-specific components.
It does not replace the packaged stylesheet.
All visible content has named classes.
The preview classes use the `diary-preview-` prefix.
The [main styling guide](../../README.md#ui-mock-up-class-catalog) lists these classes.

## Browser checks

The preview was checked in Chrome at desktop and phone widths.
The checks cover navigation, role views, task completion, safe predecessors, template isolation, entry creation, milestone changes, and draft approval.
The browser reported no script errors in the checked paths.
