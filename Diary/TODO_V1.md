# Diary V1 implementation checklist

Status reviewed: 3 November 2026.

This checklist tracks the generic Diary V1 requirements in the [design document](../docs/design/event-calendar.md).
Each identifier stays unchanged when its status changes.
A checked item identifies an implemented component, not a complete V1 release.
Unchecked items remain implementation or verification work.
Previews demonstrate behavior but do not complete production view requirements.
The [web user guide](USER_GUIDE.md) explains the current pages for DiaryUsers and DiaryManagers.
The [integration guide](README.md) documents setup, API operations, and integration limits.

Each item gives its completion condition and requirement reference.
Implementation and verification annotations name files and exact technical symbols.
Source comments use the same DV1 identifiers.
Partial implementation annotations do not mark an item complete.
Each partial item has a Remaining annotation.
Substantial remaining work has a linked design document.
Template blocks, CSS selectors, and JavaScript functions identify implementations without Python symbols.
Documentation-only items identify their section instead of an executable symbol.
The source links also identify the applicable design rules.
The final sections record confirmed decisions and deferred Diary features.

## Implemented components

- [x] **DV1-001: Independent PostgreSQL data layer.**
  Diary owns its models and migrations without foreign keys to host application models.
  Implementation: [models.py](models.py): `ValidatedModel`, `EventCalendar`, `TemplateVersion`, `CalendarEntry`. [migrations/0001_initial.py](migrations/0001_initial.py): `Migration`. [migrations/0002_remove_calendarentry_diary_calendarentry_date_shape_and_more.py](migrations/0002_remove_calendarentry_diary_calendarentry_date_shape_and_more.py): `Migration`.
  Verification: [tests/test_api.py](tests/test_api.py): `DiaryTests.test_postgresql`, `DiaryTests.test_models_have_no_foreign_keys_to_other_apps`.
  Requirement: [D4].

- [x] **DV1-002: Named milestone API.**
  Milestone names remain stable, and discovery returns the names used by the selected template version.
  Discovery is optional for callers that already know the required names.
  Implementation: [api.py](api.py): `DiaryAPI.define_milestones`, `DiaryTemplateVersion.required_milestones`. [models.py](models.py): `Milestone.clean`.
  Verification: [tests/test_api.py](tests/test_api.py): `DiaryTests.test_required_milestones_are_distinct_and_template_specific`.
  Requirement: [D4].

- [x] **DV1-003: Date calculation.**
  Source, relative, annual, and one-time rules calculate dates and identify missing or invalid dates.
  Lateness uses optional `DIARY_TIME_ZONE`, otherwise Django's `TIME_ZONE`, and includes tasks due today.
  Implementation: [date_rules.py](date_rules.py): `resolve_date`. [models.py](models.py): `EntryFields.resolve_date`. [api.py](api.py): `DiaryInstance.active_tasks`.
  Verification: [tests/test_api.py](tests/test_api.py): `DiaryTests.test_leap_day_and_previous_year`, `DiaryTests.test_active_tasks_can_be_blocked_and_late_and_exclude_completed_tasks`.
  Requirement: [D5] and [D6].

- [x] **DV1-004: Named diary creation and template snapshots.**
  Creation requires a nonempty name and copies an approved template's entries, rules, owners, and dependencies.
  Repeated creation with identical inputs returns the same Diary key.
  Existing diaries retain their copies after template changes.
  Implementation: [api.py](api.py): `DiaryInstance.create`. [entry_mapping.py](entry_mapping.py): `EntryMapper.snapshot_fields`.
  Verification: [tests/test_api.py](tests/test_api.py): `DiaryTests.test_calendar_creation_returns_a_stable_key_and_copies_rules_and_dependencies`. [tests/test_entry_mapping.py](tests/test_entry_mapping.py): `EntryMappingTests.test_snapshots_exclude_history_and_do_not_load_milestones`.
  Requirement: [D4].

- [x] **DV1-005: Ownership data and assignment checks.**
  The model supports person, role, and whole-team ownership.
  Ordinary users can add only self-owned personal entries.
  The configured edit permission controls assignments to another person or role.
  Implementation: [models.py](models.py): `EntryFields`, `owner_shape`. [entry_mapping.py](entry_mapping.py): `validate_entry_owner`. [api.py](api.py): `DiaryInstance.add_entry`, `DiaryTemplateVersion.add_entry`.
  Verification: [tests/test_api.py](tests/test_api.py): `DiaryTests.test_personal_entries_are_self_owned_and_repeat_calls_are_safe`, `DiaryTests.test_officer_can_assign_person_role_and_whole_team`. [tests/test_entry_mapping.py](tests/test_entry_mapping.py): `EntryMappingTests`.
  Requirement: [D6] and [D8].

- [x] **DV1-006: Saved dependency validation.**
  The API excludes circular choices and rejects invalid links within the saved graph.
  Database locks prevent concurrent saves from creating a cycle.
  Implementation: [api.py](api.py): `_DependencyAPI.available_predecessors`, `_DependencyAPI.set_predecessors`. [models.py](models.py): `DependencyFields.clean`, `DependencyFields.save`.
  Verification: [tests/test_api.py](tests/test_api.py): `DiaryTests.test_selector_excludes_self_and_transitive_successors`. [tests/test_concurrency.py](tests/test_concurrency.py): `DependencyConcurrencyTests`.
  Requirement: [D6].

- [x] **DV1-007: Task reads for one diary.**
  `DiaryInstance.active_tasks()` and `DiaryInstance.personal_tasks()` calculate readiness and lateness without stored status flags.
  Personal selection uses current user and role references.
  Callable and HTTP data reads protect personal entries under DV1-031.
  Implementation: [api.py](api.py): `DiaryInstance.read`, `DiaryInstance.active_tasks`, `DiaryInstance.personal_tasks`.
  Verification: [tests/test_api.py](tests/test_api.py): `DiaryTests.test_personal_tasks_include_matching_roles_without_duplicate_entries`, `DiaryTests.test_no_persistent_readiness_or_lateness_flags`.
  Requirement: [D6] and [D8].

- [x] **DV1-008: Close a diary instance.**
  `DiaryInstance.close()` accepts open tasks, preserves records, and safely handles repeated calls.
  Closed diaries remain readable but reject API changes and contribute no active tasks.
  Implementation: [api.py](api.py): `DiaryInstance.close`, `_open_calendar`. [models.py](models.py): `EventCalendar`. [migrations/0003_calendar_closure.py](migrations/0003_calendar_closure.py): `Migration`.
  Verification: [tests/test_api.py](tests/test_api.py): `DiaryTests.test_close_calendar_preserves_open_tasks_and_completion_records`, `DiaryTests.test_closed_calendar_rejects_api_changes`.
  Requirement: [D4].

- [x] **DV1-009: Configured ownership role names and existence checks.**
  `DIARY_TASK_OWNER_ROLES` controls assignment choices.
  Startup validates role existence directly through Django's standard group model.
  Ownership-role membership checks at startup are implemented under DV1-015.
  Creation validation is implemented under DV1-016.
  Template warnings are implemented under DV1-017.
  Implementation: [roles.py](roles.py): `task_owner_roles`, `validate_task_owner_roles`. [apps.py](apps.py): `DiaryConfig.ready`.
  Verification: [tests/test_roles.py](tests/test_roles.py): `RoleConfigurationTests`, `DjangoGroupDatabaseTests`.
  Requirement: [D4] and [D9].

- [x] **DV1-010: Basic completion record fields.**
  Models store the completing actor, completion time, and due date at completion.
  Normal saves protect completed records.
  Completion operations and explanatory comments still need DV1-035 through DV1-038.
  Implementation: [models.py](models.py): `CalendarEntry`, `CalendarEntry.clean`, `CalendarEntry.due_date`.
  Verification: [tests/test_api.py](tests/test_api.py): `DiaryTests.test_completed_due_date_stays_fixed_when_milestone_changes`.
  Requirement: [D6].

- [x] **DV1-011: Base template and reusable task fragment.**
  The task list can render as a complete document or as reusable content.
  Default styles and override guidance exist.
  Production pages still need DV1-041.
  Implementation: [templates/Diary/base.html](templates/Diary/base.html): `diary_styles`, `diary_content`. [templates/Diary/task_list.html](templates/Diary/task_list.html): `diary_content`. [templates/Diary/partials/task_list.html](templates/Diary/partials/task_list.html): `.diary-task-list`. [static/Diary/styles/diary.css](static/Diary/styles/diary.css): `.diary`.
  Verification: [tests/test_styling.py](tests/test_styling.py): `DiaryStyleOverrideTests`.
  Requirement: [D6].

- [x] **DV1-012: Runtime warning limit documented.**
  The API guide explains the absence of automatic warnings after ownership groups become empty or disappear.
  Restart, creation, and template editing remain the documented validation points.
  Implementation: [README.md](README.md): `Startup and ownership validation requirements`.
  Documentation only. No class or function provides continuous runtime monitoring.
  Requirement: [D9].

- [x] **DV1-046: Class-based callable API and factories.**
  `DiaryAPI` holds the actor context and provides shared services.
  `DiaryInstance`, `DiaryTemplate`, and `DiaryTemplateVersion` provide factories and object operations.
  Factories return references with stable keys without granting extra scope.
  Operations check permissions and current database state each time.
  Implementation: [api.py](api.py): `Actor`, `DiaryAPI`, `DiaryInstance`, `DiaryTemplate`, `DiaryTemplateVersion`, `_BoundObject`.
  Verification: [tests/test_class_api.py](tests/test_class_api.py): `ClassAPITests`.
  Requirement: [D4].

- [x] **DV1-047: Simple V1 access settings.**
  `DIARY_MANAGER` and `DIARY_USER` each select one group.
  Managers inherit user capabilities and have all template permissions.
  Startup rejects missing or invalid setting values.
  The old configurable action mapping grants no access in V1.
  Access-group existence and membership checks are implemented under DV1-014.
  Implementation: [roles.py](roles.py): `access_groups`. [api.py](api.py): `_allowed`, `_require`. [apps.py](apps.py): `DiaryConfig.ready`.
  Verification: [tests/test_roles.py](tests/test_roles.py): `AccessGroupConfigurationTests`. [tests/test_class_api.py](tests/test_class_api.py): `ClassAPITests`.
  Requirement: [D4] and [D9].

- [x] **DV1-048: Standard Django groups and optional template default.**
  Role checks use Django groups without a host lookup setting or callback.
  Explicit template names and version keys work without `DIARY_TEMPLATE_NAME`.
  The setting remains an optional default, and conflicting selectors are rejected.
  Implementation: [roles.py](roles.py): `validate_task_owner_roles`. [entry_mapping.py](entry_mapping.py): `validate_entry_owner`. [api.py](api.py): `_template_version`, `DiaryTemplate.from_name`, `DiaryTemplate.create`, `DiaryAPI.template_version`, `DiaryInstance.create`.
  Verification: [tests/test_roles.py](tests/test_roles.py): `DjangoGroupDatabaseTests`. [tests/test_class_api.py](tests/test_class_api.py): `ClassAPITests`.
  Requirement: [D4].

