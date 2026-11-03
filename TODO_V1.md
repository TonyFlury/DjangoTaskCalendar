# Diary V1 implementation checklist

Status reviewed: 3 November 2026.

This checklist tracks the generic Diary V1 requirements in the [design document](../docs/design/event-calendar.md).
Each identifier stays unchanged when its status changes.
A checked item identifies an implemented component, not a complete V1 release.
Unchecked items remain implementation or verification work.
Previews demonstrate behavior but do not complete production view requirements.

Each item gives its completion condition and requirement reference.
Implementation and verification annotations name files and exact technical symbols.
Source comments use the same DV1 identifiers.
Partial implementation annotations do not mark an item complete.
Each partial item has a Remaining annotation.
Substantial remaining work has a linked design document.
Template blocks, CSS selectors, and JavaScript functions identify implementations without Python symbols.
Documentation-only items identify their section instead of an executable symbol.
The source links also identify the applicable design rules.
The final sections separate unresolved decisions, host integration, and deferred features.

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
  Personal-entry privacy still needs DV1-031.
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

## Access and validation work

- [ ] **DV1-013: Generic identity and role adapters.**
  Use the `DIARY_MANAGER` and `DIARY_USER` group names throughout Diary.
  Retrieve the configured user model through `get_user_model()` when model access is necessary.
  Keep host business models and custom request attributes outside Diary.
  Completion requires access tests with different host group names.
  Partial implementation: [views.py](views.py): `DjangoOwnerDirectory.person_in_groups`, `TemplateEditorView.dispatch`. [forms.py](forms.py): `TemplateTaskFormSet.__init__`.
  Verification: [tests/test_template_editor.py](tests/test_template_editor.py): `TemplateEditorTests.test_person_ownership_uses_configured_user_model_and_rejects_other_users`.
  Remaining: Add shared identity and ownership handling for task HTTP operations. Apply trusted diary scope and verify alternate groups across all operations.
  Design: [Remaining work for DV1-013](../docs/design/diary-v1-remaining-work.md#dv1-013-identity-and-role-adapters).
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

- [ ] **DV1-018: Authenticated routed views.**
  Add production URL routes and views for task lists, details, template editing, entry creation, and completion.
  Use the callable API for data actions.
  Template chooser, creation, and editing routes now exist. Task and completion routes remain outstanding.
  Enforce permissions on direct requests and save actions.
  Partial implementation: [views.py](views.py): `TemplateEditorView`, `TemplateCreateView`. [urls.py](urls.py): `urlpatterns`.
  Verification: [tests/test_template_editor.py](tests/test_template_editor.py): `TemplateEditorTests.test_anonymous_and_ordinary_users_cannot_access_or_save_templates`, `TemplateEditorTests.test_http_post_requires_csrf_token`.
  Remaining: Implement personal lists, diary lists, task details, task creation, and completion routes. Enforce task privacy, host scope, and action permissions.
  Design: [Remaining work for DV1-018](../docs/design/diary-v1-remaining-work.md#dv1-018-remaining-authenticated-task-views).
  Requirement: [D6] and [D8].

- [ ] **DV1-019: View object selectors.**
  Accept `diary_key` or `template_name` through URL parameters or trusted server-supplied context.
  Apply the same host scope and visibility checks for either input method.
  Template selectors accept URL values and trusted view context. Conflicting names return HTTP 400.
  Diary selectors remain outstanding.
  Partial implementation: [views.py](views.py): `TemplateEditorView.dispatch`.
  Verification: [tests/test_template_editor.py](tests/test_template_editor.py): `TemplateEditorTests.test_named_view_selects_latest_draft_and_supports_url_or_trusted_context`.
  Remaining: Implement diary-key inputs and cross-diary selection. Resolve DEC-001 for diary conflicts and verify invalid or unauthorized keys.
  Design: [Remaining work for DV1-019](../docs/design/diary-v1-remaining-work.md#dv1-019-diary-selectors).
  Requirement: [D6].

- [ ] **DV1-020: Personal task API across diaries.**
  Support one permitted diary or all permitted open diaries.
  Include the diary key and name with task results.
  Select only the user's personal tasks and current role-owned tasks by default.
  Keep whole-team tasks behind the explicit option.
  Requirement: [D4], [D6], and [D8].

- [ ] **DV1-021: Default personal task view.**
  Open this view by default for logged-in users.
  Without a key, group open tasks by diary name while retaining each diary key.
  With a key, show tasks from that permitted instance only.
  Exclude completed tasks and closed diaries.
  Support the Late, Ready, and Blocked filters used by host links.
  Give Late priority so those filter categories do not overlap.
  Requirement: [D6].

- [ ] **DV1-049: Ready tasks by default in My Diary.**
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
  Requirement: [D6] and [usage guidance](README.md#confirmed-v1-my-diary-display-requirement).

- [ ] **DV1-022: Full diary list view.**
  Provide explicit navigation to a permitted diary's date-ordered entries.
  Show the diary name without requiring host event metadata.
  Apply personal-entry privacy and display the date, source, owner, and state for each entry.
  Requirement: [D6] and [D8].

- [ ] **DV1-023: Task details view.**
  Show the task's date rule, due date, owner, dependency state, and completion record when applicable.
  Preserve diary context and apply privacy to related task information.
  Reuse the V1 completion controls.
  Requirement: [D6] and [D8].

- [x] **DV1-024: Template chooser and named template view.**
  Without `template_name`, list available templates for selection.
  With a name, show its highest version number, including a draft when applicable.
  Do not substitute `DIARY_TEMPLATE_NAME` for the missing view selector.
  Restrict editing to DiaryManagers.
  Implementation: [api.py](api.py): `DiaryAPI.templates`, `DiaryTemplate.editor_data`. [views.py](views.py): `TemplateEditorView.dispatch`, `TemplateEditorView.get`. [urls.py](urls.py): `urlpatterns`. [templates/Diary/template_list.html](templates/Diary/template_list.html): `diary_content`.
  Verification: [tests/test_template_editor.py](tests/test_template_editor.py): `TemplateEditorTests.test_reads_do_not_create_records_and_missing_name_opens_chooser`, `TemplateEditorTests.test_named_view_selects_latest_draft_and_supports_url_or_trusted_context`.
  Requirement: [D6] and [D8].

## Template and entry operations

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

- [ ] **DV1-028: Template-only dependency editing.**
  Reject dependency edits to existing live diary tasks through every V1 interface.
  Keep template changes from propagating into live diaries.
  The current `DiaryInstance.set_predecessors()` operation still needs restriction.
  Requirement: [D6] and [D12].

- [ ] **DV1-029: Personal entry form.**
  Set the owner to the authenticated user on the server.
  Reject another person or role supplied through a modified request.
  Keep the personal entry outside the template.
  Requirement: [D8].

- [ ] **DV1-030: DiaryManager assignment form.**
  Allow a DiaryManager to select a person, configured role, or whole-team ownership.
  Verify references through the configured identity system.
  Prevent ordinary users from assigning tasks to another owner.
  Requirement: [D6] and [D8].

- [ ] **DV1-031: Personal-entry privacy.**
  Show personally added tasks only to their owner and permitted DiaryManagers.
  Apply the rule to list reads, details, searches, predecessor choices, and both API interfaces.
  Prevent related-task information from exposing private task content.
  Requirement: [D8].

- [ ] **DV1-032: Manager-only edits to template-sourced tasks.**
  Restrict permitted edits to DiaryManagers.
  Keep the source template and other diary instances unchanged.
  Preserve the V1 ban on live dependency editing and milestone changes.
  Resolve DEC-002 before selecting additional editable fields or owner-change behavior.
  Requirement: [D4], [D8], and [D12].

- [ ] **DV1-033: Combined diary entry and template addition.**
  Offer the DiaryManager choice “Add to template for future diaries”, initially off.
  Show the reusable date rule and owner choice before saving.
  Require explicit selection of a reusable rule before adding a one-time task to the template.
  Save one diary entry and one approved template addition together with a shared entry key.
  Reject duplicate requests without creating another entry.
  Keep other existing diaries unchanged.
  Requirement: [D4] and [D8].

- [ ] **DV1-034: Add a new template item to an active diary.**
  Show the selected diary, item, ownership, and calculated date before saving.
  Permit late dates with the normal Late highlight.
  Prevent repeated additions through the stable entry key.
  Preserve existing tasks, completion records, and other diaries.
  Resolve DEC-003 for absent milestones or predecessor tasks.
  Requirement: [D4].

## Completion operations

- [ ] **DV1-035: Blocking predecessor inspection.**
  List all open predecessors in the blocking chain before task completion.
  Include indirect blockers and preserve task visibility rules.
  Resolve DEC-004 for presentation of inaccessible blockers.
  Requirement: [D6] and [D8].

- [ ] **DV1-036: Normal task completion.**
  Provide “Complete” to permitted users for accessible tasks.
  Save completion only when the blocking predecessor list is empty.
  Check the condition again during the save.
  Record one completion per task and preserve its due date at completion.
  Reject changes to a closed diary.
  Requirement: [D6].

- [ ] **DV1-037: DiaryManager “Close all” operation.**
  Complete the open blocking chain and selected task together.
  Record the manager, completion time, and due date for each newly completed task.
  Add an explanatory comment to each forced predecessor completion.
  Preserve existing completion records and all dependency links.
  Reject ordinary-user requests and concurrent changes that invalidate the operation.
  Requirement: [D6].

- [ ] **DV1-038: Persistent completion comments and history display.**
  Add storage for explanatory forced-completion comments and the selected task reference.
  Include any necessary PostgreSQL migration and API result changes.
  Display the recorded action, caller, time, and due date in task details.
  The current completion fields do not store these comments.
  Requirement: [D6].

## Presentation and release checks

- [ ] **DV1-039: Production task highlighting.**
  Give Late tasks a red shadowed border.
  Give Blocked tasks an amber shadowed border when a direct predecessor is late.
  Give red priority when the task itself is late.
  Give other Blocked tasks a dashed border.
  Keep text labels and update all task views after state changes.
  The preview implementation does not complete production styling work.
  Requirement: [D6].

- [ ] **DV1-040: Ownership display and membership handling.**
  Show person names, current role members, and “Whole team” as appropriate.
  Keep role references rather than copying a fixed member list.
  Preserve ownership when membership changes.
  Apply empty-group warnings at the validation points in section 9.
  Resolve DEC-005 for a person who loses DiaryUser membership.
  Requirement: [D6] and [D9].

- [ ] **DV1-041: Complete pages, fragments, and styling interface.**
  Use a complete base document for each routed page and reusable fragments for embedded content.
  Give visible components, controls, content roles, and states stable `diary-` classes within `.diary`.
  Avoid inline presentation rules and styling dependencies on IDs, text, tags, or element positions.
  Document every class and CSS variable in `README.md`.
  Verify keyboard access, text state labels, narrow screens, and host overrides.
  Partial implementation: [forms.py](forms.py): `StyledForm.__init__`. [templates/Diary/template_editor.html](templates/Diary/template_editor.html): `diary_content`. [templates/Diary/partials/template_editor.html](templates/Diary/partials/template_editor.html): `.diary-template-editor`. [static/Diary/styles/diary.css](static/Diary/styles/diary.css): `.diary-template-field`.
  Verification: [tests/test_styling.py](tests/test_styling.py): `DiaryStyleOverrideTests`. [tests/browser_template_editor.py](tests/browser_template_editor.py): `EditorBrowserTests.test_editor`.
  Remaining: Build remaining task documents and fragments. Complete task-state styling, class documentation, keyboard checks, narrow-screen checks, and host-override verification.
  Design: [Remaining work for DV1-041](../docs/design/diary-v1-remaining-work.md#dv1-041-remaining-pages-and-styling).
  Requirement: [D6].

- [ ] **DV1-042: Empty states and invalid selections.**
  Handle empty personal lists, unknown keys, unavailable templates, invalid selectors, and denied access explicitly.
  Preserve the selected diary context without silently choosing another instance.
  Keep all reads free from diary creation or template-copy actions.
  Do not require a host current-event attribute.
  Partial implementation: [views.py](views.py): `TemplateEditorView.dispatch`, `TemplateEditorView.get`.
  Verification: [tests/test_template_editor.py](tests/test_template_editor.py): `TemplateEditorTests.test_reads_do_not_create_records_and_missing_name_opens_chooser`, `TemplateEditorTests.test_named_view_selects_latest_draft_and_supports_url_or_trusted_context`.
  Remaining: Implement empty and error states for task pages and diary instances. Verify privacy, preserved diary context, and reads without creation.
  Design: [Remaining work for DV1-042](../docs/design/diary-v1-remaining-work.md#dv1-042-remaining-empty-and-error-states).
  Requirement: [D4], [D6], and [D8].

- [ ] **DV1-043: Enforce the V1 milestone-change boundary.**
  Keep post-creation milestone editing outside supported V1 workflows.
  Do not expose the preview milestone editor as an approved V1 page.
  Review the existing callable mutation when defining the supported V1 interface.
  Milestone changes and their impact review belong in V2.
  Requirement: [D7].

- [ ] **DV1-044: Regression and concurrency verification.**
  Cover privacy, configured groups, membership checks, selectors, template saves, task additions, and completion operations.
  Verify transaction failures, repeated requests, and races between completion, diary closure, and permitted edits.
  Run database tests only against a separate PostgreSQL test database.
  Verify installation without host business application models.
  Partial implementation: [tests/test_template_editor.py](tests/test_template_editor.py): `TemplateRevisionConcurrencyTests`, `TemplateEditorTests`. [tests/browser_template_editor.py](tests/browser_template_editor.py): `EditorBrowserTests.test_editor`.
  Remaining: Verify unimplemented identity, group, selection, privacy, task-editing, and completion workflows. Cover transaction rollback and concurrent completion, closure, and permitted edits.
  Design: [Remaining work for DV1-044](../docs/design/diary-v1-remaining-work.md#dv1-044-remaining-verification).
  Requirement: [D4], [D6], [D8], and [D9].

- [ ] **DV1-045: Release documentation and deployment checks.**
  Update API signatures, view inputs, settings, migration instructions, and styling documentation for the final implementation.
  Preserve the documented runtime warning limit for ownership group changes.
  Check all V1 items against their completion conditions before release.
  Record the language review limits without claiming unverified ASD-STE100 compliance.
  Requirement: [D4], [D6], [D9], and [usage documentation](README.md).

## Decisions needed by specific items

These entries identify unresolved details, not approved implementation rules.
They do not reopen the confirmed V1 decisions.

| Identifier | Decision | Affected items | Documentation |
| --- | --- | --- | --- |
| DEC-001 | Template views reject conflicting selectors. Confirm the same rule when implementing diary views. | DV1-019 | [Usage guide](README.md#template-creation-and-editing). |
| DEC-002 | Define additional editable instance fields, owner changes, and any extra progress states. | DV1-032 | [D12], especially item 16, retains owner-change decisions. |
| DEC-003 | Define item-copy behavior when required milestones or predecessor tasks are absent. | DV1-034 | [D4] records this unresolved detail. |
| DEC-004 | Define how the blocker list represents tasks whose details the current user cannot view. | DV1-035 | [D6] and [D8] require blocker inspection and personal-entry privacy. |
| DEC-005 | Define review and ownership handling when a person loses DiaryUser membership. | DV1-040 | [D6] requires review and prohibits silent whole-team reassignment. |

## Host integration work

These items belong to the [Garage Sale integration design](../GarageSale/DIARY_INTEGRATION.md).
They are outside the generic Diary V1 implementation.

- [ ] **HOST-001:** Decide when the host creates and closes diary instances.
- [ ] **HOST-002:** Map source dates to milestones and save returned Diary keys against the correct host records.
- [ ] **HOST-003:** Supply authenticated identity, current memberships, configured groups, and permitted diary scope.
- [ ] **HOST-004:** Connect the host dashboard's compact Late, Ready, and Blocked counts to the personal task filters.

The dashboard must omit Diary imports and content when the app is disabled.
Its counts must exclude whole-team tasks and completed tasks.
Late has priority over Blocked or Ready, so each task contributes to one count.
Zero counts remain links, and an absent host Diary key has an explicit empty state.
Reference: [D6] and the host integration design.

## Outside V1

The following work is not a generic Diary V1 requirement:

- Milestone date changes and their impact review belong in V2.
- V2 must review the V1 force completion behavior.
- Dependency editing in live diaries is deferred to a future review.
- Multiple sign-offs are outside V1.
- Reminders have no confirmed release number.
- A month display, exports, and broad retrospective template replacement are not approved V1 requirements.
- A separate template approval step is outside V1.
- Template task content is application data.
- Diary has no public view.
- Finer-grained permissions may become an optional feature in a later version, outside V1.

## Future requirements

These requirements have no assigned release and are not V1 completion conditions.

- [ ] **DFUT-001: Independent diary creation UI.**
  Let an authorized user create a diary from an approved template through Diary's own UI.
  Prompt for the diary name, diary year, and the selected template's relevant milestone dates.
  Use the existing instance creation API and preserve safe retries without duplicate diaries.
  Require no Garage Sale event or other host business record.
  Define the permitted role and access to the newly created diary before implementation.
  Implementation: Not started. No UI classes, functions, or routes implement this requirement.
  Design: [Independent diary creation UI](../docs/design/diary-instance-creation-ui.md).
  Existing API: [api.py](api.py): `DiaryAPI.create_diary`, `DiaryInstance.create`, `DiaryTemplateVersion.required_milestones`.

## Review limits

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
