# Diary V1 partial implementation design

Reviewed: 3 November 2026.

This document describes the remaining work for partially implemented items in [the V1 checklist](../../Diary/TODO_V1.md).
The existing [Diary design](event-calendar.md) defines the approved requirements.
DV1-052 below records an additional confirmed V1 requirement.
DFUT-003 below records a deferred requirement with no assigned release.
Completed sections record their implementation evidence and link to the updated checklist.

Statements under **Current implementation** describe existing code.
Statements under **Remaining requirements** restate approved requirements.
Statements under **Proposed implementation** describe work that has not been implemented or approved as a specific interface.
Open decisions remain separate from approved requirements.

## Confirmed scope: DV1-034 and DEC-003

The user confirmed that copying existing template tasks into existing diaries is not required.
DV1-034 remains in the checklist as a removed requirement, without a future release assignment.
DEC-003 is closed because its missing-input questions applied only to that copying operation.
No implementation or verification remains for the removed feature.

DV1-033 remains implemented.
A manager can create a new diary task and optionally add it to a template for future diaries.
That operation does not copy an existing template task into a live diary or change other existing diaries.
The template editor continues to save versions for future diary creation.

## Technical names

| Technical name | Meaning |
| --- | --- |
| `Actor` | Existing callable API data class with caller identity, group names, and permitted diary keys. |
| `OwnerDirectory` | Existing callable API protocol for person eligibility checks. |
| `DjangoOwnerDirectory` | Existing template workflow adapter for Django user references. |
| `DIARY_MANAGER` | Existing setting that names the DiaryManager group. |
| `DIARY_USER` | Existing setting that names the DiaryUser group. |
| `DIARY_TASK_OWNER_ROLES` | Existing setting that lists permitted ownership groups. |
| `diary_key` | Existing design name for a diary selector supplied to a view. |
| `template_name` | Existing view selector for a named template. |
| `Diary/identity.py` | Optional refactoring proposal. No V1 implementation is required. |
| `DjangoActorFactory.from_user()` | Optional internal factory proposal. No V1 implementation is required. |
| `get_diary_keys()` | Existing `DiaryScopeMixin` method that supplies trusted host scope. |

Other code names below identify existing files, classes, methods, template blocks, or checklist items.

## DV1-013: Identity and role adapters

**Status: implemented for required V1 interfaces.**

The technical adapter `DjangoOwnerDirectory.person_in_groups()` in [Diary/views.py](../../Diary/views.py) uses the configured Django user model.
`DiaryScopeMixin.dispatch()` builds an Actor from authenticated identity, current groups, and trusted permitted diary keys.
`DiaryScopeMixin.get_diary_keys()` supplies the host scope extension.
The personal, manager, task creation, and task detail views share that scope implementation.
Template operations use the configured manager group.

[TemplateEditorTests](../../Diary/tests/test_template_editor.py), [PersonalDiaryTests](../../Diary/tests/test_personal_view.py), and [ManagerDiaryTests](../../Diary/tests/test_manager_view.py) cover current groups and scoped views.
[TaskCreationTests](../../Diary/tests/test_task_creation.py) and [TaskEditingTests](../../Diary/tests/test_task_editing.py) cover assignment, date changes, and completion access.
The recorded standard-user and host-user checks verify both configured user models.

The earlier proposed identity module and internal factory are optional refactoring choices.
They are not missing V1 requirements.
No implementation remains under DV1-013 after removal of the copying workflow.

## DV1-014: Startup access-group validation

**Status: implemented.**

[Diary/roles.py](../../Diary/roles.py) contains `access_groups()` and `validate_access_groups()`.
The first function checks setting values without database access.
The second checks that both configured access groups exist and have at least one user.
It uses the configured Django user model and one database query.
It does not create groups or change membership.

[Diary/apps.py](../../Diary/apps.py) calls both validation stages from `DiaryConfig.ready()`.
Ordinary management commands, WSGI startup, and ASGI startup require valid populated access groups.
Errors distinguish invalid settings, missing groups, empty groups, and database failures.
They identify the relevant settings and group names.

