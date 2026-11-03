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
- [Complete a task](#complete-a-task).
- [Use the manager diary](#use-the-manager-diary).
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

## Understand tasks and permissions

| Term | Meaning |
| --- | --- |
| Diary | A named collection of tasks. |
| Task | One item of work with an owner and an optional due date. |
| Owner | The person, group, or whole team responsible for a task. |
| Template | A reusable set of tasks for new diaries. |
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
| Create or change templates | Not permitted. | Permitted. |

These actions require an open diary and an incomplete task where applicable.
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
| Milestone date | **Milestone name**. | The same date as the selected milestone. |
| Days from a milestone | **Milestone name** and **Day offset**. | A calculated date before or after the milestone. |
| Annual date | **Month**, **Day of month**, and **Year offset** when necessary. | One date calculated from the diary's creation date. |

A negative **Day offset** means days before the milestone.
A positive value means days after it.
Zero means the milestone date itself.
For example, minus seven means seven days before the milestone.

The task creation form uses existing milestones.
A missing milestone date can leave the task marked **Date not set**.
A manager can define a new milestone name in the template editor.
That does not set the milestone date in an existing diary.

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

### Template dates and predecessors

Template tasks use reusable date rules.
They do not use one-time dates.
The [date-rule explanation](#select-a-date-rule) also applies to their milestone and annual fields.

**Milestone name** can select an existing milestone or define a new name.
**New milestone label** gives a readable label for a new name.
A milestone name uses letters, digits, underscores, or hyphens, without spaces.
Existing milestone labels stay unchanged.

**Predecessors** identifies tasks that must finish first.
A predecessor must belong to the same template version.
The choices exclude the task itself and tasks that would create a circular dependency.
A circular dependency would make tasks require each other to finish first.

Select the required tasks in **Predecessors**.
Hold Ctrl or Command to select several tasks when your browser requires it.

Enter a task name in **Find predecessors** when that control is available.
The editor can show a warning when an ownership group has no members.
A later membership change does not produce continuous automatic warnings.

A template change does not change predecessor links in existing diaries.
The task detail page has no predecessor editor.

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
| A diary is closed. | Its records remain available, but task changes are unavailable. | Ask your site administrator which diary to use. |
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
- Task details provide no controls to change task names, descriptions, owners, or predecessor links.
- Task details provide no task deletion control.
- Milestone date editing is unavailable in these pages.
- Creating or closing a diary depends on your website's separate process.
- Copying an existing template task into an existing diary is unavailable in these pages.
- **My Diary** lists assigned tasks. The full diary list is a manager page.
- Reminders, exports, a calendar month view, and future date-window filters are unavailable.

Annual-date selection has a further limit for diaries that last more than 12 months.
The selected occurrence can be too early for the intended task.
An appropriate **Year offset** can select a later year.
Diary does not calculate that choice from the diary's duration.

The website's dashboard can differ from the Diary pages described here.
A demonstration page does not establish that a function is available on your site.

For website setup, see the separate [integration and API guide](README.md).
