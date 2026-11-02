# Diary V1 implementation checklist

Status reviewed: 2 November 2026.

This checklist tracks the generic Diary V1 requirements in the [design document](../docs/design/event-calendar.md).
Each identifier stays unchanged when its status changes.
A checked item identifies an implemented component, not a complete V1 release.
Unchecked items remain implementation or verification work.
Previews demonstrate behavior but do not complete production view requirements.

Each item gives its completion condition and requirement reference.
The source links also identify the applicable design rules.
The final sections separate unresolved decisions, host integration, and deferred features.

## Implemented components

- [x] **DV1-001: Independent PostgreSQL data layer.**
  Diary owns its models and migrations without foreign keys to host application models.
  Evidence: [models](models.py), [migrations](migrations/), and [database tests](tests/test_api.py).
  Requirement: [D4].

- [x] **DV1-002: Named milestone API.**
  Milestone names remain stable, and discovery returns the names used by the selected template version.
  Discovery is optional for callers that already know the required names.
  Evidence: [callable API](api.py) and [API tests](tests/test_api.py).
  Requirement: [D4].

- [x] **DV1-003: Date calculation.**
  Source, relative, annual, and one-time rules calculate dates and identify missing or invalid dates.
  Lateness uses `DIARY_TIME_ZONE` and includes tasks due today.
  Evidence: [date rules](date_rules.py), [callable API](api.py), and [API tests](tests/test_api.py).
  Requirement: [D5] and [D6].

- [x] **DV1-004: Named diary creation and template snapshots.**
  Creation requires a nonempty name and copies an approved template's entries, rules, owners, and dependencies.
  Repeated creation with identical inputs returns the same Diary key.
  Existing diaries retain their copies after template changes.
  Evidence: [callable API](api.py) and [API tests](tests/test_api.py).
  Requirement: [D4].

- [x] **DV1-005: Ownership data and assignment checks.**
  The model supports person, role, and whole-team ownership.
  Ordinary users can add only self-owned personal entries.
  The configured edit permission controls assignments to another person or role.
  Evidence: [models](models.py), [callable API](api.py), and [API tests](tests/test_api.py).
  Requirement: [D6] and [D8].

- [x] **DV1-006: Saved dependency validation.**
  The API excludes circular choices and rejects invalid links within the saved graph.
  Database locks prevent concurrent saves from creating a cycle.
  Evidence: [API tests](tests/test_api.py) and [concurrency tests](tests/test_concurrency.py).
  Requirement: [D6].

- [x] **DV1-007: Task reads for one diary.**
  `DiaryInstance.active_tasks()` and `DiaryInstance.personal_tasks()` calculate readiness and lateness without stored status flags.
  Personal selection uses current user and role references.
  Personal-entry privacy still needs DV1-031.
  Evidence: [callable API](api.py) and [API tests](tests/test_api.py).
  Requirement: [D6] and [D8].

- [x] **DV1-008: Close a diary instance.**
  `DiaryInstance.close()` accepts open tasks, preserves records, and safely handles repeated calls.
  Closed diaries remain readable but reject API changes and contribute no active tasks.
  Evidence: [migration 0003](migrations/0003_calendar_closure.py) and [API tests](tests/test_api.py).
  Requirement: [D4].

- [x] **DV1-009: Configured ownership role names and existence checks.**
  `DIARY_TASK_OWNER_ROLES` controls assignment choices.
  Startup validates role existence directly through Django's standard group model.
  Membership validation still needs DV1-014 through DV1-017.
  Evidence: [role validation](roles.py), [startup](apps.py), and [role tests](tests/test_roles.py).
  Requirement: [D4] and [D9].

- [x] **DV1-010: Basic completion record fields.**
  Models store the completing actor, completion time, and due date at completion.
  Normal saves protect completed records.
  Completion operations and explanatory comments still need DV1-035 through DV1-038.
  Evidence: [models](models.py) and [API tests](tests/test_api.py).
  Requirement: [D6].

- [x] **DV1-011: Base template and reusable task fragment.**
  The task list can render as a complete document or as reusable content.
  Default styles and override guidance exist.
  Production pages still need DV1-041.
  Evidence: [templates](templates/Diary/), [styling tests](tests/test_styling.py), and [usage guide](README.md).
  Requirement: [D6].