Database setup and repair commands defer database checks while retaining setting-value checks.
Those commands are `migrate`, `sync_access_policy`, `shell`, `createsuperuser`, and `loaddata`.
The `test` command also defers database checks before Django creates its separate test database.
Tests then exercise normal startup against that database.
These exceptions do not exempt a subsequent server startup.
The [usage guide](../../Diary/README.md#startup-setup-and-repair-commands) explains each exception.

**Verification**

[Diary/tests/test_roles.py](../../Diary/tests/test_roles.py) contains `AccessGroupConfigurationTests` and `AccessGroupDatabaseTests`.
They verify different group names, missing groups, empty groups, current membership, and a configured shared group.
They cover database failure and unavailable tables through an isolated PostgreSQL search path.
They verify normal startup, setup-command exceptions, and setting validation before database access.
The complete Diary suite also runs with standard and custom Django user models.

**Remaining boundary**

No implementation work remains for DV1-014.
DV1-015 now provides ownership-group membership checks at startup.
DV1-016 now provides ownership validation during diary creation.
DV1-014 does not provide continuous runtime monitoring.

## DV1-015: Startup ownership membership validation

**Status: implemented.**

[Diary/roles.py](../../Diary/roles.py) contains `validate_task_owner_roles()`.
It checks that each configured ownership group exists and has at least one member.
The membership query uses `get_user_model()` and evaluates all configured groups in one database query.
An empty `DIARY_TASK_OWNER_ROLES` collection requires no ownership query.
Validation does not create groups, assign users, or change task ownership.

[Diary/apps.py](../../Diary/apps.py) calls the validator from `DiaryConfig.ready()` during normal startup.
Errors identify `DIARY_TASK_OWNER_ROLES` and separately list missing groups and empty groups.
Database failures retain their configuration context.
The existing setup, repair, and test-command exceptions remain unchanged.

**Verification**

[Diary/tests/test_roles.py](../../Diary/tests/test_roles.py) contains `OwnershipGroupMembershipTests`, `DjangoGroupDatabaseTests`, and `RoleConfigurationTests`.
They verify populated groups, missing groups, empty groups, and membership changes.
They also verify database failures, empty configuration, normal startup, and setup-command exceptions.
Populated access groups do not satisfy membership requirements for separate ownership groups.

**Remaining boundary**

No implementation work remains for DV1-015.
DV1-016 now provides fresh ownership validation during diary creation.
Continuous runtime monitoring remains outside the implemented startup checks.

## DV1-016: Ownership validation during diary creation

**Status: implemented.**

[Diary/api.py](../../Diary/api.py) provides `DiaryAPI.create_diary()` and `DiaryInstance.create()`.
Both entry points use `validate_task_owner_roles()` from [Diary/roles.py](../../Diary/roles.py).
The instance factory checks caller permission before checking the current ownership configuration.
The checks run inside the existing creation transaction before diary writes.
Every configured ownership group must exist and have a member, even when the selected template does not use that group.

Invalid configuration raises `ImproperlyConfigured` without retaining partial diary data.
Repeated calls revalidate ownership before returning an existing diary reference.
Failed retries preserve existing records.
A failure later in the copy workflow rolls back new diary data, dates, task copies, and dependency links.
The validator does not change groups, memberships, or source templates.

**Verification**

[Diary/tests/test_creation_validation.py](../../Diary/tests/test_creation_validation.py) contains `DiaryCreationValidationTests`.
It covers both factories, runtime group deletion, membership removal, configuration changes, retries, and membership repair.
It checks permission ordering and database failures.
It also forces failure after the first task copy to verify transaction rollback.

**Remaining boundary**

No implementation work remains for DV1-016.
The checks use current membership when creation validates the configured roles.
Continuous monitoring after validation remains outside this feature.

## DV1-018: Authenticated task views

**Status: implemented for required V1 interfaces.**

[Diary/urls.py](../../Diary/urls.py), technical symbol `urlpatterns`, provides the required routes.
[Diary/views.py](../../Diary/views.py) provides `PersonalDiaryView`, `ManagerDiaryView`, `TemplateEditorView`, `TemplateCreateView`, `TaskCreateView`, and `TaskDetailView`.
The task detail route also handles completion and manager Close all through POST.

These interfaces authenticate callers and enforce their configured roles and permitted diary scope.
Browser writes use CSRF protection and callable API operations.
Reads do not create diaries or copy tasks.
The checklist links the corresponding template, personal, manager, creation, and editing tests.

No additional ordinary-user full diary route is required.
No template-to-diary copying route is required.
No implementation remains under DV1-018.

## DV1-022: Manager full diary list

**Status: implemented.**

The user confirmed the V1 scope for task lists:

- DiaryUsers need the existing assigned-task view.
- DiaryManagers need the existing full diary list for a permitted diary.

V1 requires no separate full diary list for ordinary users.
This scope does not require a new route or a permission change.
The optional whole-team selection remains available in the personal view.

The technical view classes are `PersonalDiaryView` and `ManagerDiaryView` in [Diary/views.py](../../Diary/views.py).
DV1-021 identifies the personal view.
DV1-022 identifies the manager's full diary list.
DV1-052 identifies its manager filters.

The manager page uses [manager_diary.html](../../Diary/templates/Diary/manager_diary.html), block `diary_content`.
Its task fragment is [partials/manager_tasks.html](../../Diary/templates/Diary/partials/manager_tasks.html), class `.diary-manager-task-list`.
[ManagerDiaryTests](../../Diary/tests/test_manager_view.py) covers current owners, permissions, diary scope, task selection, history, and empty states.
[ManagerDiaryBrowserTests.test_manager_filters_and_layout](../../Diary/tests/browser_manager_diary.py) covers keyboard controls, combined filters, narrow screens, and host style overrides.
This documentation correction relies on that existing evidence and adds no executable verification.

DV1-034 is not required, and DEC-003 is closed.
Neither item blocks the existing task-list interfaces.

## DV1-052: Manager filters for one diary

**Status: implemented.**

The technical view class `ManagerDiaryView` implements the manager-only list for one permitted diary.
The named route `Diary:manager-diary` uses `/diary/manager/` in the standard project URL configuration.
`ManagerDiaryFilterForm` supplies three checkboxes, all clear by default:

| Interface label | Technical GET name | Selected behavior |
| --- | --- | --- |
| include completed tasks | `include_completed` | Include completed records for history inspection. |
| exclude blocked tasks | `exclude_blocked` | Exclude incomplete tasks with incomplete predecessors. |
| exclude non-late tasks | `exclude_non_late` | Select only incomplete tasks due today or earlier. |

The default view shows all incomplete tasks, including blocked tasks and tasks that are not late.
The view applies all selected exclusions together.
Completed tasks are never late or blocked in this presentation.
The late-only option therefore excludes completed history, even when the history checkbox is selected.
The blocked-task exclusion retains completed history.
Tasks without a due date are not late.
Date comparisons use the Diary time zone or the project default.

The page orders tasks by due date, with unset dates last.
It displays task text, source, current ownership, dependency state, and lateness.
Completion records show the actor, time, and preserved due date.
Closed diaries remain readable with a closed-state message.
Displaying those records does not add them to active-task reads elsewhere.
The page provides no task mutation controls.
Forced-completion comments remain part of DV1-038.

**Selectors and scope**

GET input uses the technical query name `diary_key`.
Trusted context uses `diary_key` and `permitted_diary_keys`.
Host code can supply context through `extra_context` or `get_context_data()`.
The view also accepts those names as class attributes through `as_view()`.
A host subclass can override `get_diary_keys()` for request-specific scope.
The default route grants no diary scope.
GET input cannot supply permitted diary keys.
A selector only narrows the trusted scope and never grants access.

Equivalent UUID selectors are accepted.
Malformed, blank, or conflicting selectors return HTTP 400.
An in-scope key without a diary returns HTTP 404.
An out-of-scope key returns HTTP 403.
An omitted selector displays an explicit selection message.
No read changes diary data or task records.

**Presentation and verification**

`Diary/manager_diary.html` extends the complete base document through `diary_content`.
`Diary/partials/manager_diary.html` provides the reusable `.diary-manager` fragment.
`Diary/partials/manager_tasks.html` renders `.diary-manager-task-list` and `.diary-manager-completion`.
Manager task-state classes provide red, amber, and dashed borders with text labels.
The usage guide documents every new styling class and variable.
Existing styling class names retain their meanings.

[Manager view tests](../../Diary/tests/test_manager_view.py) contain `ManagerDiaryTests`.
They verify both selectors, trusted context variants, all filter combinations, permissions, scope, history, current owners, time zones, and empty states.
[Chrome verification](../../Diary/tests/browser_manager_diary.py) contains `ManagerDiaryBrowserTests.test_manager_filters_and_layout`.
It verifies keyboard checkbox operation, history selection, combined filters, reset behavior, mobile layout, and host styling overrides.

**Remaining boundary**

No implementation work remains for DV1-052.
The personal list is implemented separately.
DiaryUsers use the implemented assigned-task view. V1 requires no additional ordinary-user full diary list.
Host integration must supply the permitted keys for its own authenticated users.
Future date-window filtering remains deferred under DFUT-003.

## DV1-020, DV1-021, and DV1-049: Personal diary

**Status: implemented.**

The technical API methods are `DiaryAPI.personal_tasks()` and `DiaryInstance.personal_tasks()` in [Diary/api.py](../../Diary/api.py).
They return open tasks owned by the caller or the caller's current groups.
The caller can select one permitted diary or all permitted open diaries.
Results include each diary's key and name.
Whole-team tasks require an explicit option.

The technical view class is `PersonalDiaryView` in [Diary/views.py](../../Diary/views.py).
The default route is `Diary:personal-diary` in [Diary/urls.py](../../Diary/urls.py).
The host supplies permitted keys through trusted context or `DiaryScopeMixin.get_diary_keys()`.
The default route grants no diary scope.
Current group membership controls access on each request.

The view groups tasks by diary name and key.
It shows ready tasks by default, including late ready tasks.
The “show blocked also” checkbox adds blocked owned tasks.
The separate whole-team checkbox adds whole-team tasks.
Specific status filters take precedence over the blocked-task checkbox.
Late tasks contribute only to the Late count.
Ready and Blocked counts exclude late tasks.
Status links retain the selected diary and optional display choices.
Future date-window controls remain deferred under DFUT-003.

**Selectors and empty states**

GET selectors, view attributes, and trusted context use `DiaryScopeMixin.selected_key()`.
Malformed, blank, or conflicting selectors return HTTP 400.
An out-of-scope selector returns HTTP 403.
An unknown permitted key returns HTTP 404.
A selected diary retains its name when no tasks match.
A selected closed diary displays its closed state without active tasks.
Reads create no diaries and change no tasks.

**Privacy boundary: implemented DV1-031**

The technical function `_visible_entries()` removes another person's private additions and related keys from ordinary-user reads.
Managers can inspect these entries within their permitted diary scope.
Template tasks remain visible through ordinary diary reads, regardless of owner.
Personal selection includes only matching owners and current roles.
Private tasks cannot appear as predecessor choices.
Readiness uses the complete dependency graph before visibility filtering.

Task details and completion now have privacy verification.
The technical methods `DiaryAPI.search_tasks()` and `DiaryInstance.search_tasks()` search visible names and descriptions only.
The technical helper `_search_entries()` rejects invalid text and limits searches to 256 characters.
An omitted diary selector searches all permitted diaries, including completion history and closed diaries.
An explicit selector retains scope and existence checks.

The technical view class `DiaryDataView` provides authenticated, read-only JSON routes.
It shares `DiaryScopeMixin` with the HTML views.
The default routes grant no diary scope.
[HTTP data integration](../../Diary/README.md#http-data-api) documents route names, selectors, response fields, and errors.
Private and unknown task lookups return the same HTTP 404 response.
Successful responses and handled errors prohibit storage and vary by session cookie.
The view repeats identity and current group checks for every request.

[PersonalEntryPrivacyTests](../../Diary/tests/test_privacy.py) verifies callable searches, JSON resources, HTML details, private blockers, and completion references.
It also verifies current permissions, scope changes, unsupported writes, and the manager-only template editor.
The template editor reads template records only. Its JavaScript receives no private diary additions.
No privacy implementation remains under DV1-031.
Task detail links now provide blocker inspection and completion.
The personal list keeps its separate task-selection controls.

**Implementation and verification**

The technical form class is `PersonalDiaryFilterForm` in [Diary/forms.py](../../Diary/forms.py).
The page template is [personal_diary.html](../../Diary/templates/Diary/personal_diary.html), block `diary_content`.
The reusable fragment is [partials/personal_diary.html](../../Diary/templates/Diary/partials/personal_diary.html), class `.diary-personal`.
The task fragment uses `.diary-task-late`, `.diary-task-blocked-late`, and `.diary-task-blocked` for state highlights.
The [usage guide](../../Diary/README.md#personal-diary-page-integration) describes integration and controls.

[PersonalDiaryTests](../../Diary/tests/test_personal_view.py) verifies ownership, privacy, selectors, filter combinations, counts, date boundaries, and reads without changes.
The earlier personal-view review passed 11 tests against a separate PostgreSQL database with Django's standard user model.
Earlier logs record nine personal tests and 145 Diary tests passing.
The earlier Chrome log records two passing tests, including `PersonalDiaryBrowserTests.test_personal_filters_keyboard_and_layout`.
That browser method checks keyboard controls, mobile layout, status filters, privacy, and host style overrides.
This documentation change did not repeat the earlier broader or browser checks.
Host dashboard integration and deployment remain separate work.

## DV1-028: Frozen diary dependencies

**Status: implemented.**

The confirmed V1 policy prohibits dependency changes after a diary's initial creation.
The policy applies to users, managers, open diaries, closed diaries, and completed tasks.
Initial template dependencies remain part of the creation snapshot.
Template graph changes do not propagate to existing diaries.

The technical API method `_DependencyAPI.set_predecessors()` in [Diary/api.py](../../Diary/api.py) rejects every diary edit.
It retains role, diary scope, and closure checks.
Draft template edits remain permitted through the same method.
The technical model methods `EntryDependency.clean()`, `EntryDependency.save()`, and `EntryDependency.delete()` in [Diary/models.py](../../Diary/models.py) enforce normal model writes.

Migration [0006_freeze_live_dependencies.py](../../Diary/migrations/0006_freeze_live_dependencies.py), class `Migration`, adds the internal technical field `EventCalendar.dependencies_locked`.
Existing rows start locked, without any change to their dependency links or completion data.
`DiaryInstance.create()` initializes a new graph and locks it before returning.
PostgreSQL rejects unlocking and prevents an unfinished initialization transaction from committing.

The migration's technical SQL value `FORWARD_SQL` defines guards for dependency row writes and stable endpoint identities.
These guards cover bulk writes, querysets, and many-to-many relationship operations.
Normal dates, completion actions, and closed-diary reads continue to work.

[LiveDependencyTests](../../Diary/tests/test_live_dependencies.py) covers API, model, bulk, relationship, browser-action, and identity restrictions.
`LiveDependencyTransactionTests` covers concurrent mutations and unfinished initialization.
`LiveDependencyMigrationTests.test_existing_links_and_completion_records_are_preserved` applies the real migration to historical PostgreSQL tables.
The template graph race remains in [DependencyConcurrencyTests.test_concurrent_opposite_links_cannot_form_a_cycle](../../Diary/tests/test_concurrency.py).
Historical test fixtures use [seed_legacy_dependencies](../../Diary/tests/legacy_dependencies.py) only to represent pre-migration data.
Production code does not use that fixture helper.

No implementation remains under DV1-028.
DFUT-004 records possible later editing, without an assigned release or approved policy.

## DV1-029, DV1-030, and DV1-033: Task creation

**Status: implemented.**

The approved requirements remain in [Entry creation](event-calendar.md#entry-creation-confirmed-requirements).
The technical view class is `TaskCreateView` in [Diary/views.py](../../Diary/views.py).
The route `Diary:task-create` uses `/diary/tasks/new/` in the standard project URL configuration.
The technical form classes are `TaskCreateForm` and `ReusableTaskRuleForm` in [Diary/forms.py](../../Diary/forms.py).
The complete document uses [task_create.html](../../Diary/templates/Diary/task_create.html), block `diary_content`.
The reusable content uses [partials/task_create.html](../../Diary/templates/Diary/partials/task_create.html), class `.diary-create`.

**Identity, ownership, and scope**

The host supplies trusted permitted diary keys through `DiaryScopeMixin`.
An omitted selector opens a chooser of permitted open diaries.
POST requires one selected permitted diary.
The default route grants no scope.
Ordinary users receive self-owned personal tasks.
The server rejects modified owner identifiers and template requests from ordinary users.
Managers can select an eligible active person, a configured ownership group, or Whole team.
Current configured group membership controls each request.
Closed diaries reject new tasks.

**Combined save**

The “Add to template for future diaries” checkbox is clear initially.
The form identifies the source template and its current highest version.
The manager must select a separate reusable future date rule.
That rule can use an existing milestone, an offset from a milestone, or an annual date.
The future task keeps the diary task's name, description, owner, and entry key.
The diary task can keep an independent exact date.
The form never converts an exact date into an annual date automatically.

The technical method `DiaryInstance.create_task()` saves both additions in one PostgreSQL transaction.
It locks the diary and its source template.
It adds to the source template's highest version, including any draft.
The method keeps existing tasks and dependency links in the new approved revision.
A stale `expected_version_key` rejects the save.
A template-save failure rolls back the diary addition.
Repeated combined requests reject the shared entry key without creating another task or revision.
Concurrent requests from one template base allow one successful revision.

The new diary task remains a diary addition with no `source_entry` reference.
Its shared entry key identifies the new template task without changing the diary's original template version.
Other diary records, completion data, and dependency links remain unchanged.
Future diaries use the newly approved version when callers select the latest approved template.

**Verification and remaining boundaries**

[TaskCreationTests](../../Diary/tests/test_task_creation.py) verifies ownership, forged requests, CSRF checks, scope, date rules, template revisions, retries, and rollback.
`TaskCreationConcurrencyTests` verifies stale concurrent additions and simultaneous duplicate requests with independent PostgreSQL connections.
[TaskCreationBrowserTests.test_personal_and_manager_creation_keyboard_mobile_and_overrides](../../Diary/tests/browser_task_creation.py) verifies production forms in Chrome.
The browser check covers personal tasks, manager assignments, template additions, keyboard controls, narrow screens, and host style overrides.
The [usage guide](../../Diary/README.md#task-creation-page) identifies host integration and each new styling class.

Task creation requires no additional migration.
DV1-034 is not required, and DEC-003 is closed.
Task details and completion now use `TaskDetailView`.
The existing personal and manager views satisfy the V1 task-list scope.
The proposed identity module and internal factory remain open decisions under DV1-013.
The implemented task creation view does not require those proposed interfaces.

## Task editing and completion: DV1-023, DV1-032, and DV1-035 through DV1-038

**Status: implemented.**

The user approved due-date edits for self-owned diary additions and manager edits to copied template-task dates.
The existing [completion requirements](event-calendar.md#task-completion-and-blocking-predecessors-confirmed-v1-requirements) define normal completion and manager Close all.
DEC-002 also permits managers to edit orphaned template-task ownership through the existing task editor under DEC-005.
Ownership changes are ordinary task edits without a separate popup or approval step.
Other task fields and extra progress states have no V1 editing interface.

**Implemented storage and date behavior**

The technical model is `CalendarEntry` in [Diary/models.py](../../Diary/models.py).
Its new technical fields are `due_date_override`, `revision`, `completion_action`, `completion_comment`, and `completion_target_key`.
Migration [0005_task_dates_and_completion.py](../../Diary/migrations/0005_task_dates_and_completion.py), class `Migration`, adds these fields without changing existing records.
An override changes one diary task's effective due date.
The original date rule, template version, other diary tasks, and other diaries remain unchanged.
Completed tasks and closed diaries reject edits.

V1 does not warn managers when a due-date change causes a conflict.
It does not detect scheduling conflicts between changed dates and predecessor or successor dates.
The [user guide](../../Diary/README.md#due-date-permissions) records this required limit.

**Implemented API and UI**

The technical methods are `DiaryInstance.task()`, `DiaryInstance.update_due_date()`, and `DiaryInstance.complete()` in [Diary/api.py](../../Diary/api.py).
The technical view class is `TaskDetailView` in [Diary/views.py](../../Diary/views.py).
The route `Diary:task-detail` requires a task UUID and one selected permitted diary.
The host supplies trusted scope through `DiaryScopeMixin`.
The optional technical context name `task_detail_url_name` connects host task lists to their equally scoped detail route.
The page uses [task_detail.html](../../Diary/templates/Diary/task_detail.html), block `diary_content`.
The reusable content uses [partials/task_detail.html](../../Diary/templates/Diary/partials/task_detail.html), class `.diary-detail`.

The technical form classes are `TaskDueDateForm` and `TaskCompletionForm` in [Diary/forms.py](../../Diary/forms.py).
A task revision prevents stale edits or stale first completion requests.
The due-date form is available only for self-owned diary additions or manager-permitted tasks.
Completion permission follows task visibility independently of date-edit permission.

**Blocker display and force completion**

`DiaryInstance._open_blockers()` finds all open direct and indirect predecessors.
Traversal stops at completed predecessors.
`DiaryInstance.task()` shows visible blockers and one generic marker for inaccessible blockers.
This implements DEC-004 without exposing private names, dates, owners, keys, or a private-blocker count.
The marker text is an implementation choice within the approved privacy requirements.

Normal completion rejects any remaining open predecessor under the diary write lock.
Manager Close all completes the open chain and selected task in one transaction.
An opaque HMAC fingerprint binds the force action to the inspected chain state.
HMAC means keyed-hash message authentication code.
The fingerprint contains no readable private task identifiers.
A changed chain or due date requires another inspection.
The operation keeps earlier completion records and dependency links unchanged.
Each forced predecessor records the action and selected task in a persistent comment.
Ordinary readers receive a generic comment when the selected task is inaccessible.

**Verification**

[TaskEditingTests](../../Diary/tests/test_task_editing.py) covers ownership, copied-task restrictions, private blockers, audit privacy, date overrides, revisions, normal completion, Close all, and rollback.
`TaskEditingConcurrencyTests` covers competing date edits, completion retries, date changes against completion, diary closure, and forced completion against a predecessor edit.
`TaskCompletionMigrationTests.test_existing_dates_and_completion_records_remain_unchanged` applies the actual migration to historical PostgreSQL tables.
[TaskEditingBrowserTests.test_personal_dates_manager_template_dates_completion_and_layout](../../Diary/tests/browser_task_editing.py) covers list navigation, date edits, completion history, keyboard controls, narrow screens, and host style overrides.
The [styling guide](../../Diary/README.md#task-detail-styling-classes) defines every added class and identifies reused CSS variables.
The exact staged implementation passed 177 tests with each user-model configuration against separate PostgreSQL test databases.

**Remaining boundaries**

DV1-022 is complete through the existing manager diary list.
Copying existing template tasks into existing diaries is not required.
DV1-028 now enforces the live dependency restriction through the API, models, and PostgreSQL.
V1 does not add task reopening, owner changes, other content edits, or automatic scheduling-conflict warnings.
The proposed shared identity module remains an open implementation choice under DV1-013.

## DV1-019: Diary selectors

**Status: implemented for required V1 interfaces.**

The technical methods are `TemplateEditorView.dispatch()`, `DiaryScopeMixin.selected_key()`, and `DiaryScopeMixin.get_diary_keys()` in [Diary/views.py](../../Diary/views.py).
Template views accept a named selector or open the template chooser.
Personal views accept one permitted diary or select assigned tasks across permitted open diaries.
Manager views require one selected diary for the full list.
Task creation offers a permitted diary chooser when no diary is selected.
Task details and completion require an explicit permitted diary.

URL selectors and trusted view context use the same scope checks.
Conflicting, malformed, unknown, and out-of-scope selectors retain their documented error behavior.
A selector cannot grant diary access.

The checklist identifies selector verification in `TemplateEditorTests`, `ManagerDiaryTests`, `PersonalDiaryTests`, `TaskCreationTests`, and `TaskEditingTests`.
No additional selector interface is required for the removed copying workflow.
No implementation remains under DV1-019.

## DV1-041: Pages and styling

**Status: implemented for required V1 pages.**

The template, personal, manager, task creation, and task detail workflows have complete documents and reusable fragments.
Their styling classes and CSS variables are documented in [Diary/README.md](../../Diary/README.md).
Completion uses the task detail page.
Task state rules appear in [Diary/static/Diary/styles/diary.css](../../Diary/static/Diary/styles/diary.css).
The technical selectors include `.diary-task-late`, `.diary-manager-task-late`, and `.diary-detail-late`.

[DiaryStyleOverrideTests](../../Diary/tests/test_styling.py) covers complete and embedded documents and host styles.
The recorded template, personal, manager, task creation, and task editing browser tests cover their current controls and layouts.
The task editing browser check also verifies dashed, amber, and red border behavior.
DV1-039 is complete for the current required task views.

No ordinary-user full diary page or copying page is required.
No implementation remains under DV1-041.

## DV1-042: Empty and error states

**Status: implemented for required V1 interfaces.**

The existing views handle empty personal selections, template choices, missing diaries, private tasks, denied access, and closed diaries.
Task forms keep submitted values after validation errors.
Task edits and forced completion reject stale state without partial changes.
Reads do not create diaries or silently select another diary after a selector error.

The technical view classes are `TemplateEditorView`, `ManagerDiaryView`, `PersonalDiaryView`, `TaskCreateView`, and `TaskDetailView` in [Diary/views.py](../../Diary/views.py).
Their corresponding test classes are identified in the checklist.
Those tests cover selected diary context, invalid input, permissions, privacy, empty results, and reads without writes.

The removed copying workflow needs no additional empty or error states.
No implementation remains under DV1-042.

## DV1-044: Remaining verification

**Current implementation**

[Diary/tests/test_template_editor.py](../../Diary/tests/test_template_editor.py) includes `TemplateEditorTests` and `TemplateRevisionConcurrencyTests`.
[Diary/tests/browser_template_editor.py](../../Diary/tests/browser_template_editor.py) includes `EditorBrowserTests.test_editor()`.
Existing tests cover other implemented Diary components, as recorded in the checklist.
Successful template tests do not verify unimplemented task workflows.

**Remaining requirements**

Add concurrent membership-change verification for the implemented ownership recovery workflow.
Transactions provide rollback. The shared diary row lock serializes supported writes to the same diary.
The technical method `_open_calendar()` obtains that lock before reassignment, completion, and other supported task changes.
Existing `TaskEditingConcurrencyTests` verify date edits, completion, and diary closure through separate database connections.
User and group membership records do not share the diary row lock.
An administrator can remove membership after Diary checks eligibility and before an assignment commits.
The assignment can then become orphaned again. This does not imply a partial transaction or corrupt task record.
The remaining tests must verify that behavior and the recovery operation's use of the existing diary lock.
No demonstrated transaction defect is recorded under DV1-044.
Task creation tests now cover ownership, template revisions, rollback, duplicate requests, and concurrent saves.
Personal tests now cover privacy, cross-diary reads, configured groups, selectors, and filters.
Verify repeated requests and transaction rollback for each new operation.
Verify concurrent completion, diary closure, and permitted task edits.
Repeat integration checks with standard and custom Django user models.
Keep all database tests on separate PostgreSQL test databases.

**Proposed implementation**

Extend tests alongside each dependent feature instead of deferring verification to release.
Use separate database connections for concurrency checks.
Check both the operation result and preserved database records after a rejected operation.
Reuse the standalone test configuration to detect host business-model dependencies.
Extend browser coverage after task routes and completion controls exist.

| Related items | Verification still required |
| --- | --- |
| DV1-013, DV1-018, DV1-019 | Implemented for the required interfaces. |
| DV1-031 | Implemented privacy checks for searches, HTTP data reads, and related task references. |
| DV1-028 | Implemented dependency freeze with API, model, migration, and concurrency verification. |
| DV1-043 | Implemented milestone restriction with API, model, and PostgreSQL verification. |
| DV1-035 through DV1-038 | Implemented and verified through the task detail workflow. |
| DV1-040 | Implemented under DEC-005. Concurrent membership-change verification remains under DV1-044. |
| DV1-039, DV1-041, DV1-042 | Implemented for the required pages and states. |

**Completion checks**

Record the exact test files and symbols under each completed checklist item.
Record PostgreSQL test results and the isolated-project verification result.
Keep DV1-044 unchecked until its remaining dependent workflows have verification.
DV1-045 separately requires final release documentation and deployment checks.

## DFUT-003: Future date-window filtering

**Confirmed deferred requirement**

All diary views must eventually let users select incomplete tasks due within a specified future date window.
This includes personal task views and views of a specific permitted diary.
The filter must preserve task privacy and the host's permitted diary scope.
The requirement has no assigned release and is not a V1 completion condition.
No production controls or executable verification implement it.

**Proposed implementation**

Use one date-window rule across diary views.
Apply the window to each task's calculated due date.
Use the Diary time zone for relative future windows.
Show the selected window and provide an action to clear it.
Combine the window with permitted task selection before rendering results.
Document each implemented control and styling class in the usage guide.

**Open decisions**

Define absolute date inputs, relative windows, or support for both.
Define whether the start and end dates are included.
Define whether the window can start today.
Define handling for invalid ranges and tasks without a due date.
Define interactions with completion history, late-only selection, and blocked-task filters.
Define whether window selection persists across diary views.

**Future completion checks**

Verify boundary dates and Diary time-zone changes.
Verify exclusion of completed tasks and tasks outside the selected window.
Verify task privacy and permitted diary scope in every applicable view.
Verify consistent results between personal views and specific diary views.
Record exact implementation and verification symbols when this deferred requirement is implemented.

## DFUT-004: Live diary dependency editing

**Backlog proposal. No assigned release.**

A later version may offer a controlled editor for existing diary dependencies.
This is not an approved V1 editing capability.
The V1 database guards and API restrictions remain in force.

**Open design questions**

Define which roles can edit and which graph changes are permitted.
Define handling for completed tasks, forced completions, and completion history.
Define the effect on readiness and the display of changed blocking chains.
Define cycle checks, concurrent saves, rollback, and closed-diary behavior.
Define the records needed to explain who changed a graph and why.
A future implementation must explicitly replace the V1 restriction through reviewed code and database changes.

No editor, public mutation method, or release date is approved by this backlog record.

## Review limits

The staged DV1-031 implementation passed 200 tests with each supported user model.
Both runs used separate PostgreSQL test databases.
All 15 Chrome cases passed, including one template-editor retry after a stale-element error.
The new privacy test class covers callable search, JSON reads, HTML details, related references, current roles, and trusted scope.
No application data or deployed services changed during verification.

The staged dependency restriction passed 190 tests with each supported user model.
Both runs used separate PostgreSQL test databases.
All 15 Chrome cases passed.
One navigation case required a retry after a Chrome document-node error.

This document records remaining work and proposed implementation boundaries.
It does not change application code, migrations, or deployed services.
The checklist retains its existing identifiers.
DV1-023, DV1-032, and DV1-035 through DV1-038 are also complete.
The checklist identifies the other completed components.
DV1-013, DV1-018, DV1-019, DV1-039, DV1-041, and DV1-042 are complete for the required interfaces.
The remaining partial items stay unchecked.
DV1-034 is not required, and DEC-003 is closed.
ASD-STE100 Issue 9 was available locally.
A full dictionary and technical-name review remains necessary.
This document does not claim full ASD-STE100 compliance.

## DV1-040: Ownership recovery in the existing editor

**Current implementation**

The technical function `Diary.ownership.orphaned_entry_keys()` identifies open tasks without an eligible person or role member.
It excludes diary additions, completed tasks, and whole-team tasks.
The technical method `DiaryInstance.reassign_task()` requires manager permission, trusted diary scope, and the inspected task revision.
It checks current eligibility before it changes ownership.
It preserves task dates, task identity, dependency links, and completion records.
An explicit `update_template=True` also creates an approved template version in the same transaction.
That option requires `expected_version_key` and a matching stable task key in the latest template.
Failure rolls back both operations. Existing diary copies retain their owners.
The technical class `OwnershipRecoveryTests` verifies permission, stale revisions, closure, replacement eligibility, and template rollback.

**Approved decision: DEC-005**

The manager full diary list places orphaned template tasks before other tasks.
The normal date, name, and stable-key ordering remains within each category. Existing filters still apply.
Managers can leave an orphaned task unresolved.
An unresolved task preserves its owner and remains incomplete.
Dependent tasks remain blocked while that predecessor stays incomplete.
Managers assign replacements through the existing task detail editor. No separate popup or recovery page is required.
Person replacements must be active members of the configured DiaryUser group.
Authorized ownership groups and whole-team ownership are also permitted.
The selected ownership group must have an eligible active member.
The existing editor changes this diary only. The optional template revision remains a callable API operation.

**Verification limits**

The technical class `ManagerOwnershipRecoveryTests` verifies list ordering, existing-editor controls, person eligibility, stale forms, and trusted scope.
The technical class `OwnershipRecoveryTests` verifies restored membership and rejection of diary additions and manager-only replacement persons.
The technical class `OwnershipRecoveryBrowserTests` verifies navigation, replacement controls, and phone layout.
DV1-044 retains verification for simultaneous membership changes, completion, and closure through separate database connections.

## DV1-043: Implemented milestone boundary

The technical method `DiaryInstance.set_milestone_dates()` rejects post-creation changes after permission, scope, and closure checks.
The technical class `CalendarMilestone` rejects normal model changes after initialization.
Migration `0007_freeze_live_milestones` protects stored dates against direct PostgreSQL writes.
It does not change existing milestone values.
The technical class `LiveMilestoneTests` verifies API, model, bulk insertion, queryset update, and deletion restrictions.
Milestone editing and impact review remain V2 work.