- [x] **DV1-050: Optional Diary time zone.**
  Use `DIARY_TIME_ZONE` when the host defines it.
  Otherwise use Django's project-default `TIME_ZONE`, independently of a temporarily activated user time zone.
  Preserve the caller's explicit `today` argument.
  The [configuration warning](README.md#current-api-configuration) explains UTC fallback, daylight saving time, and local-midnight lateness.
  Implementation: [api.py](api.py): `DiaryInstance.active_tasks`.
  Verification: [tests/test_time_zone.py](tests/test_time_zone.py): `DiaryTimeZoneTests`.
  Requirement: [usage guide](README.md#current-api-configuration) and [D6].

- [x] **DV1-051: Diary creation without a required year.**
  Creation accepts a name and milestone dates without a diary year or required host reference.
  Annual template dates use the nearest matching date strictly after diary creation.
  A matching date today selects the following year. February 29 selects the next valid leap day.
  The stored annual date remains unchanged during later reads, milestone changes, and creation retries.
  Migration preserves existing annual dates and completion records before removing the old diary year.
  Implementation: [api.py](api.py): `DiaryAPI.create_diary`, `DiaryInstance.create`, `DiaryInstance.set_milestone_dates`, `DiaryInstance.read`. [date_rules.py](date_rules.py): `next_annual_date`, `resolve_date`. [models.py](models.py): `EventCalendar`, `EntryFields.resolve_date`, `CalendarEntry.clean`, `CalendarEntry.annual_due_date`. [forms.py](forms.py): `TemplateTaskForm.year_offset`. [migrations/0004_milestone_dates_without_diary_year.py](migrations/0004_milestone_dates_without_diary_year.py): `Migration`, `preserve_annual_dates`.
  Verification: [tests/test_creation_dates.py](tests/test_creation_dates.py): `FixedDateCalculationTests`, `DiaryCreationDateTests`, `DiaryYearMigrationTests.test_migration_preserves_existing_dates_and_completion_records`. [tests/test_api.py](tests/test_api.py): `DiaryTests.test_documented_setup_and_callable_examples_execute`.
  Documentation: [Fixed dates and the 12-month limitation](README.md#fixed-dates-and-the-12-month-limitation) identifies the remaining calculation limit.
  Future implementations will address occurrence selection for diaries that span more than 12 months.
  Requirement: the user request for creation without a year and fixed-date calculations.

- [x] **DV1-056: Due dates based on previous tasks.**
  Implement [DFUT-014](../TODO.md#diary-feature-backlog): a task can take its due date from another task's due date with a signed calendar-day offset, independently of completion dependencies.
  Resolve task date chains in source-first order when the diary is created or tasks are first applied, regardless of template order.
  Reject missing, invalid, self-referencing, or cyclic date sources and unresolvable dates.
  Store the resolved due date and its source provenance. Late completion or a later edit to the source task must not move dependent due dates; an explicit override changes only the selected task.
  Support task-relative dates in template and diary forms, the callable API, template version copying, and fixture transfer.
  Implementation: [date_rules.py](date_rules.py), [api.py](api.py), [models.py](models.py), [forms.py](forms.py), and [migration 0013](migrations/0013_task_relative_due_dates.py).
  Verification: [task-relative date tests](tests/test_task_relative_dates.py) and [graph browser tests](tests/browser_template_graph.py).
  Documentation: [Due dates from other tasks](README.md#due-dates-from-other-tasks-dfut-014).
  Boundary: Tracking forward impacts remains a future requirement under DFUT-015 in the repository TODO.

## Access and validation work

- [x] **DV1-053: Template-sourced predecessor choices.**
  Exclude diary additions from predecessor choices, including tasks added by managers.
  Preserve the V1 restriction against changes to existing diary dependencies.
  Implementation: [api.py](api.py): `_DependencyAPI.available_predecessors`, `_DependencyAPI.set_predecessors`. [models.py](models.py): `CalendarEntry.clean`, `EntryDependency.clean`.
  Verification: [tests/test_personal_view.py](tests/test_personal_view.py): `PersonalDiaryTests.test_non_template_predecessors_are_excluded_and_rejected_atomically`.
  Requirement: [D6] template dependency rules and [D8] personal-entry privacy.

- [x] **DV1-013: Generic identity and role adapters.**
  Use the `DIARY_MANAGER` and `DIARY_USER` group names throughout Diary.
  Retrieve the configured user model through `get_user_model()` when model access is necessary.
  Keep host business models and custom request attributes outside Diary.
  Completion requires access tests with different host group names.
  Implementation: [views.py](views.py): `DjangoOwnerDirectory.person_in_groups`, `TemplateEditorView.dispatch`, `ManagerDiaryView.dispatch`, `ManagerDiaryView.get_diary_keys`. [forms.py](forms.py): `TemplateTaskFormSet.__init__`.
  Verification: [tests/test_template_editor.py](tests/test_template_editor.py): `TemplateEditorTests.test_person_ownership_uses_configured_user_model_and_rejects_other_users`.
  Manager verification: [tests/test_manager_view.py](tests/test_manager_view.py): `ManagerDiaryTests`.
  Personal implementation: [views.py](views.py): `DiaryScopeMixin.dispatch`, `DiaryScopeMixin.get_diary_keys`, `DiaryScopeMixin.selected_key`, `PersonalDiaryView.get`, `PersonalDiaryView.filter_context`, `DiaryOwnerLabelsMixin.get_owner_labels`. [templates/Diary/partials/task_list.html](templates/Diary/partials/task_list.html): `.diary-task-late`, `.diary-task-blocked-late`, `.diary-task-blocked`, `.diary-task-owner`.
  Personal verification: [tests/test_personal_view.py](tests/test_personal_view.py): `PersonalDiaryTests`. [tests/browser_personal_diary.py](tests/browser_personal_diary.py): `PersonalDiaryBrowserTests.test_personal_filters_keyboard_and_layout`.
  Task creation implementation: [views.py](views.py): `TaskCreateView.respond`. [templates/Diary/partials/task_create.html](templates/Diary/partials/task_create.html): `.diary-create`.
  Task creation verification: [tests/test_task_creation.py](tests/test_task_creation.py): `TaskCreationTests`, `TaskCreationConcurrencyTests`. [tests/browser_task_creation.py](tests/browser_task_creation.py): `TaskCreationBrowserTests.test_personal_and_manager_creation_keyboard_mobile_and_overrides`.
  Task detail implementation: [views.py](views.py): `TaskDetailView`. [templates/Diary/partials/task_detail.html](templates/Diary/partials/task_detail.html): `.diary-detail`, `.diary-detail-history`, `.diary-detail-late`, `.diary-detail-blocked-late`, `.diary-detail-blocked`.
  Task detail verification: [tests/test_task_editing.py](tests/test_task_editing.py): `TaskEditingTests`, `TaskEditingConcurrencyTests`, `TaskCompletionMigrationTests`. [tests/browser_task_editing.py](tests/browser_task_editing.py): `TaskEditingBrowserTests.test_personal_dates_manager_template_dates_completion_and_layout`.
  Scope: Existing required interfaces are implemented. Template-to-diary copying is not required.
  Design: [Implemented identity and role adapters](../docs/design/diary-v1-remaining-work.md#dv1-013-identity-and-role-adapters).
  Requirement: [D4] and [D8].

- [x] **DV1-014: Startup access-group validation.**
  Require `DIARY_MANAGER` and `DIARY_USER`.
  Startup validates setting values, database existence, and current membership for both access groups.
  Check that every referenced group exists and has at least one user.
  Raise `ImproperlyConfigured` with setting names and distinct missing-group or empty-group explanations.
  Keep database and group setup commands available.
  Implementation: [roles.py](roles.py): `access_groups`, `validate_access_groups`. [apps.py](apps.py): `DiaryConfig.ready`.
  Verification: [tests/test_roles.py](tests/test_roles.py): `AccessGroupConfigurationTests`, `AccessGroupDatabaseTests`.
  Setup and repair commands retain database-check exceptions. The test command creates its database before explicit startup validation tests.
  Design: [Completed startup validation](../docs/design/diary-v1-remaining-work.md#dv1-014-startup-access-group-validation).
  Requirement: [D9].

- [x] **DV1-015: Startup ownership membership validation.**
  Check that every configured task ownership role exists and has at least one member.
  Report each absent or empty role through `ImproperlyConfigured`.
  Startup checks current membership through the configured Django user model.
  Implementation: [roles.py](roles.py): `validate_task_owner_roles`. [apps.py](apps.py): `DiaryConfig.ready`.
  Verification: [tests/test_roles.py](tests/test_roles.py): `OwnershipGroupMembershipTests`, `DjangoGroupDatabaseTests`, `RoleConfigurationTests`.
  Preserve the existing setup and repair command exceptions.
  Requirement: [D9].

- [x] **DV1-016: Ownership validation during diary creation.**
  Repeat ownership existence and membership checks against the current database state.
  Reject creation when a configured role is absent or empty.
  Preserve transaction safety without a partly created diary.
  Recheck all configured ownership groups on each call, including repeated creation requests.
  Implementation: [api.py](api.py): `DiaryAPI.create_diary`, `DiaryInstance.create`. [roles.py](roles.py): `validate_task_owner_roles`.
  Verification: [tests/test_creation_validation.py](tests/test_creation_validation.py): `DiaryCreationValidationTests`.
  Invalid ownership configuration raises `ImproperlyConfigured` before any diary records are written.
  Design: [Completed creation validation](../docs/design/diary-v1-remaining-work.md#dv1-016-ownership-validation-during-diary-creation).
  Requirement: [D9].

- [x] **DV1-017: Empty-group warnings during template editing.**
  Check current membership for the selected ownership group.
  Show an on-screen warning with the group name and affected task when it has no members.
  Keep this warning separate from creation validation.
  Implementation: [forms.py](forms.py): `TemplateTaskFormSet.empty_roles`, `TemplateTaskFormSet.ownership_warnings`. [views.py](views.py): `TemplateEditorView.render_editor`. [static/Diary/scripts/template_editor.js](static/Diary/scripts/template_editor.js): `initialize`, `refresh`.
  Verification: [tests/test_template_editor.py](tests/test_template_editor.py): `TemplateEditorTests.test_empty_role_warning_names_task_and_preserves_role_assignment`. [tests/browser_template_editor.py](tests/browser_template_editor.py): `EditorBrowserTests.test_editor`.
  Requirement: [D9].

## HTTP views and task selection

- [x] **DV1-018: Authenticated routed views.**
  Add production URL routes and views for task lists, details, template editing, entry creation, and completion.
  Use the callable API for data actions.
  Template routes, manager and personal task lists, and task creation routes now exist.
  Enforce permissions on direct requests and save actions.
  Implementation: [views.py](views.py): `TemplateEditorView`, `TemplateCreateView`, `ManagerDiaryView.dispatch`, `ManagerDiaryView.get`. [urls.py](urls.py): `urlpatterns`.
  Verification: [tests/test_template_editor.py](tests/test_template_editor.py): `TemplateEditorTests.test_anonymous_and_ordinary_users_cannot_access_or_save_templates`, `TemplateEditorTests.test_http_post_requires_csrf_token`.
  Manager verification: [tests/test_manager_view.py](tests/test_manager_view.py): `ManagerDiaryTests`.
  Personal implementation: [views.py](views.py): `DiaryScopeMixin.dispatch`, `DiaryScopeMixin.get_diary_keys`, `DiaryScopeMixin.selected_key`, `PersonalDiaryView.get`, `PersonalDiaryView.filter_context`, `DiaryOwnerLabelsMixin.get_owner_labels`. [templates/Diary/partials/task_list.html](templates/Diary/partials/task_list.html): `.diary-task-late`, `.diary-task-blocked-late`, `.diary-task-blocked`, `.diary-task-owner`.
  Personal verification: [tests/test_personal_view.py](tests/test_personal_view.py): `PersonalDiaryTests`. [tests/browser_personal_diary.py](tests/browser_personal_diary.py): `PersonalDiaryBrowserTests.test_personal_filters_keyboard_and_layout`.
  Task creation implementation: [views.py](views.py): `TaskCreateView.respond`. [templates/Diary/partials/task_create.html](templates/Diary/partials/task_create.html): `.diary-create`.
  Task creation verification: [tests/test_task_creation.py](tests/test_task_creation.py): `TaskCreationTests`, `TaskCreationConcurrencyTests`. [tests/browser_task_creation.py](tests/browser_task_creation.py): `TaskCreationBrowserTests.test_personal_and_manager_creation_keyboard_mobile_and_overrides`.
  Task detail implementation: [views.py](views.py): `TaskDetailView`. [templates/Diary/partials/task_detail.html](templates/Diary/partials/task_detail.html): `.diary-detail`, `.diary-detail-history`, `.diary-detail-late`, `.diary-detail-blocked-late`, `.diary-detail-blocked`.
  Task detail verification: [tests/test_task_editing.py](tests/test_task_editing.py): `TaskEditingTests`, `TaskEditingConcurrencyTests`, `TaskCompletionMigrationTests`. [tests/browser_task_editing.py](tests/browser_task_editing.py): `TaskEditingBrowserTests.test_personal_dates_manager_template_dates_completion_and_layout`.
  Scope: Existing required interfaces are implemented. Template-to-diary copying is not required.
  Design: [Implemented authenticated views](../docs/design/diary-v1-remaining-work.md#dv1-018-authenticated-task-views).
  Requirement: [D6] and [D8].

- [x] **DV1-019: View object selectors.**
  Accept `diary_key` or `template_name` through URL parameters or trusted server-supplied context.
  Apply the same host scope and visibility checks for either input method.
  Template selectors accept URL values and trusted view context. Conflicting names return HTTP 400.
  Conflicting selectors produce a WARNING through the technical logger `Diary.views`.
  Implementation: [views.py](views.py): `DiaryScopeMixin.selected_key`, `TemplateEditorView.dispatch`.
  Log verification: [tests/test_manager_view.py](tests/test_manager_view.py): `ManagerDiaryTests.test_conflicting_malformed_repeated_and_unknown_selectors`. [tests/test_template_editor.py](tests/test_template_editor.py): `TemplateEditorTests.test_named_view_selects_latest_draft_and_supports_url_or_trusted_context`.
  Manager and personal selectors accept GET input and trusted view context. Personal selection supports one or all permitted open diaries.
  Implementation: [views.py](views.py): `TemplateEditorView.dispatch`, `ManagerDiaryView.selected_key`, `ManagerDiaryView.get_diary_keys`.
  Verification: [tests/test_template_editor.py](tests/test_template_editor.py): `TemplateEditorTests.test_named_view_selects_latest_draft_and_supports_url_or_trusted_context`.
  Manager verification: [tests/test_manager_view.py](tests/test_manager_view.py): `ManagerDiaryTests`.
  Personal implementation: [views.py](views.py): `DiaryScopeMixin.dispatch`, `DiaryScopeMixin.get_diary_keys`, `DiaryScopeMixin.selected_key`, `PersonalDiaryView.get`, `PersonalDiaryView.filter_context`, `DiaryOwnerLabelsMixin.get_owner_labels`. [templates/Diary/partials/task_list.html](templates/Diary/partials/task_list.html): `.diary-task-late`, `.diary-task-blocked-late`, `.diary-task-blocked`, `.diary-task-owner`.
  Personal verification: [tests/test_personal_view.py](tests/test_personal_view.py): `PersonalDiaryTests`. [tests/browser_personal_diary.py](tests/browser_personal_diary.py): `PersonalDiaryBrowserTests.test_personal_filters_keyboard_and_layout`.
  Task creation implementation: [views.py](views.py): `TaskCreateView.respond`. [templates/Diary/partials/task_create.html](templates/Diary/partials/task_create.html): `.diary-create`.
  Task creation verification: [tests/test_task_creation.py](tests/test_task_creation.py): `TaskCreationTests`, `TaskCreationConcurrencyTests`. [tests/browser_task_creation.py](tests/browser_task_creation.py): `TaskCreationBrowserTests.test_personal_and_manager_creation_keyboard_mobile_and_overrides`.
  Task detail implementation: [views.py](views.py): `TaskDetailView`. [templates/Diary/partials/task_detail.html](templates/Diary/partials/task_detail.html): `.diary-detail`, `.diary-detail-history`, `.diary-detail-late`, `.diary-detail-blocked-late`, `.diary-detail-blocked`.
  Task detail verification: [tests/test_task_editing.py](tests/test_task_editing.py): `TaskEditingTests`, `TaskEditingConcurrencyTests`, `TaskCompletionMigrationTests`. [tests/browser_task_editing.py](tests/browser_task_editing.py): `TaskEditingBrowserTests.test_personal_dates_manager_template_dates_completion_and_layout`.
  Scope: Existing required interfaces are implemented. Template-to-diary copying is not required.
  Design: [Implemented selectors](../docs/design/diary-v1-remaining-work.md#dv1-019-diary-selectors).
  Requirement: [D6].

- [x] **DV1-020: Personal task API across diaries.**
  Support one permitted diary or all permitted open diaries.
  Include the diary key and name with task results.
  Select only the user's personal tasks and current role-owned tasks by default.
  Keep whole-team tasks behind the explicit option.
  Implementation: [api.py](api.py): `DiaryAPI.personal_tasks`, `DiaryAPI.personal_task_order`, `DiaryInstance.personal_tasks`, `_comparison_date`.
  Verification: [tests/test_personal_view.py](tests/test_personal_view.py): `PersonalDiaryTests.test_api_metadata_scope_ownership_and_lateness_boundary`, `PersonalDiaryTests.test_role_membership_changes_and_manager_personal_selection`.
  Design: [Personal diary implementation](../docs/design/diary-v1-remaining-work.md#dv1-020-dv1-021-and-dv1-049-personal-diary).
  Requirement: [D4], [D6], and [D8].

- [x] **DV1-021: Default personal task view.**
  Open this view by default for logged-in users.
  Without a key, group open tasks by diary name while retaining each diary key.
  With a key, show tasks from that permitted instance only.
  Exclude completed tasks and closed diaries.
  Support the Late, Ready, and Blocked filters used by host links.
  Give Late priority so those filter categories do not overlap.
  Implementation: [views.py](views.py): `PersonalDiaryView.get`, `PersonalDiaryView.filter_context`. [urls.py](urls.py): `urlpatterns`. [templates/Diary/personal_diary.html](templates/Diary/personal_diary.html): `diary_content`. [templates/Diary/partials/personal_diary.html](templates/Diary/partials/personal_diary.html): `.diary-personal`.
  Verification: [tests/test_personal_view.py](tests/test_personal_view.py): `PersonalDiaryTests.test_default_shows_owned_ready_tasks_grouped_by_name_and_key`, `PersonalDiaryTests.test_status_links_preserve_scope_and_counts_do_not_overlap`.
  Design: [Personal diary implementation](../docs/design/diary-v1-remaining-work.md#dv1-020-dv1-021-and-dv1-049-personal-diary).
  Requirement: [D6].

- [x] **DV1-049: Ready tasks by default in My Diary.**
  Show only ready tasks in the default DiaryUser view.
  Provide a “show blocked also” checkbox, clear by default.
  When selected, also show blocked tasks assigned to the user or their groups.
  Determine blocking from incomplete predecessors regardless of their owners.
  Preserve task access rules and predecessor privacy.
  Apply this behavior to one-diary and multiple-diary views from DV1-021.
  Keep the callable API task results unchanged.
  Verify the default, both checkbox states, and predecessors owned by other users or groups.
  Verify that completed predecessors stop blocking and inaccessible tasks remain excluded.
  Document the checkbox styling classes when implementing the control.
  Implementation: [forms.py](forms.py): `PersonalDiaryFilterForm`. [views.py](views.py): `PersonalDiaryView.filter_context`. [templates/Diary/partials/personal_diary.html](templates/Diary/partials/personal_diary.html): `.diary-personal-filter-show-blocked`.
  Verification: [tests/test_personal_view.py](tests/test_personal_view.py): `PersonalDiaryTests.test_checkbox_and_status_filter_combinations`, `PersonalDiaryTests.test_private_entries_and_template_blockers_preserve_state`, `PersonalDiaryTests.test_blockers_owned_by_another_group_and_template_person_visibility`.
  Browser verification: [tests/browser_personal_diary.py](tests/browser_personal_diary.py): `PersonalDiaryBrowserTests.test_personal_filters_keyboard_and_layout`.
  Design: [Personal diary implementation](../docs/design/diary-v1-remaining-work.md#dv1-020-dv1-021-and-dv1-049-personal-diary).
  Requirement: [D6] and [usage guidance](README.md#confirmed-v1-my-diary-display-requirement).

- [x] **DV1-022: Manager full diary list view.**
  Show a permitted diary's date-ordered entries to a DiaryManager.
  Show its name, dates, sources, owners, and task states.
  Apply DV1-052 for the manager's default selection and checkbox filters.
  DiaryUsers use the implemented assigned-task view under DV1-021.
  V1 requires no separate full diary list for DiaryUsers.
  Implementation: [views.py](views.py): `ManagerDiaryView`. [templates/Diary/manager_diary.html](templates/Diary/manager_diary.html): `diary_content`. [templates/Diary/partials/manager_tasks.html](templates/Diary/partials/manager_tasks.html): `.diary-manager-task-list`.
  Verification: [tests/test_manager_view.py](tests/test_manager_view.py): `ManagerDiaryTests.test_default_and_every_filter_combination`, `ManagerDiaryTests.test_current_owners_private_entries_and_escaping`. [tests/browser_manager_diary.py](tests/browser_manager_diary.py): `ManagerDiaryBrowserTests.test_manager_filters_and_layout`.
  Scope: The user confirmed that the personal and manager views satisfy the required V1 task lists.
  Design: [Confirmed task-list scope](../docs/design/diary-v1-remaining-work.md#dv1-022-manager-full-diary-list).
  Requirement: [D6] and [D8].

- [x] **DV1-023: Task details view.**
  Show the task's date rule, due date, owner, dependency state, and completion record when applicable.
  Preserve diary context and apply privacy to related task information.
  Reuse the V1 completion controls.
  Implementation: [api.py](api.py): `DiaryInstance.task`. [views.py](views.py): `TaskDetailView`, `DiaryScopeMixin.task_url`. [templates/Diary/task_detail.html](templates/Diary/task_detail.html): `diary_content`. [templates/Diary/partials/task_detail.html](templates/Diary/partials/task_detail.html): `.diary-detail`, `.diary-detail-rule`, `.diary-detail-history`.
  Verification: [tests/test_task_editing.py](tests/test_task_editing.py): `TaskEditingTests.test_no_missing_migration_and_full_or_embedded_documents`, `TaskEditingTests.test_task_links_keep_host_scope_and_states_refresh_after_edits_and_completion`.
  Design: [Task editing and completion](../docs/design/diary-v1-remaining-work.md#task-editing-and-completion-dv1-023-dv1-032-and-dv1-035-through-dv1-038).
  Requirement: [D6] and [D8].

- [x] **DV1-052: Manager filters for one diary.**
  Provide the checkboxes “include completed tasks”, “exclude blocked tasks”, and “exclude non-late tasks”.
  Keep all three checkboxes clear by default.
  Show all incomplete tasks by default, including blocked tasks and tasks that are not late.
  Let managers inspect completion history and select late tasks only.
  Preserve the selected diary, task privacy, and permitted diary scope.
  Keep the separate DiaryUser default under DV1-049.
  Implementation: [views.py](views.py): `ManagerDiaryView`. [forms.py](forms.py): `ManagerDiaryFilterForm`. [api.py](api.py): `DiaryInstance.read`. [urls.py](urls.py): `urlpatterns`. [templates/Diary/partials/manager_diary.html](templates/Diary/partials/manager_diary.html): `.diary-manager-filters`. [templates/Diary/partials/manager_tasks.html](templates/Diary/partials/manager_tasks.html): `.diary-manager-completion`. [static/Diary/styles/diary.css](static/Diary/styles/diary.css): `.diary-manager-task-late`, `.diary-manager-task-blocked-late`, `.diary-manager-task-blocked`.
  Verification: [tests/test_manager_view.py](tests/test_manager_view.py): `ManagerDiaryTests.test_default_and_every_filter_combination`, `ManagerDiaryTests.test_completion_history_preserves_actor_time_and_due_date`, `ManagerDiaryTests.test_scope_is_required_and_never_taken_from_the_query`. [tests/browser_manager_diary.py](tests/browser_manager_diary.py): `ManagerDiaryBrowserTests.test_manager_filters_and_layout`.
  Completed history is never late or blocked. Selected exclusions apply together and retain the selected permitted diary.
  The usage guide documents all new styling classes and variables.
  Design: [Manager filters for one diary](../docs/design/diary-v1-remaining-work.md#dv1-052-manager-filters-for-one-diary).
  Requirement: [confirmed manager filters](README.md#confirmed-v1-manager-diary-filters) and the user request.

- [x] **DV1-024: Template chooser and named template view.**
  Without `template_name`, list available templates for selection.
  With a name, show its highest version number, including a draft when applicable.
  Do not substitute `DIARY_TEMPLATE_NAME` for the missing view selector.
  Restrict editing to DiaryManagers.
  Implementation: [api.py](api.py): `DiaryAPI.templates`, `DiaryTemplate.editor_data`. [views.py](views.py): `TemplateEditorView.dispatch`, `TemplateEditorView.get`. [urls.py](urls.py): `urlpatterns`. [templates/Diary/template_list.html](templates/Diary/template_list.html): `diary_content`.
  Verification: [tests/test_template_editor.py](tests/test_template_editor.py): `TemplateEditorTests.test_reads_do_not_create_records_and_missing_name_opens_chooser`, `TemplateEditorTests.test_named_view_selects_latest_draft_and_supports_url_or_trusted_context`.
  Requirement: [D6] and [D8].

## Template and entry operations

- [x] **DV1-054: Validated template fixture transfer.**
  Export approved template definitions as Django JSON fixtures.
  Export person ownership by email address. Resolve destination users by email and validate ownership and dependency cycles.
  Permit explicit email overrides when an address differs between deployments.
  Preserve existing diary copies and template history. Roll back the complete import after any failure.
  Implementation: [management/commands/transfer_diary_templates.py](management/commands/transfer_diary_templates.py): `Command.export_fixture`, `Command.export_person_email`, `Command.read_fixture`, `Command.person_mappings`, `Command.import_person_reference`, `Command.import_fixture`, `Command.save_plan`.
  Verification: [tests/test_template_transfer.py](tests/test_template_transfer.py): `TemplateTransferTests`.
  Developer documentation: [Template fixture transfer](README.md#template-fixture-transfer).
  Requirement: The user request for template export and validated import between deployments.

- [x] **DV1-025: Template authoring interface.**
  Support named milestones, reusable date rules, and optional person, role, or whole-team ownership.
  Offer only configured ownership roles.
  Keep template task content under the author's control.
  Implementation: [forms.py](forms.py): `TemplateForm`, `TemplateTaskForm.clean`, `TemplateTaskForm.entry_spec`. [views.py](views.py): `TemplateCreateView`, `TemplateEditorView.post`. [templates/Diary/template_editor.html](templates/Diary/template_editor.html): `diary_content`. [static/Diary/scripts/template_editor.js](static/Diary/scripts/template_editor.js): `initialize`.
  Verification: [tests/test_template_editor.py](tests/test_template_editor.py): `TemplateEditorTests`. [tests/browser_template_editor.py](tests/browser_template_editor.py): `EditorBrowserTests.test_editor`.
  Requirement: [D4], [D5], [D6], and [D9].

- [x] **DV1-026: Versioned template save and approval.**
  Preserve stable entry keys when creating a changed version.
  Approve the resulting version through the DiaryManager's save action.
  Require no separate approval action in V1.
  Keep existing diary copies unchanged.
  Reject stale saves and preserve stable entry keys in each new approved version.
  Implementation: [api.py](api.py): `DiaryTemplate.save_version`, `DiaryTemplateVersion.approve`. [models.py](models.py): `TemplateVersion.clean`, `TemplateEntry.save`, `TemplateEntry.delete`.
  Verification: [tests/test_template_editor.py](tests/test_template_editor.py): `TemplateEditorTests.test_create_and_edit_approve_versions_and_preserve_existing_diaries`, `TemplateEditorTests.test_stale_save_preserves_submitted_data_and_does_not_add_version`, `TemplateRevisionConcurrencyTests`.
  Requirement: [D4] and [D8].

- [x] **DV1-027: Safe template predecessor editor.**
  Exclude the task, its direct successors, its indirect successors, and tasks outside the selected template version.
  Recalculate choices using proposed unsaved links.
  Retain server validation and concurrency protection.
  Implementation: [template_graph.py](template_graph.py): `validate_template_graph`. [forms.py](forms.py): `TemplateTaskFormSet.__init__`, `TemplateTaskFormSet.clean`. [static/Diary/scripts/template_editor.js](static/Diary/scripts/template_editor.js): `refresh`.
  Verification: [tests/test_template_editor.py](tests/test_template_editor.py): `TemplateEditorTests.test_predecessor_choices_exclude_self_and_unsaved_indirect_successors`, `TemplateEditorTests.test_complete_graph_rejects_cycles_self_links_duplicates_and_foreign_predecessors`. [tests/browser_template_editor.py](tests/browser_template_editor.py): `EditorBrowserTests.test_editor`.
  Requirement: [D6].

- [x] **DV1-028: Template-only dependency editing.**
  Reject dependency edits to existing live diary tasks through every V1 interface.
  Keep template changes from propagating into live diaries.
  `DiaryInstance.set_predecessors()` rejects all changes to existing diary graphs, including empty and identical selections.
  Initial template copying finishes before the new diary leaves its creation transaction.
  Existing graphs cannot return to initialization.
  Implementation: [api.py](api.py): `_DependencyAPI.set_predecessors`, `DiaryInstance.create`. [models.py](models.py): `EventCalendar.dependencies_locked`, `EntryDependency.clean`, `EntryDependency.save`, `EntryDependency.delete`. [migrations/0006_freeze_live_dependencies.py](migrations/0006_freeze_live_dependencies.py): `Migration`, `FORWARD_SQL`.
  Verification: [tests/test_live_dependencies.py](tests/test_live_dependencies.py): `LiveDependencyTests`, `LiveDependencyTransactionTests`, `LiveDependencyMigrationTests.test_existing_links_and_completion_records_are_preserved`. [tests/test_concurrency.py](tests/test_concurrency.py): `DependencyConcurrencyTests.test_concurrent_opposite_links_cannot_form_a_cycle`.
  Database guards reject row insertion, replacement, deletion, unlock attempts, and identity changes to referenced tasks.
  Backlog: DFUT-004 records possible controlled editing in a later release.
  Design: [Frozen diary dependencies](../docs/design/diary-v1-remaining-work.md#dv1-028-frozen-diary-dependencies).
  Requirement: [D6] and [D12].

- [x] **DV1-029: Personal entry form.**
  Set the owner to the authenticated user on the server.
  Reject another person or role supplied through a modified request.
  Keep the personal entry outside the template.
  Implementation: [forms.py](forms.py): `TaskCreateForm.__init__`, `TaskCreateForm.clean`, `TaskCreateForm.entry_spec`. [views.py](views.py): `TaskCreateView`. [api.py](api.py): `DiaryInstance.create_task`, `DiaryInstance.add_entry`. [templates/Diary/task_create.html](templates/Diary/task_create.html): `diary_content`. [templates/Diary/partials/task_create.html](templates/Diary/partials/task_create.html): `.diary-create`.
  Verification: [tests/test_task_creation.py](tests/test_task_creation.py): `TaskCreationTests.test_user_creates_self_owned_private_task_and_safe_retry`, `TaskCreationTests.test_user_cannot_forge_owner_or_template_selection`, `TaskCreationTests.test_csrf_and_current_membership_protect_direct_posts`.
  Design: [Task creation implementation](../docs/design/diary-v1-remaining-work.md#dv1-029-dv1-030-and-dv1-033-task-creation).
  Requirement: [D8].

- [x] **DV1-030: DiaryManager assignment form.**
  Allow a DiaryManager to select a person, configured role, or whole-team ownership.
  Verify references through the configured identity system.
  Prevent ordinary users from assigning tasks to another owner.
  Implementation: [forms.py](forms.py): `TaskCreateForm.__init__`, `TaskCreateForm.clean`. [views.py](views.py): `TaskCreateView.respond`, `DjangoOwnerDirectory.person_in_groups`. [api.py](api.py): `DiaryInstance.create_task`, `DiaryInstance.add_entry`. [urls.py](urls.py): `urlpatterns`.
  Verification: [tests/test_task_creation.py](tests/test_task_creation.py): `TaskCreationTests.test_manager_assigns_person_role_and_team_without_revising_template`, `TaskCreationTests.test_permissions_scope_closed_diary_and_read_only_chooser`.
  Design: [Task creation implementation](../docs/design/diary-v1-remaining-work.md#dv1-029-dv1-030-and-dv1-033-task-creation).
  Requirement: [D6] and [D8].

- [x] **DV1-031: Personal-entry privacy.**
  Show personally added tasks only to their owner and permitted DiaryManagers.
  Apply the rule to list reads, details, searches, predecessor choices, and both API interfaces.
  Prevent related-task information from exposing private task content.
  Implementation: [api.py](api.py): `_visible_entries`, `DiaryInstance.read`, `DiaryInstance.active_tasks`, `_DependencyAPI.available_predecessors`. [views.py](views.py): `PersonalDiaryView.get`.
  Verification: [tests/test_personal_view.py](tests/test_personal_view.py): `PersonalDiaryTests.test_private_entries_and_template_blockers_preserve_state`, `PersonalDiaryTests.test_role_membership_changes_and_manager_personal_selection`.
  Task creation implementation: [views.py](views.py): `TaskCreateView.respond`. [templates/Diary/partials/task_create.html](templates/Diary/partials/task_create.html): `.diary-create`.
  Task creation verification: [tests/test_task_creation.py](tests/test_task_creation.py): `TaskCreationTests`, `TaskCreationConcurrencyTests`. [tests/browser_task_creation.py](tests/browser_task_creation.py): `TaskCreationBrowserTests.test_personal_and_manager_creation_keyboard_mobile_and_overrides`.
  Task detail implementation: [views.py](views.py): `TaskDetailView`. [templates/Diary/partials/task_detail.html](templates/Diary/partials/task_detail.html): `.diary-detail`, `.diary-detail-history`, `.diary-detail-late`, `.diary-detail-blocked-late`, `.diary-detail-blocked`.
  Task detail verification: [tests/test_task_editing.py](tests/test_task_editing.py): `TaskEditingTests`, `TaskEditingConcurrencyTests`, `TaskCompletionMigrationTests`. [tests/browser_task_editing.py](tests/browser_task_editing.py): `TaskEditingBrowserTests.test_personal_dates_manager_template_dates_completion_and_layout`.
  Search implementation: [api.py](api.py): `_search_entries`, `DiaryAPI.search_tasks`, `DiaryInstance.search_tasks`.
  HTTP data implementation: [views.py](views.py): `DiaryDataView.dispatch`, `DiaryDataView.get`. [urls.py](urls.py): `urlpatterns`, routes `data-diary`, `data-active`, `data-personal`, `data-search`, `data-task`, and `data-predecessors`.
  Privacy verification: [tests/test_privacy.py](tests/test_privacy.py): `PersonalEntryPrivacyTests`.
  Searches inspect visible names and descriptions only. Private and unknown task lookups return the same unavailable response.
  Related keys and completion comments remain protected. Blocking uses the complete dependency graph.
  HTTP reads repeat authentication and trusted scope checks. Responses prohibit storage and vary by session cookie.
  No privacy implementation remains for these V1 interfaces.
  Design: [Personal diary privacy boundary](../docs/design/diary-v1-remaining-work.md#dv1-020-dv1-021-and-dv1-049-personal-diary).
  Requirement: [D8].

- [x] **DV1-032: Manager-only edits to template-sourced tasks.**
  Restrict permitted edits to DiaryManagers.
  Keep the source template and other diary instances unchanged.
  Preserve the V1 ban on live dependency editing and milestone changes.
  The approved edit is a due-date override for the selected diary task.
  DiaryUsers can edit only self-owned diary additions.
  DiaryManagers can also edit dates on copied template tasks and other permitted diary tasks.
  Keep names, descriptions, milestones, and dependency links unchanged.
  Ownership changes require explicit orphan recovery under DV1-040.
  V1 does not warn managers when a due-date change causes a conflict.
  Implementation: [models.py](models.py): `CalendarEntry.due_date_override`, `CalendarEntry.open_due_date`, `CalendarEntry.revision`. [api.py](api.py): `DiaryInstance.update_due_date`, `DiaryInstance._can_edit_date`. [forms.py](forms.py): `TaskDueDateForm`. [views.py](views.py): `TaskDetailView.respond`.
  Verification: [tests/test_task_editing.py](tests/test_task_editing.py): `TaskEditingTests.test_user_edits_personal_due_date_without_changing_original_rule_or_other_records`, `TaskEditingTests.test_user_cannot_edit_copied_group_team_or_other_person_dates`, `TaskEditingTests.test_manager_changes_copied_due_date_without_template_revision_or_warning_service`, `TaskEditingTests.test_stale_invalid_and_completed_due_date_changes_are_rejected`, `TaskEditingConcurrencyTests`.
  The guide records the conflict-warning limit. DV1-028 now enforces the callable dependency restriction.
  Design: [Task editing and completion](../docs/design/diary-v1-remaining-work.md#task-editing-and-completion-dv1-023-dv1-032-and-dv1-035-through-dv1-038).
  Requirement: [D4], [D8], and [D12].

- [x] **DV1-033: Combined diary entry and template addition.**
  Offer the DiaryManager choice “Add to template for future diaries”, initially off.
  Show the reusable date rule and owner choice before saving.
  Require explicit selection of a reusable rule before adding a one-time task to the template.
  Save one diary entry and one approved template addition together with a shared entry key.
  Reject duplicate requests without creating another entry.
  Keep other existing diaries unchanged.
  Implementation: [api.py](api.py): `DiaryInstance.create_task`, `DiaryTemplate.save_version`. [forms.py](forms.py): `TaskCreateForm`, `ReusableTaskRuleForm`. [views.py](views.py): `TaskCreateView.respond`. [templates/Diary/partials/task_create.html](templates/Diary/partials/task_create.html): `.diary-create-future`.
  Verification: [tests/test_task_creation.py](tests/test_task_creation.py): `TaskCreationTests.test_combined_save_preserves_snapshots_graph_and_future_creation`, `TaskCreationTests.test_future_rule_is_explicit_and_validated_before_any_write`, `TaskCreationTests.test_stale_template_and_storage_failure_roll_back_both_additions`, `TaskCreationTests.test_milestone_rules_and_latest_revision_are_preserved`, `TaskCreationConcurrencyTests`.
  Browser verification: [tests/browser_task_creation.py](tests/browser_task_creation.py): `TaskCreationBrowserTests.test_personal_and_manager_creation_keyboard_mobile_and_overrides`.
  Design: [Task creation implementation](../docs/design/diary-v1-remaining-work.md#dv1-029-dv1-030-and-dv1-033-task-creation).
  Requirement: [D4] and [D8].

## Completion operations

- [x] **DV1-035: Blocking predecessor inspection.**
  List all open predecessors in the blocking chain before task completion.
  Include indirect blockers and preserve task visibility rules.
  Represent inaccessible blockers with one generic marker, without private names, dates, owners, keys, or counts.
  Implementation: [api.py](api.py): `DiaryInstance._open_blockers`, `DiaryInstance.task`. [templates/Diary/partials/task_detail.html](templates/Diary/partials/task_detail.html): `.diary-detail-blockers`, `.diary-detail-private-blocker`.
  Verification: [tests/test_task_editing.py](tests/test_task_editing.py): `TaskEditingTests.test_normal_completion_rechecks_indirect_and_direct_blockers`, `TaskEditingTests.test_private_blockers_and_completion_audit_do_not_disclose_private_target_keys`.
  Design: [Task editing and completion](../docs/design/diary-v1-remaining-work.md#task-editing-and-completion-dv1-023-dv1-032-and-dv1-035-through-dv1-038).
  Requirement: [D6] and [D8].

- [x] **DV1-036: Normal task completion.**
  Provide “Complete” to permitted users for accessible tasks.
  Save completion only when the blocking predecessor list is empty.
  Check the condition again during the save.
  Record one completion per task and preserve its due date at completion.
  Reject changes to a closed diary.
  Implementation: [api.py](api.py): `DiaryInstance.complete`. [models.py](models.py): `CalendarEntry.clean`. [forms.py](forms.py): `TaskCompletionForm`. [templates/Diary/partials/task_detail.html](templates/Diary/partials/task_detail.html): `.diary-detail-complete`.
  Verification: [tests/test_task_editing.py](tests/test_task_editing.py): `TaskEditingTests.test_normal_completion_saves_effective_due_date_and_is_idempotent`, `TaskEditingTests.test_normal_completion_rechecks_indirect_and_direct_blockers`, `TaskEditingConcurrencyTests`.
  Design: [Task editing and completion](../docs/design/diary-v1-remaining-work.md#task-editing-and-completion-dv1-023-dv1-032-and-dv1-035-through-dv1-038).
  Requirement: [D6].

- [x] **DV1-037: DiaryManager “Close all” operation.**
  Complete the open blocking chain and selected task together.
  Record the manager, completion time, and due date for each newly completed task.
  Add an explanatory comment to each forced predecessor completion.
  Preserve existing completion records and all dependency links.
  Reject ordinary-user requests and concurrent changes that invalidate the operation.
  Implementation: [api.py](api.py): `DiaryInstance.complete`, `DiaryInstance._open_blockers`. [templates/Diary/partials/task_detail.html](templates/Diary/partials/task_detail.html): `.diary-detail-close-all`.
  Verification: [tests/test_task_editing.py](tests/test_task_editing.py): `TaskEditingTests.test_close_all_records_comments_and_keeps_existing_completions_and_links`, `TaskEditingTests.test_forced_completion_rejects_users_and_stale_predecessor_inspection`, `TaskEditingTests.test_failure_during_close_all_rolls_back_every_completion`, `TaskEditingConcurrencyTests.test_close_all_and_predecessor_date_edit_reject_one_stale_operation`.
  Design: [Task editing and completion](../docs/design/diary-v1-remaining-work.md#task-editing-and-completion-dv1-023-dv1-032-and-dv1-035-through-dv1-038).
  Requirement: [D6].

- [x] **DV1-038: Persistent completion comments and history display.**
  Add storage for explanatory forced-completion comments and the selected task reference.
  Include any necessary PostgreSQL migration and API result changes.
  Display the recorded action, caller, time, and due date in task details.
  Store the action, explanatory comment, selected task key, actor, time, and effective due date.
  Implementation: [models.py](models.py): `CalendarEntry.completion_action`, `CalendarEntry.completion_comment`, `CalendarEntry.completion_target_key`. [migrations/0005_task_dates_and_completion.py](migrations/0005_task_dates_and_completion.py): `Migration`. [api.py](api.py): `_visible_entries`, `DiaryInstance.complete`. [templates/Diary/partials/task_detail.html](templates/Diary/partials/task_detail.html): `.diary-detail-history`.
  Verification: [tests/test_task_editing.py](tests/test_task_editing.py): `TaskEditingTests.test_close_all_records_comments_and_keeps_existing_completions_and_links`, `TaskEditingTests.test_private_blockers_and_completion_audit_do_not_disclose_private_target_keys`, `TaskCompletionMigrationTests.test_existing_dates_and_completion_records_remain_unchanged`.
  Design: [Task editing and completion](../docs/design/diary-v1-remaining-work.md#task-editing-and-completion-dv1-023-dv1-032-and-dv1-035-through-dv1-038).
  Requirement: [D6].

## Presentation and release checks

- [x] **DV1-055: Graphical template view for Diary Managers.**
  Show template tasks as boxes, completion dependencies as solid arrows, and task or milestone date relations as dashed arrows.
  Show referenced host milestones as shared diamonds; omit milestones with no date relations.
  Position tasks and milestones according to signed date offsets and task-relative chains. Zero offsets enter the top of the task, while retaining the actual same-day due date.
  When a completion dependency and date relation connect the same task pair, display only the solid dependency arrow while retaining the date relation for positioning.
  Reduce crossings with connected subgraphs and routing lanes. Provide zoom, pan, fit, keyboard access to task forms, and creation/subgraph ordering of task choices.
  Preserve the existing forms without JavaScript and the host styling integration.
  Implementation: [template editor script](static/Diary/scripts/template_editor.js): `taskGraph`, `arrangeGraph`, `positionGraphDates`, and `orderedTaskChoices`.
  Verification: [graph browser tests](tests/browser_template_graph.py) and [template editor tests](tests/test_template_editor.py).
  Documentation: [View task connections](USER_GUIDE.md#view-task-connections) and [template page styling](README.md#template-page-styling).
  Boundary: This is a view with links to editing forms and relative date positioning, rather than a calendar-day scale. Direct graphical editing remains under DFUT-011 in the [repository TODO](../TODO.md#diary-feature-backlog).

- [x] **DV1-039: Production task highlighting.**
  Give Late tasks a red shadowed border.
  Give Blocked tasks an amber shadowed border when a direct predecessor is late.
  Give red priority when the task itself is late.
  Give other Blocked tasks a dashed border.
  Keep text labels and update all task views after state changes.
  Implementation: [static/Diary/styles/diary.css](static/Diary/styles/diary.css): `.diary-manager-task-late`, `.diary-manager-task-blocked-late`, `.diary-manager-task-blocked`. [views.py](views.py): `ManagerDiaryView.get_tasks`.
  Verification: [tests/test_manager_view.py](tests/test_manager_view.py): `ManagerDiaryTests.test_highlights_and_fragment_use_stable_styling_classes`. [tests/browser_manager_diary.py](tests/browser_manager_diary.py): `ManagerDiaryBrowserTests.test_manager_filters_and_layout`.
  Personal implementation: [views.py](views.py): `DiaryScopeMixin.dispatch`, `DiaryScopeMixin.get_diary_keys`, `DiaryScopeMixin.selected_key`, `PersonalDiaryView.get`, `PersonalDiaryView.filter_context`, `DiaryOwnerLabelsMixin.get_owner_labels`. [templates/Diary/partials/task_list.html](templates/Diary/partials/task_list.html): `.diary-task-late`, `.diary-task-blocked-late`, `.diary-task-blocked`, `.diary-task-owner`.
  Personal verification: [tests/test_personal_view.py](tests/test_personal_view.py): `PersonalDiaryTests`. [tests/browser_personal_diary.py](tests/browser_personal_diary.py): `PersonalDiaryBrowserTests.test_personal_filters_keyboard_and_layout`.
  Task detail implementation: [views.py](views.py): `TaskDetailView`. [templates/Diary/partials/task_detail.html](templates/Diary/partials/task_detail.html): `.diary-detail`, `.diary-detail-history`, `.diary-detail-late`, `.diary-detail-blocked-late`, `.diary-detail-blocked`.
  Task detail verification: [tests/test_task_editing.py](tests/test_task_editing.py): `TaskEditingTests`, `TaskEditingConcurrencyTests`, `TaskCompletionMigrationTests`. [tests/browser_task_editing.py](tests/browser_task_editing.py): `TaskEditingBrowserTests.test_personal_dates_manager_template_dates_completion_and_layout`.
  Scope: Existing required interfaces are implemented. Template-to-diary copying is not required.
  Design: [Implemented pages and styling](../docs/design/diary-v1-remaining-work.md#dv1-041-pages-and-styling).
  Requirement: [D6].

- [x] **DV1-040: Ownership display and membership handling.**
  Show person names, current role members, and “Whole team” as appropriate.
  Keep role references rather than copying a fixed member list.
  Preserve ownership when membership changes.
  Apply empty-group warnings at the validation points in section 9.
  Put orphaned template tasks first in the manager list. Preserve the normal ordering within each task category.
  Let managers leave these tasks unresolved or assign a replacement through the existing task editor.
  Limit person replacements to active members of `DIARY_USER`. Also permit authorized ownership groups and whole-team ownership.
  Partial implementation: [views.py](views.py): `ManagerDiaryView.get_owner_labels`, `ManagerDiaryView.get_tasks`. [templates/Diary/partials/manager_tasks.html](templates/Diary/partials/manager_tasks.html): `.diary-manager-task-owner`, `.diary-manager-owner-members`.
  Verification: [tests/test_manager_view.py](tests/test_manager_view.py): `ManagerDiaryTests.test_current_owners_private_entries_and_escaping`.
  Personal implementation: [views.py](views.py): `DiaryScopeMixin.dispatch`, `DiaryScopeMixin.get_diary_keys`, `DiaryScopeMixin.selected_key`, `PersonalDiaryView.get`, `PersonalDiaryView.filter_context`, `DiaryOwnerLabelsMixin.get_owner_labels`. [templates/Diary/partials/task_list.html](templates/Diary/partials/task_list.html): `.diary-task-late`, `.diary-task-blocked-late`, `.diary-task-blocked`, `.diary-task-owner`.
  Personal verification: [tests/test_personal_view.py](tests/test_personal_view.py): `PersonalDiaryTests`. [tests/browser_personal_diary.py](tests/browser_personal_diary.py): `PersonalDiaryBrowserTests.test_personal_filters_keyboard_and_layout`.
  Task detail implementation: [views.py](views.py): `TaskDetailView`. [templates/Diary/partials/task_detail.html](templates/Diary/partials/task_detail.html): `.diary-detail`, `.diary-detail-history`, `.diary-detail-late`, `.diary-detail-blocked-late`, `.diary-detail-blocked`.
  Task detail verification: [tests/test_task_editing.py](tests/test_task_editing.py): `TaskEditingTests`, `TaskEditingConcurrencyTests`, `TaskCompletionMigrationTests`. [tests/browser_task_editing.py](tests/browser_task_editing.py): `TaskEditingBrowserTests.test_personal_dates_manager_template_dates_completion_and_layout`.
  API implementation: [ownership.py](ownership.py): `orphaned_entry_keys`. [api.py](api.py): `DiaryInstance.reassign_task`.
  API verification: [tests/test_ownership_recovery.py](tests/test_ownership_recovery.py): `OwnershipRecoveryTests`.
  Recovery implementation: [views.py](views.py): `ManagerDiaryView.get_tasks`, `ManagerDiaryView.task_order`, `TaskDetailView.respond`, `DjangoOwnerDirectory.person_in_groups`. [forms.py](forms.py): `TaskOwnerRecoveryForm`.
  Recovery templates: [templates/Diary/partials/manager_tasks.html](templates/Diary/partials/manager_tasks.html): `.diary-manager-orphaned`. [templates/Diary/partials/task_detail.html](templates/Diary/partials/task_detail.html): `.diary-recovery-form`.
  Editor verification: [tests/test_ownership_recovery.py](tests/test_ownership_recovery.py): `ManagerOwnershipRecoveryTests`.
  Browser verification: [tests/browser_ownership_recovery.py](tests/browser_ownership_recovery.py): `OwnershipRecoveryBrowserTests.test_existing_editor_reassigns_orphaned_template_task`.
  Recovery design: [Ownership recovery in the existing editor](../docs/design/diary-v1-remaining-work.md#dv1-040-ownership-recovery-in-the-existing-editor).
  Design: [Manager diary implementation](../docs/design/diary-v1-remaining-work.md#dv1-052-manager-filters-for-one-diary).
  Requirement: [D6] and [D9].

- [x] **DV1-041: Complete pages, fragments, and styling interface.**
  Save navigation: [views.py](views.py): `TemplateEditorView.get_success_url` preserves package form handling for host views.
  Verification: [test_template_editor.py](tests/test_template_editor.py): `TemplateEditorTests.test_host_success_hook_delegates_all_form_processing`.
  Compact manager filters: [manager_diary.html](templates/Diary/partials/manager_diary.html): `.diary-manager-filter-controls` and `.diary-manager-filter-actions`.
  Styling: [diary.css](static/Diary/styles/diary.css): `.diary-manager-filter-group`, `.diary-manager-filter-label`, and `.diary-manager-filter-help`.
  Verification: [test_host_embedding.py](tests/test_host_embedding.py): `HostEmbeddingTests.test_manager_filter_actions_stay_inside_panel`.
  Host embedding: [HOST_EMBEDDING.md](HOST_EMBEDDING.md). Package pages accept `diary_base_template` and `diary_ui`.
  Implementation: [views.py](views.py): `DiaryScopeMixin.task_url`, `PersonalDiaryView.filter_context`, `TemplateEditorView.get`, and `TemplateEditorView.render_editor`.
  Shared forms: [selection_forms.html](templates/Diary/partials/selection_forms.html): `.diary-selection-form` and `.diary-selection-kind`.
  Hidden fields: [form_fields.html](templates/Diary/partials/form_fields.html): `.diary-host-field`.
  Verification: [test_host_embedding.py](tests/test_host_embedding.py): `HostEmbeddingTests`.
  Use a complete base document for each routed page and reusable fragments for embedded content.
  Give visible components, controls, content roles, and states stable `diary-` classes within `.diary`.
  Avoid inline presentation rules and styling dependencies on IDs, text, tags, or element positions.
  Document every class and CSS variable in `README.md`.
  Verify keyboard access, text state labels, narrow screens, and host overrides.
  Implementation: [forms.py](forms.py): `StyledForm.__init__`, `ManagerDiaryFilterForm.__init__`. [templates/Diary/partials/manager_diary.html](templates/Diary/partials/manager_diary.html): `.diary-manager`. [templates/Diary/template_editor.html](templates/Diary/template_editor.html): `diary_content`. [templates/Diary/partials/template_editor.html](templates/Diary/partials/template_editor.html): `.diary-template-editor`. [static/Diary/styles/diary.css](static/Diary/styles/diary.css): `.diary-template-field`.
  Verification: [tests/test_styling.py](tests/test_styling.py): `DiaryStyleOverrideTests`. [tests/browser_template_editor.py](tests/browser_template_editor.py): `EditorBrowserTests.test_editor`.
  Manager verification: [tests/test_manager_view.py](tests/test_manager_view.py): `ManagerDiaryTests`.
  Personal implementation: [views.py](views.py): `DiaryScopeMixin.dispatch`, `DiaryScopeMixin.get_diary_keys`, `DiaryScopeMixin.selected_key`, `PersonalDiaryView.get`, `PersonalDiaryView.filter_context`, `DiaryOwnerLabelsMixin.get_owner_labels`. [templates/Diary/partials/task_list.html](templates/Diary/partials/task_list.html): `.diary-task-late`, `.diary-task-blocked-late`, `.diary-task-blocked`, `.diary-task-owner`.
  Personal verification: [tests/test_personal_view.py](tests/test_personal_view.py): `PersonalDiaryTests`. [tests/browser_personal_diary.py](tests/browser_personal_diary.py): `PersonalDiaryBrowserTests.test_personal_filters_keyboard_and_layout`.
  Task creation implementation: [views.py](views.py): `TaskCreateView.respond`. [templates/Diary/partials/task_create.html](templates/Diary/partials/task_create.html): `.diary-create`.
  Task creation verification: [tests/test_task_creation.py](tests/test_task_creation.py): `TaskCreationTests`, `TaskCreationConcurrencyTests`. [tests/browser_task_creation.py](tests/browser_task_creation.py): `TaskCreationBrowserTests.test_personal_and_manager_creation_keyboard_mobile_and_overrides`.
  Task detail implementation: [views.py](views.py): `TaskDetailView`. [templates/Diary/partials/task_detail.html](templates/Diary/partials/task_detail.html): `.diary-detail`, `.diary-detail-history`, `.diary-detail-late`, `.diary-detail-blocked-late`, `.diary-detail-blocked`.
  Task detail verification: [tests/test_task_editing.py](tests/test_task_editing.py): `TaskEditingTests`, `TaskEditingConcurrencyTests`, `TaskCompletionMigrationTests`. [tests/browser_task_editing.py](tests/browser_task_editing.py): `TaskEditingBrowserTests.test_personal_dates_manager_template_dates_completion_and_layout`.
  Scope: Existing required interfaces are implemented. Template-to-diary copying is not required.
  Design: [Implemented pages and styling](../docs/design/diary-v1-remaining-work.md#dv1-041-pages-and-styling).
  Requirement: [D6].

- [x] **DV1-042: Empty states and invalid selections.**
  Handle empty personal lists, unknown keys, unavailable templates, invalid selectors, and denied access explicitly.
  Preserve the selected diary context without silently choosing another instance.
  Keep all reads free from diary creation or template-copy actions.
  Do not require a host current-event attribute.
  Implementation: [views.py](views.py): `TemplateEditorView.dispatch`, `TemplateEditorView.get`, `ManagerDiaryView.get`.
  Verification: [tests/test_template_editor.py](tests/test_template_editor.py): `TemplateEditorTests.test_reads_do_not_create_records_and_missing_name_opens_chooser`, `TemplateEditorTests.test_named_view_selects_latest_draft_and_supports_url_or_trusted_context`.
  Manager verification: [tests/test_manager_view.py](tests/test_manager_view.py): `ManagerDiaryTests`.
  Personal implementation: [views.py](views.py): `DiaryScopeMixin.dispatch`, `DiaryScopeMixin.get_diary_keys`, `DiaryScopeMixin.selected_key`, `PersonalDiaryView.get`, `PersonalDiaryView.filter_context`, `DiaryOwnerLabelsMixin.get_owner_labels`. [templates/Diary/partials/task_list.html](templates/Diary/partials/task_list.html): `.diary-task-late`, `.diary-task-blocked-late`, `.diary-task-blocked`, `.diary-task-owner`.
  Personal verification: [tests/test_personal_view.py](tests/test_personal_view.py): `PersonalDiaryTests`. [tests/browser_personal_diary.py](tests/browser_personal_diary.py): `PersonalDiaryBrowserTests.test_personal_filters_keyboard_and_layout`.
  Task creation implementation: [views.py](views.py): `TaskCreateView.respond`. [templates/Diary/partials/task_create.html](templates/Diary/partials/task_create.html): `.diary-create`.
  Task creation verification: [tests/test_task_creation.py](tests/test_task_creation.py): `TaskCreationTests`, `TaskCreationConcurrencyTests`. [tests/browser_task_creation.py](tests/browser_task_creation.py): `TaskCreationBrowserTests.test_personal_and_manager_creation_keyboard_mobile_and_overrides`.
  Task detail implementation: [views.py](views.py): `TaskDetailView`. [templates/Diary/partials/task_detail.html](templates/Diary/partials/task_detail.html): `.diary-detail`, `.diary-detail-history`, `.diary-detail-late`, `.diary-detail-blocked-late`, `.diary-detail-blocked`.
  Task detail verification: [tests/test_task_editing.py](tests/test_task_editing.py): `TaskEditingTests`, `TaskEditingConcurrencyTests`, `TaskCompletionMigrationTests`. [tests/browser_task_editing.py](tests/browser_task_editing.py): `TaskEditingBrowserTests.test_personal_dates_manager_template_dates_completion_and_layout`.
  Scope: Existing required interfaces are implemented. Template-to-diary copying is not required.
  Design: [Implemented empty and error states](../docs/design/diary-v1-remaining-work.md#dv1-042-empty-and-error-states).
  Requirement: [D4], [D6], and [D8].

- [x] **DV1-043: Enforce the V1 milestone-change boundary.**
  Keep post-creation milestone editing outside supported V1 workflows.
  Do not expose the preview milestone editor as an approved V1 page.
  Reject the callable mutation after permission, scope, and closure checks.
  Milestone changes and their impact review belong in V2.
  Implementation: [api.py](api.py): `DiaryInstance.set_milestone_dates`. [models.py](models.py): `CalendarMilestone.clean`, `CalendarMilestone.save`, `CalendarMilestone.delete`.
  Database implementation: [migrations/0007_freeze_live_milestones.py](migrations/0007_freeze_live_milestones.py): `Migration`, `FORWARD_SQL`.
  Verification: [tests/test_live_milestones.py](tests/test_live_milestones.py): `LiveMilestoneTests`.
  Design: [Implemented milestone boundary](../docs/design/diary-v1-remaining-work.md#dv1-043-implemented-milestone-boundary).
  Requirement: [D7].

- [ ] **DV1-057: Review and clean up the V1 user interface.**
  Review the user and manager journeys for diary selection, task lists and filters, task creation and editing, ownership, completion, notes, template application, and the template graph.
  Make labels, terminology, help, validation messages, navigation, and actions consistent.
  Correct field and date-input alignment, spacing, wrapping, overflow, and redundant content.
  Clearly distinguish completion predecessors from date sources, and diary-only edits from changes to future templates.
  Review complex graph readability, milestone and task labels, connector meaning, zero offsets, and zoom/pan controls.
  Check desktop and narrow layouts, keyboard access, focus, accessible labels, empty/error states, and forms without JavaScript.
  Preserve host styling hooks, permissions, privacy, and server-side validation throughout the cleanup.
  Completion: Record the review, resolve the agreed V1 issues, update affected help pages, and record browser verification with screenshots or equivalent evidence.
  Status: Open. Existing individual UI fixes do not complete this review.
  Template editor review implemented: graph-first navigation, a compact responsive task dialog with Save task / Cancel, a separate Save template action, and a collapsed searchable task finder with removal/restoration access.
  Navigator space review implemented: title/description settings and help moved into dialogs; Settings opens automatically for creation and stays closed during edits. Settings has draft Save settings / Cancel actions. The toolbar places Add task before a vertical separator and zoom controls, with Settings / Help aligned right. Zoom affects only scrollable content inside the fixed-size panel.
  Date controls combine task due dates and milestone dates into one source picker with a shared signed offset, including zero. Annual rules remain separate. Tasks retain ownership and completion; milestones remain host-supplied dates. Existing API date kinds remain supported.
  Implementation: [template editor](templates/Diary/partials/template_editor.html), [editor script](static/Diary/scripts/template_editor.js), [styles](static/Diary/styles/diary.css), and [date rule forms](forms.py).
  Verification: [graph and dialog browser checks](tests/browser_template_graph.py), [template creation browser checks](tests/browser_template_editor.py), and [server / no-JavaScript checks](tests/test_template_editor.py).
  Remaining: Complete the review of the other user and manager journeys listed above.
  Related: DV1-041, DV1-042, DV1-045, DV1-055, and DV1-056.

- [ ] **DV1-044: Regression and concurrency verification.**
  Scope: Test cases and verification only. This item adds no product interface.
  Cover privacy, configured groups, membership checks, selectors, template saves, task additions, and completion operations.
  Verify transaction failures, repeated requests, and races between completion, diary closure, and permitted edits.
  Run database tests only against a separate PostgreSQL test database.
  Verify installation without host business application models.
  Partial implementation: [tests/test_manager_view.py](tests/test_manager_view.py): `ManagerDiaryTests`. [tests/browser_manager_diary.py](tests/browser_manager_diary.py): `ManagerDiaryBrowserTests.test_manager_filters_and_layout`. [tests/test_template_editor.py](tests/test_template_editor.py): `TemplateRevisionConcurrencyTests`, `TemplateEditorTests`. [tests/browser_template_editor.py](tests/browser_template_editor.py): `EditorBrowserTests.test_editor`.
  Manager verification: [tests/test_manager_view.py](tests/test_manager_view.py): `ManagerDiaryTests`.
  Personal implementation: [views.py](views.py): `DiaryScopeMixin.dispatch`, `DiaryScopeMixin.get_diary_keys`, `DiaryScopeMixin.selected_key`, `PersonalDiaryView.get`, `PersonalDiaryView.filter_context`, `DiaryOwnerLabelsMixin.get_owner_labels`. [templates/Diary/partials/task_list.html](templates/Diary/partials/task_list.html): `.diary-task-late`, `.diary-task-blocked-late`, `.diary-task-blocked`, `.diary-task-owner`.
  Personal verification: [tests/test_personal_view.py](tests/test_personal_view.py): `PersonalDiaryTests`. [tests/browser_personal_diary.py](tests/browser_personal_diary.py): `PersonalDiaryBrowserTests.test_personal_filters_keyboard_and_layout`.
  Task creation implementation: [views.py](views.py): `TaskCreateView.respond`. [templates/Diary/partials/task_create.html](templates/Diary/partials/task_create.html): `.diary-create`.
  Task creation verification: [tests/test_task_creation.py](tests/test_task_creation.py): `TaskCreationTests`, `TaskCreationConcurrencyTests`. [tests/browser_task_creation.py](tests/browser_task_creation.py): `TaskCreationBrowserTests.test_personal_and_manager_creation_keyboard_mobile_and_overrides`.
  Task detail implementation: [views.py](views.py): `TaskDetailView`. [templates/Diary/partials/task_detail.html](templates/Diary/partials/task_detail.html): `.diary-detail`, `.diary-detail-history`, `.diary-detail-late`, `.diary-detail-blocked-late`, `.diary-detail-blocked`.
  Task detail verification: [tests/test_task_editing.py](tests/test_task_editing.py): `TaskEditingTests`, `TaskEditingConcurrencyTests`, `TaskCompletionMigrationTests`. [tests/browser_task_editing.py](tests/browser_task_editing.py): `TaskEditingBrowserTests.test_personal_dates_manager_template_dates_completion_and_layout`.
  Transactions provide rollback. The shared diary row lock serializes supported writes to the same diary.
  Existing verification: [tests/test_task_editing.py](tests/test_task_editing.py): `TaskEditingConcurrencyTests.test_date_edit_and_completion_use_one_consistent_task_revision`, `TaskEditingConcurrencyTests.test_diary_closure_and_completion_leave_no_write_after_closure`.
  Membership changes use separate user and group records. The diary lock does not prevent those changes.
  A membership removal after an eligibility check can leave the assigned task orphaned again.
  This item records verification work, not a demonstrated transaction defect or missing application feature.
  Remaining: Test ownership recovery with simultaneous membership changes. Verify that recovery shares the existing completion and closure lock behavior.
  Design: [Remaining work for DV1-044](../docs/design/diary-v1-remaining-work.md#dv1-044-remaining-verification).
  Requirement: [D4], [D6], [D8], and [D9].

- [ ] **DV1-045: Release documentation and deployment checks.**
  Scope: English only for V1. Localization is not required.
  Schedule: Perform these checks when needed for release. This item does not identify an unimplemented application feature.
  Update API signatures, view inputs, settings, migration instructions, and styling documentation for the final implementation.
  Preserve the documented runtime warning limit for ownership group changes.
  Check all V1 items against their completion conditions before release.
  Record the language review limits without claiming unverified ASD-STE100 compliance.
  Partial documentation: [USER_GUIDE.md](USER_GUIDE.md): `Start using Diary`, `Find your tasks`, `Change a due date`, `Complete a task`, and manager procedures.
  The web guide includes privacy, shared completion, template version behavior, recovery instructions, and the V1 date-conflict warning limit.
  Verification: Manual comparison with current forms, page templates, task permissions, and existing implementation evidence.
  Documentation only. This change adds no executable symbols or application tests.
  Remaining: Complete final release checks, deployment verification, and the full Issue 9 dictionary and technical-name review.
  Requirement: [D4], [D6], [D9], and [usage documentation](README.md).

## Confirmed decisions for specific items

These entries record decisions for specific implementation items.
They do not reopen the confirmed V1 decisions.

| Identifier | Decision | Affected items | Documentation |
| --- | --- | --- | --- |
| DEC-001 | Resolved. Reject conflicting URL and context selectors with HTTP 400 and a WARNING log message. Neither input takes priority. | DV1-019 | [Full developer guide](README.md#dec-001-conflicting-selectors). |
| DEC-002 | Resolved. Managers can edit template-created task due dates and orphaned-task ownership through the existing task editor. Other task content stays unchanged. | DV1-032, DV1-040 | [Full developer guide](README.md#dec-002-v1-edits-to-template-created-tasks). |
| DEC-003 | Closed. Copying existing template tasks into existing diaries is not required. | DV1-034, not required | [Removed requirement](#removed-requirement-dv1-034). |
| DEC-004 | Implemented with one generic marker for inaccessible open predecessors. No private content, identifiers, or count appear. | DV1-035 | [Task editing design](../docs/design/diary-v1-remaining-work.md#task-editing-and-completion-dv1-023-dv1-032-and-dv1-035-through-dv1-038). |
| DEC-005 | Resolved. Put orphaned template tasks first in the manager list. Allow unresolved ownership or explicit reassignment through the existing editor. | DV1-040 | Choose a DiaryUser, authorized ownership group, or Whole team. No dedicated popup is required. |

## Outside V1

The following work is not a generic Diary V1 requirement:

- Milestone date changes and their impact review belong in V2.
- V2 must review the V1 force completion behavior.
- Controlled dependency editing in existing diaries is a backlog proposal under DFUT-004, without an assigned release.
- Multiple sign-offs are outside V1.
- Reminders have no confirmed release number.
- A month display, exports, and broad retrospective template replacement are not approved V1 requirements.
- A separate template approval step is outside V1.
- Template task content is application data.
- Diary has no public view.
- Finer-grained permissions may become an optional feature in a later version, outside V1.

## Removed requirement: DV1-034

**DV1-034: Copy an existing template task into an active diary — not required.**

The user confirmed that this feature is not required.
Its identifier remains here to keep the implementation record stable.
It is removed from the required work, rather than marked as an implemented feature.
No future release is assigned to it.
DEC-003 is closed because its missing-date and missing-predecessor questions applied only to this feature.

DV1-033 remains implemented: a manager can create a new diary task and add it to a template for future diaries.
That operation keeps other existing diaries unchanged.
This is a documentation-only scope record. It adds no executable symbols or verification.

## Future requirements

The complete DFUT list is maintained in the [repository TODO](../TODO.md#diary-feature-backlog).
DFUT identifiers and existing statuses are retained there; requirements are not duplicated here.
The implemented graphical view is recorded under DV1-055, and task-relative dates under DV1-056.
The remaining full graphical editor stays in the backlog as DFUT-011.
DFUT-007 signals are implemented in version 0.1.10.1; the contract and verification
are recorded in the repository TODO and [Task change signals](README.md#task-change-signals).

## Review limits

DV1-054 passed 225 standalone tests and 226 host tests against separate PostgreSQL databases.
Its 11 transfer tests cover fixture imports, email ownership, cycles, dry runs, repeated imports, revision consent, and complete rollback.
Person assignments use email addresses in exported fixtures. The command resolves local user references during import.
User Management requires no changes. No database migration or static collection is needed for this command.
The full developer guide documents the command and its transfer limits.
DFUT-005 records installable Python packaging as post-V1 work. No packaging implementation or release number is assigned.
The full Issue 9 dictionary and technical-name review remains incomplete.

DEC-001 and DEC-002 now identify confirmed behavior in the full developer guide.
The selector logging change passed 28 manager and template tests against a separate PostgreSQL database.
Conflict tests verify HTTP 400, WARNING records, selector names, and omission of submitted selector values.
The change adds no database migration or deployed service change.
DV1-044 remains test work. DV1-045 requires English documentation only, with no current localization requirement.

DEC-005 is resolved through the existing manager list and task editor.
The standalone configuration passed 215 tests, including the ownership recovery Chrome test.
The host configuration passed 215 tests, including the Garage Sale diary-key integration test.
Both configurations used separate PostgreSQL test databases.
The browser check covers orphan priority, existing-editor navigation, person choices, whole-team reassignment, and phone layout.
DV1-044 retains checks for simultaneous membership changes, completion, and closure through separate database connections.
No application migration or deployment occurred for this change. No additional migration is required.

The resumed edits implement the DV1-043 milestone boundary and template-only predecessor choices.
The standalone configuration passed 208 tests against a separate PostgreSQL database.
The host configuration passed 209 tests, including the Garage Sale diary-key integration test.
The Chrome preview check passed count links, completion updates, empty lists, disabled Diary, and desktop and phone layouts.
That earlier change supplied the recovery API. The DEC-005 change above supplies the existing-editor controls.
The dashboard preview uses three exclusive counts. Production dashboard integration remains outstanding.
Issue 9 was available locally. A full dictionary and technical-name review remains incomplete.

The staged DV1-031 implementation passed 200 tests with each supported user model.
Both runs used separate PostgreSQL test databases.
All 15 Chrome cases passed, including one template-editor retry after a stale-element error.
The new privacy test class covers callable search, JSON reads, HTML details, related references, current roles, and trusted scope.
No application data or deployed services changed during verification.

The staged dependency restriction passed 190 tests with each supported user model.
Both runs used separate PostgreSQL test databases.
All 15 Chrome cases passed.
One navigation case required a retry after a Chrome document-node error.

DV1-028 now rejects changes to existing diary dependencies through the API, model methods, and PostgreSQL row operations.
Migration `0006_freeze_live_dependencies` preserves existing links and completion records.
Historical graph fixtures represent records saved before that migration. Their helper operates only in the separate test database.
The database guards remain enabled during the actual restriction checks.
This change does not migrate application data or deploy services.

The user confirmed that copying existing template tasks into existing diaries is not required.
DV1-034 is removed from required work, and DEC-003 is closed.
DV1-013, DV1-018, DV1-019, DV1-039, DV1-041, and DV1-042 are complete for the remaining required interfaces.
Their existing annotations identify implementation and verification evidence.
This documentation change does not add application behavior or repeat application tests.

The user confirmed that DiaryUsers need their assigned-task view and DiaryManagers need the full diary list.
DV1-021 and DV1-022 provide those implemented views.
A separate full diary list for ordinary users is not V1 work.
This documentation correction uses existing implementation evidence and does not repeat application tests.

The web user guide describes the current production page templates and their form labels.
Its instructions distinguish ordinary users from managers and separate implemented controls from current limits.
The documentation check covers local links, sentence lengths, and selected Issue 9 dictionary entries.
Issue 9 was available locally. A full dictionary and technical-name review remains incomplete.
This documentation-only change does not repeat application tests or confirm deployment.

Task editing and completion use migration `0005_task_dates_and_completion`.
The exact staged implementation passed 177 tests with the standard user model and 177 tests with the host user model.
Both configurations used separate PostgreSQL test databases.
Tests cover date permissions, effective completion dates, private blockers, forced comments, stale forms, rollback, and concurrent changes.
The migration test keeps existing dates and completion records in an isolated PostgreSQL schema.
The Chrome check covers personal edits, manager template-task edits, normal completion, Close all, mobile layout, and host style overrides.
The same Chrome check verifies dashed, amber, and red borders with red priority.
No application database migration or deployment occurred during this change.
The full Issue 9 dictionary and technical-name review remains incomplete.

Task creation tests cover DV1-029, DV1-030, and DV1-033 against separate PostgreSQL test databases.
The staged implementation passed 156 Diary tests without host business apps and 156 tests with the host user model.
These staged checks exclude the separate pending predecessor changes.
The final task creation checks passed 13 tests, including failure during template approval.
The Chrome task creation test passed with personal ownership, manager template additions, keyboard controls, narrow screens, and host style overrides.
Concurrent saves and duplicate requests produce one successful combined addition.
Stale template versions and template-save failures keep both diary and template records.
Task creation requires no additional database migration.
A full Issue 9 dictionary and technical-name review remains incomplete.

The earlier personal-view review passed 11 tests against a separate PostgreSQL database with Django's standard user model.
Earlier local logs record nine personal tests and 145 Diary tests passing.
An earlier Chrome log records two tests passing, including the personal browser test.
The earlier personal-view documentation review did not repeat those broader or browser checks.
The host must still supply trusted permitted diary keys.
These implementation checks do not confirm deployment or host dashboard integration.

The manager view passed 134 Diary and host-integration tests against a separate PostgreSQL test database.
The isolated configuration passed 133 tests without host business apps.
The manager Chrome test passed with keyboard, filter combinations, mobile layout, and host override checks.
Manager selectors use trusted scope and reject conflicting inputs.
No application data or deployed services changed during verification.

The change for creation without a year passed 124 tests with the host application against a separate PostgreSQL test database.
The same change passed 123 tests without host business apps against a separate PostgreSQL test database.
The tests include fixed-date boundaries, leap days, time zones, safe retries, and migration data preservation.
The migration consistency check found no missing model changes.
No migration was applied to application data for this change.

The status review inspected the implementation, migrations, tests, and preview boundaries.
The Diary suite and host key integration passed 118 tests against a separate PostgreSQL database.
The isolated configuration passed 117 tests with Django's standard user model and no host business apps.
The optional time-zone change passed 37 targeted tests against a separate PostgreSQL database.
The optional Chrome test passed against a separate PostgreSQL database.
The tests include the Garage Sale key integration test.
Migration consistency checks found no model changes.
No migration was applied to application data.
ASD-STE100 Issue 9 was available locally.
A full dictionary and technical-name review remains necessary.
This checklist does not claim full ASD-STE100 compliance.

[D4]: ../docs/design/event-calendar.md#4-chosen-design
[D5]: ../docs/design/event-calendar.md#5-date-rules
[D6]: ../docs/design/event-calendar.md#6-page-design
[D7]: ../docs/design/event-calendar.md#7-milestone-date-changes-v2
[D8]: ../docs/design/event-calendar.md#8-access
[D9]: ../docs/design/event-calendar.md#9-startup-validation
[D12]: ../docs/design/event-calendar.md#12-open-decisions