- [x] **DV1-012: Runtime warning limit documented.**
  The API guide explains the absence of automatic warnings after ownership groups become empty or disappear.
  Restart, creation, and template editing remain the documented validation points.
  Evidence: [startup and ownership requirements](README.md#startup-and-ownership-validation-requirements).
  Requirement: [D9].

- [x] **DV1-046: Class-based callable API and factories.**
  `DiaryAPI` holds the actor context and provides shared services.
  `DiaryInstance`, `DiaryTemplate`, and `DiaryTemplateVersion` provide factories and object operations.
  Factories return references with stable keys without granting extra scope.
  Operations check permissions and current database state each time.
  Evidence: [API implementation](api.py), [class API tests](tests/test_class_api.py), and [migration guidance](README.md#migration-from-module-functions).
  Requirement: [D4].

- [x] **DV1-047: Simple V1 access settings.**
  `DIARY_MANAGER` and `DIARY_USER` each select one group.
  Managers inherit user capabilities and have all template permissions.
  Startup rejects missing or invalid setting values.
  The old configurable action mapping grants no access in V1.
  Database checks for group existence and membership still need DV1-014.
  Evidence: [access configuration](roles.py), [API checks](api.py), and [permission tests](tests/test_class_api.py).
  Requirement: [D4] and [D9].

- [x] **DV1-048: Standard Django groups and optional template default.**
  Role checks use Django groups without a host lookup setting or callback.
  Explicit template names and version keys work without `DIARY_TEMPLATE_NAME`.
  The setting remains an optional default, and conflicting selectors are rejected.
  Evidence: [role checks](roles.py), [group tests](tests/test_roles.py), and [factory tests](tests/test_class_api.py).
  Requirement: [D4].

## Access and validation work

- [ ] **DV1-013: Generic identity and role adapters.**
  Use the `DIARY_MANAGER` and `DIARY_USER` group names throughout Diary.
  Retrieve the configured user model through `get_user_model()` when model access is necessary.
  Keep host business models and custom request attributes outside Diary.
  Completion requires access tests with different host group names.
  Requirement: [D4] and [D8].

- [ ] **DV1-014: Startup access-group validation.**
  Require `DIARY_MANAGER` and `DIARY_USER`.
  Setting-value validation exists, but database existence and membership checks remain outstanding.
  Check that every referenced group exists and has at least one user.
  Raise `ImproperlyConfigured` with setting names and distinct missing-group or empty-group explanations.
  Keep database and group setup commands available.
  Requirement: [D9].

- [ ] **DV1-015: Startup ownership membership validation.**
  Check that every configured task ownership role exists and has at least one member.
  Report each absent or empty role through `ImproperlyConfigured`.
  Extend the current Django group checks to validate membership.
  Requirement: [D9].

- [ ] **DV1-016: Ownership validation during diary creation.**
  Repeat ownership existence and membership checks against the current database state.
  Reject creation when a configured role is absent or empty.
  Preserve transaction safety without a partly created diary.
  Requirement: [D9].

- [ ] **DV1-017: Empty-group warnings during template editing.**
  Check current membership for the selected ownership group.
  Show an on-screen warning with the group name and affected task when it has no members.
  Keep this warning separate from creation validation.
  Requirement: [D9].

## HTTP views and task selection

- [ ] **DV1-018: Authenticated routed views.**
  Add production URL routes and views for task lists, details, template editing, entry creation, and completion.
  Use the callable API for data actions.
  Enforce permissions on direct requests and save actions.
  Requirement: [D6] and [D8].

- [ ] **DV1-019: View object selectors.**
  Accept `diary_key` or `template_name` through URL parameters or trusted server-supplied context.
  Apply the same host scope and visibility checks for either input method.
  Resolve decision DEC-001 before finalizing conflicting-input behavior.
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

- [ ] **DV1-024: Template chooser and named template view.**
  Without `template_name`, list available templates for selection.
  With a name, show its highest version number, including a draft when applicable.
  Do not substitute `DIARY_TEMPLATE_NAME` for the missing view selector.
  Restrict editing to DiaryManagers.
  Requirement: [D6] and [D8].

## Template and entry operations

- [ ] **DV1-025: Template authoring interface.**
  Support named milestones, reusable date rules, and optional person, role, or whole-team ownership.
  Offer only configured ownership roles.
  Keep template task content under the author's control.
  Requirement: [D4], [D5], [D6], and [D9].

- [ ] **DV1-026: Versioned template save and approval.**
  Preserve stable entry keys when creating a changed version.
  Approve the resulting version through the DiaryManager's save action.
  Require no separate approval action in V1.
  Keep existing diary copies unchanged.
  Requirement: [D4] and [D8].

- [ ] **DV1-027: Safe template predecessor editor.**
  Exclude the task, its direct successors, its indirect successors, and tasks outside the selected template version.
  Recalculate choices using proposed unsaved links.
  Retain server validation and concurrency protection.
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
  Requirement: [D6].

- [ ] **DV1-042: Empty states and invalid selections.**
  Handle empty personal lists, unknown keys, unavailable templates, invalid selectors, and denied access explicitly.
  Preserve the selected diary context without silently choosing another instance.
  Keep all reads free from diary creation or template-copy actions.
  Do not require a host current-event attribute.
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
| DEC-001 | Define precedence or rejection when URL and context selectors conflict. | DV1-019 | [D6] defines both input methods without conflict behavior. |
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

## Review limits

The status review inspected the implementation, migrations, tests, and preview boundaries.
The entry mapping refactor passed 67 tests against a separate PostgreSQL database.
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
