# Diary web user guide

This guide explains the Diary web pages for people who do tasks and managers who organize them.
It describes the current pages and their limits.

Your site administrator supplies the Diary links and controls which diaries you can use.
Menu names can differ between websites.
Some pages can be unavailable on your site.

## Find an instruction

- [Start using Diary](#start-using-diary).
- [Understand tasks and permissions](#understand-tasks-and-permissions).
- [Find your tasks](#find-your-tasks).
- [Add a personal task](#add-a-personal-task).
- [Select a date rule](#select-a-date-rule).
- [Change a due date](#change-a-due-date).
- [Add task notes](#add-task-notes).
- [Complete a task](#complete-a-task).
- [Use the manager diary](#use-the-manager-diary).
- [Apply a template to a diary](#apply-a-template-to-a-diary).
- [Assign a task](#assign-a-task).
- [Add a new task to a template](#add-a-new-task-to-a-template).
- [Create or change a template](#create-or-change-a-template).
- [Use Close all](#use-close-all).
- [Get help](#get-help).
- [Understand the current limits](#understand-the-current-limits).

## Start using Diary

1. Sign in to your website.
2. Open the Diary link supplied by your site administrator.
3. Examine the diary name when the page identifies one selected diary.
4. Select **View and update task** beside a task you want to open.

**My Diary** shows your tasks from one selected diary or several diaries you can use.
Opening a page does not create a diary.
Your site controls when diaries become available.

A diary can start empty. You can select **Add task** and create your own private
tasks without waiting for a manager to choose a template. In this diary, use a
one-time date or an annual date. Once it has a task with a due date, you can also
base another task's date on that task. Milestone date choices become available after a
template and its milestone dates have been supplied.

An empty task list is an ordinary starting point. You do not need to create or
understand a template to use your diary. If a manager later applies a template,
your existing personal tasks keep their names, ownership, dates, privacy, and
completion history. New template tasks appear alongside them according to their
normal visibility and assignment rules.

## Understand tasks and permissions

| Term | Meaning |
| --- | --- |
| Diary | A named collection of tasks. |
| Task | One item of work with an owner and an optional due date. |
| Owner | The person, group, or whole team responsible for a task. |
| Template | A reusable set of tasks that can be applied when a diary starts or later. |
| Template task | A task that a diary received from its template. |
| Diary addition | A task added directly to one existing diary. |
| Personal addition | A diary addition that belongs to one person. |
| Milestone | A named date, such as an event date, used to calculate task dates. |
| Predecessor | A task that must finish before another task can complete. |
| Successor | A task that depends on another task. |
| Ready | An incomplete task with no open predecessors. |
| Blocked | An incomplete task with at least one open predecessor. |
| Late | An incomplete task due today or earlier, using the time zone set for Diary. |

A task can be both **Blocked** and **Late**.
A task without a due date is not late.

A DiaryUser has ordinary Diary access.
A DiaryManager also has assignment and template permissions.
Your website can use different names for these roles.

| Action | DiaryUser | DiaryManager |
| --- | --- | --- |
| Add a personal task | For yourself only. | For yourself or another eligible person. |
| Assign a group or Whole team | Not permitted. | Permitted. |
| Change a personal addition's due date | Only when you own it. | Permitted within your diary access. |
| Change a template task's due date | Not permitted, even when you own it. | Permitted within your diary access. |
| Change a group or Whole team task's due date | Not permitted. | Permitted within your diary access. |
| Complete an accessible task | Permitted when no predecessors remain open. | Permitted when no predecessors remain open. |
| Use Close all | Not permitted. | Permitted for an open blocking chain. |
| Add a note | Tasks assigned to you, your ownership groups, or the whole team. | Any task within permitted diary access. |
| Create or change templates | Not permitted. | Permitted. |

These actions require an open diary and an incomplete task where applicable.
Notes can also be added after task completion or diary closure.
Managers cannot use diaries outside their permitted access.

Personal additions are private to their owner and permitted managers.
This rule includes personal additions that a manager assigns to another person.
Template tasks do not have the same privacy rule.
A person owner does not make a template task a private note.

Group tasks show current group members.
A group task has one shared completion record.
Completion by one permitted person completes that task for the group.
Whole-team tasks also have one shared completion record.

## Find your tasks

**My Diary** shows tasks assigned to you or your current groups.
Managers also see only their own assignments on this page.
Managers use the [manager diary](#use-the-manager-diary) for the broader task list.

The initial list shows ready tasks, including ready tasks marked **Late**.
It excludes completed tasks and tasks from closed diaries.
Whole-team tasks are initially excluded.

### Change the list

1. Select **show blocked also** to include blocked tasks assigned to you or your groups.
2. Select **include whole-team tasks** when you also want whole-team work.
3. Select **Apply filters**.

The first checkbox does not reveal another person's private addition.
A predecessor owned by another person or group can still block your task.

The **Late**, **Ready**, and **Blocked** count links select separate task categories.
The **Task status** control provides the same categories.

| Selection | Tasks shown |
| --- | --- |
| All open tasks | Ready tasks, plus blocked tasks when **show blocked also** is selected. |
| Late only | Tasks due today or earlier, including blocked tasks. |
| Ready and not late | Ready tasks whose dates are not late, including tasks without a date. |
| Blocked and not late | Blocked tasks whose dates are not late. |

A specific status selection takes priority over **show blocked also**.
Thus, **Late only** can show a blocked task while that checkbox is clear.
Each task contributes to only one count, with **Late** taking priority.
The counts include whole-team tasks only when you select their checkbox.

Select **Reset filters** to restore the initial choices.
A selected diary stays selected.

### Read the task marks

| Appearance | Meaning |
| --- | --- |
| Red border and shadow | The task itself is late. |
| Amber border and shadow | The task is blocked by a late direct predecessor, but is not itself late. |
| Dashed border | The task is blocked without a late direct predecessor. |
| Ready or Blocked text | The task's current predecessor state. |
| Date not set | The task has no due date. |

The red border takes priority over the amber border.
The text labels also identify task states.

## Add a personal task

1. Select **Add task**.
2. Select a diary if the page requests a diary selection.
3. Examine the **Diary:** name.
4. Enter **Task name**.
5. Enter **Description** if necessary.
6. Select **Date rule**.
7. Complete the fields for that rule.
8. Select **Add task** to save.

The page shows **Task added.** after a successful save.
Ordinary users receive a personal addition owned by themselves.
They cannot select another owner or add the task to a template.

A task name must be unique within its diary.
Differences in capital letters do not make two task names different.

## Select a date rule

The task creation form provides these rules.
Only the fields for the selected rule are necessary.

| Date rule | Fields to complete | Result |
| --- | --- | --- |
| One-time date | **One-time date**. | One exact due date for this diary task. |
| Milestone date | **Milestone**. | The same date as the selected milestone. |
| Days from a milestone | **Milestone** and **Day offset**. | A calculated date before or after the milestone. |
| Annual date | **Month**, **Day of month**, and **Year offset** when necessary. | One date calculated from the diary's creation date. |
| Days from another task | **Source task** and **Day offset**. | A date calculated once from another task's due date. |

A negative **Day offset** means days before the milestone.
A positive value means days after it.
Zero means the milestone date itself.
For example, minus seven means seven days before the milestone.

The task creation form offers milestones available in the selected diary.
Your website supplies their dates when it creates the diary.
New diaries require dates for every milestone used by their template tasks.
Older diaries may still have missing dates; ask your site administrator for help.

### Dates from another task

Select **Days from another task**, choose a **Source task**, and enter the signed
**Day offset**. Zero uses the same date; positive values mean after it, and negative
values mean before it. The source cannot be the task itself.

In a template, Diary resolves chains when creating a diary or first applying its
template. For example, a source due on 10 June, a review three days later, and a
submission two days after the review become 10, 13, and 15 June. Templates can
refer to other unsaved task rows; save rejects missing sources and circular date
references. A source must have a calculable date when the diary is initialized.

When adding a task to an existing diary, the choices include visible tasks with
due dates. The new task's date is fixed when added. If you also add the task to a
template, select its **Future source task** and **Future day offset** separately.

These dates do not move if the source finishes late or its due date is edited.
An explicit permitted edit to this task's date changes this task only. Task details
retain the original calculated date. Tracking downstream impacts is future work.

A date source is separate from a completion predecessor. Select **Predecessors**
as well if the task must wait for another task to finish. The template's task graph
shows completion dependencies and direct milestone date relations. Task-to-task
date references are configured in the forms and are not drawn as completion arrows.

### Annual dates

An annual rule initially selects the next matching date after the diary's creation date.
A matching date on the creation day selects the following year.
February 29 selects the next valid leap day.

**Year offset** changes the selected year.
Zero keeps the initial selection.
A changed year can make February 29 unavailable.
Diary then shows **Date not set**.

An annual rule creates one task occurrence in each diary.
It does not create another task each year.
Adding an annual task to an older diary can produce a date that is already past.

## Change a due date

1. Open **View and update task** for the task.
2. Examine the diary name and task name.
3. Enter the new **Due date**.
4. Select **Save due date**.

The form is available for your own personal additions.
This includes a personal addition assigned to you by a manager.
It is unavailable for template tasks when you are an ordinary user.

Managers can also change dates on template tasks and other tasks within their diary access.
Completed tasks and closed diaries reject date changes.

The change affects only the selected diary task.
Its original date rule stays unchanged.
Its source template, other tasks, and other diaries stay unchanged.
The next task-list display uses the changed date.

**V1 does not warn managers when a due-date change causes a conflict.**
Diary does not automatically compare the new date with related task dates to detect scheduling conflicts.
It does not change related task dates automatically.

Examine predecessor and successor dates before changing a template task's due date.
Late and Blocked marks do not provide a scheduling-conflict warning.

## Add task notes

Open a task and find **Notes**. Enter your text and select **Add note**.
Notes are optional; you do not need one to progress or complete a task.
Each save adds a separate entry with its author and save time. Earlier notes stay
in the history and cannot be edited or removed. Add a correction as another note.

You may add notes to tasks assigned to you, to your current ownership groups, or
to the whole team. Diary Managers may add notes to any task within their permitted
diary access. Notes remain available on completed tasks and closed diaries.
Adding a note does not change dates, task status, or dependencies.

Anyone permitted to view the task can read its notes. Personal task privacy also
applies to its notes. Authors appear as First Name Last Name, with **deleted user**
when a user or their display name cannot be resolved; email addresses are not used
as fallback names. Save times use the page's configured display time zone.

## Complete a task

Completion permission is separate from date-edit permission.
You can complete an accessible template task even when you cannot edit its due date.
A due date is not required for completion.

1. Open **View and update task**.
2. Examine **Open predecessors**.
3. Select **Complete** when no predecessors remain open.

The list includes open direct and indirect predecessors.
For example, your task can depend on a review that itself depends on preparation.
Both open predecessor tasks can appear in the list.

A private predecessor can prevent completion without revealing its details.
The page then shows **One or more private predecessors remain open.**
A manager can help with that blocking work.

Diary checks the predecessors again before saving completion.
A blocked task cannot complete through **Complete**.

The task then leaves your open-task list.
Its details show **Completed**, the completing person, completion time, and due date at completion.
The completion date record keeps any due-date change made before completion.
A task completed without a due date keeps **Date not set** in that record.

A completed task cannot be edited or reopened through these pages.
Repeating completion does not replace the first completion record.

## Use the manager diary

The following sections require DiaryManager access.

1. Open the manager diary link for a diary you can use.
2. Examine the diary name above the task list.
3. Select the required checkboxes.
4. Select **Apply filters**.

Initially, the list includes all incomplete tasks, including blocked tasks and tasks that are not late.
It also includes personal additions that you can manage.

| Checkbox | Effect |
| --- | --- |
| include completed tasks | Add completed tasks and their completion records. |
| exclude blocked tasks | Hide blocked incomplete tasks. |
| exclude non-late tasks | Keep only incomplete tasks due today or earlier. |

The selected checkboxes apply together.
Completed tasks are never late or blocked.
Thus, **exclude non-late tasks** hides completed tasks even when **include completed tasks** is selected.

Select **Reset filters** to clear these choices.
The same diary stays selected.

## Apply a template to a diary

This action requires DiaryManager access and a diary you are permitted to manage.
An open diary can receive one approved template, including after users have added
private tasks. Your site administrator supplies the manager page and application
route. There is no separate approval step for applying an already approved version.

1. Open the manager diary and check the diary name.
2. Select **Apply template**. This link is available when no template has been applied.
3. Select the required **Template version** and select **Choose template**.
4. Enter a date for every displayed milestone. Only milestones used by template tasks are requested.
5. Select **Apply template** to save.

The diary keeps its name and identity. Its existing tasks and completion records
remain unchanged. Personal additions remain private to their owner and permitted
managers. The copied template tasks retain their predecessor links and ownership.
If a copied task would duplicate an existing task name, the copy receives a suffix
such as **(template)** or **(template 2)**. Existing task names stay unchanged.

An annual template date is calculated from the diary's original creation date,
using the existing annual-date rules. Inspect the dates when applying a template
to an older diary; some calculated dates can already be past.

Applying a template is one complete save: if any date or task fails validation,
none of its tasks, links, or dates are added. Repeating the same save does not add
duplicate tasks. A closed diary cannot receive a template. An applied template
cannot be removed, replaced, or applied a second time with different dates.
Future template edits continue to affect future diary applications only.

The **Add to template for future diaries** option on the task creation page is
available after a template has been applied. Managers can still add and assign
diary-only tasks before that point.

## Assign a task

1. Select **Add task** from a permitted diary.
2. Complete the task name, description, and date rule.
3. Select **Owner type**.
4. Complete **Person** or **Ownership group** when required.
5. Select **Add task**.

| Owner type | Selection |
| --- | --- |
| Person | Select an eligible person in **Person**. |
| Role | Select an available group in **Ownership group**. |
| Whole team | No person or group selection is required. |

The form initially selects you as the person owner.
A person or group absent from the choices cannot receive the task through this form.
Your site administrator controls available people and groups.

## Add a new task to a template

This action adds one new diary task and a reusable task for future diaries.
It does not copy an existing template task into an existing diary.

1. Open **Add task** in the intended diary.
2. Examine the template name, version, and status under **Template for future diaries**.
3. Open **Review template** in another browser tab to examine the current template tasks.
4. Complete the diary task and owner fields.
5. Select **Add to template for future diaries**.
6. Select **Future date rule**.
7. Complete the fields for that future rule.
8. Select **Add task**.

Opening **Review template** in the same tab does not save your task form.
The template checkbox is clear initially.
It must stay clear when the task belongs only in this diary.

The future rule can use a milestone, days from a milestone, or an annual date.
The future task uses the same name, description, and owner as the diary task.
The diary task can use a different exact date.
An exact date never becomes an annual template date automatically.

The save creates one diary task and approves a new template version together.
The new version includes the current highest version's tasks, including a draft when present.
Other existing diaries keep their tasks.
New diaries can use the approved version selected by your website.

A failed combined save adds neither item.
A repeated combined request does not create another task or template version.
A template change by another manager requires a new form.

## Create or change a template

A template defines reusable tasks for future diaries.
Changing it does not replace tasks in existing diaries.
Saving approves a new version immediately.
There is no separate approval step.

### Create a template

1. Open the template page supplied by your site administrator.
2. Select **Create template**.
3. Enter **Template name**.
4. Enter **Description** if necessary.
5. Select **Add task** to add a task row.
6. Complete the task fields in that row.
7. Add more task rows as required.
8. Select **Save template**.

In this editor, **Add task** adds a form row without saving the template.
**Save template** saves the complete set of task rows.
The template name stays fixed after creation.

### Change an existing template

1. Open the template page.
2. Select the template name.
3. Examine the version number and status.
4. Change the required task rows.
5. Select **Save template**.

The editor opens the highest version, including a draft when present.
The save creates and approves another version.
Older versions and existing diary tasks stay unchanged.

**Remove task** removes a row from the proposed new version.
When that button is unavailable, the row can provide a **Delete** checkbox.
The removal does not delete the task from an existing diary.

### View task connections

Diary Managers can see **Task connections** above the task forms in the template
editor. Each box is a task. A diamond represents a host milestone used by at least
one task's **Milestone date** or **Days from a milestone** rule. Shared milestones
appear once; unused milestones stay out of the graph.

Solid arrows point from a completion prerequisite to the task that depends on it.
Dashed arrows connect milestones to tasks whose dates use them. Hover a dashed
arrow to see whether the task uses the same date or an offset before or after it.
Milestone date relations do not block task completion. Milestones are read-only
and show their full labels and stable names on hover or through their accessible
labels. Tasks without connections are included. The graph arranges tasks
automatically and shows the current form contents, including unsaved changes.
Connected groups are laid out separately. Within a group, task order is adjusted
to reduce crossing arrows, and longer connections use lanes around intervening
task boxes. Some dependency patterns still require crossings; the layout does
not change your task order in the forms or the saved dependencies.

- Select a box to move to that task's name field for editing.
- Use **+** and **−** to zoom, or **Fit to screen** to show the whole graph.
- Scroll inside the graph, or drag its background with a mouse, to move around.
- Use Tab to reach a task and Enter to edit it. With the graph background focused,
  use **+**, **−**, or **Home** to zoom or fit; arrow keys scroll.

Names, added tasks, removed or restored tasks, and predecessor selections update
the preview. Changing milestone rules or offsets also updates the diamonds and
date arrows. Removing the last reference removes its milestone from the preview.
Unnamed tasks receive temporary labels. A preview does not save
anything: select **Save template** to create the new version. Removing a task also
removes its connections from the proposed version.

Use the existing task forms to change task content and predecessors. Connections
cannot be dragged or edited on the graph. The forms remain available with
JavaScript disabled, and show full names and predecessor selections when the graph
is too large to read at fit size. Existing diary copies are unaffected by this preview.

### Template dates and predecessors

Template tasks use reusable date rules.
They do not use one-time dates.
The [date-rule explanation](#select-a-date-rule) also applies to their milestone and annual fields.

In each task, select **Milestone** from the catalogue made available by your website.
There is no separate milestone declaration step. Required dates are determined
from the tasks you save, including when JavaScript is disabled.
You cannot type a new milestone identifier or change its label in a task row.
Ask your site administrator if the required milestone is unavailable.
Changing or removing tasks automatically changes the new version's requirements.
Saving changes creates a new version; previous versions and diaries keep their requirements.

**Predecessors** identifies tasks that must finish first.
A predecessor must belong to the same template version.
The choices exclude the task itself and tasks that would create a circular dependency.
A circular dependency would make tasks require each other to finish first.

Select the required tasks in **Predecessors**.
Hold Ctrl or Command to select several tasks when your browser requires it.
Choices are grouped by connected subgraph, with prerequisites before dependent
tasks. **Source task** and **Future source task** use date-source order, with the
completion subgraphs as the tie order when no date reference determines the order.
Unrelated tasks retain their existing relative order. These lists are no longer
sorted globally by task name. Unsaved changes update the lists without clearing
your selections; the same ordering is used when JavaScript is disabled.

Enter a task name in **Find predecessors** when that control is available.
The editor can show a warning when an ownership group has no members.
A later membership change does not produce continuous automatic warnings.

A template change does not change predecessor links in existing diaries.
The task detail page has no predecessor editor.
V1 does not permit dependency changes in any existing diary, including manager changes.
You cannot add, remove, or replace its predecessor links.
Creating another template version does not change those links.

## Use Close all

**Close all** is available to managers when the selected task has open predecessors.
It completes those open predecessors and the selected task together.
It includes open indirect predecessors.

1. Open **View and update task** for the intended task.
2. Examine its diary name and task name.
3. Examine **Open predecessors**.
4. Select **Close all** only when forced completion of the chain is appropriate.

The action records you as the completing person for each newly completed task.
Each forced predecessor receives a comment identifying **Close all** and the selected task.
Earlier completion records and all predecessor links stay unchanged.

A changed predecessor state or due date requires another inspection before the save can succeed.
If saving any task fails, none of these completion changes remain.

**Close all** does not close the diary.
**Complete** also does not close the diary.
Your site controls when the diary itself closes.

## Assign an orphaned template task

An orphaned task is an open template task without an eligible person or ownership group member.
Diary additions do not qualify as orphaned tasks.
The full manager diary list places orphaned tasks first.
The selected list filters still apply.
You can leave an orphaned task unresolved. Tasks that depend on it remain blocked while it stays incomplete.

1. Select **View and update task** for the orphaned task.
2. Select **New owner type**.
3. Select **New person** for person ownership.
4. Select **New ownership group** for group ownership.
5. Select **Assign owner**.

Person choices contain active members of the configured DiaryUser group.
Group choices contain authorized ownership groups. The selected group needs an eligible active member.
Select **Whole team** to give the task to the team.
The change affects this diary only. It preserves dates and predecessor links.
The task stays incomplete until someone completes it.

## Get help

| Situation | What it means | Action |
| --- | --- | --- |
| No tasks match these filters. | Your current selection has no matching tasks. | Select **Reset filters**. |
| Blocked tasks seem absent. | My Diary hides blocked tasks initially. | Select **show blocked also**. Select **Apply filters**. |
| A task has Date not set. | Its date rule has no available date. | Ask a manager to examine its date rule and milestone date. |
| Save due date is absent. | The task is complete, the diary is closed, or your role cannot edit this task's date. | Ask a manager if the date needs correction. |
| A private predecessor remains open. | Inaccessible work blocks the selected task. | Ask a manager for help. |
| The task or predecessor chain changed. | The page contains an older task state. | Select **Reload task**. Examine the current state. |
| A template changed during saving. | Another save changed its version. | Open the template or task creation form again. |
| A person or group is unavailable. | The current assignment choices do not include that owner. | Ask your site administrator for help. |
| A selected task is unavailable. | The task does not exist or you cannot access it. | Use a current task-list link. |
| A diary is closed. | Its records remain available; assigned users and managers can still add notes. | Ask your site administrator which diary to use. |
| Diary access is denied. | Your account or selected diary lacks the necessary access. | Ask your site administrator to examine your access. |

An empty list can also mean that no matching work is assigned to you.

Some errors concern access rather than a task's contents.
An unavailable task message does not prove that a task exists.

## Understand the current limits

The current web pages have these limits:

- Personal due-date edits apply only to your own diary additions.
- Managers receive no automatic warning when a due-date change causes a scheduling conflict.
- Completed tasks cannot be reopened or edited.
- A group or whole-team task has one shared completion record.
- Task details provide no controls to change task names, descriptions, or owners.
- Predecessor links are copied when a template is first applied and then frozen. Managers cannot edit those links.
- Task details provide no task deletion control.
- Milestone date editing is unavailable in these pages.
- Creating or closing a diary depends on your website's separate process.
- A template can be applied once to an open diary without a template. Additional copying or replacement in an already templated diary is unavailable.
- **My Diary** lists assigned tasks. The full diary list is a manager page.
- Reminders, exports, a calendar month view, and future date-window filters are unavailable.

Annual-date selection has a further limit for diaries that last more than 12 months.
The selected occurrence can be too early for the intended task.
An appropriate **Year offset** can select a later year.
Diary does not calculate that choice from the diary's duration.

The website's dashboard can differ from the Diary pages described here.
A demonstration page does not establish that a function is available on your site.

Controlled editing of existing diary dependencies is a backlog proposal for a later release.
It has no assigned release number.

For website setup, see the separate [integration and API guide](README.md).
