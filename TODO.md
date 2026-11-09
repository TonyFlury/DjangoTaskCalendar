# DjangoTaskCalendar repository TODO

## README and documentation

**Must have before publication:** Complete the [documentation publication plan](docs/design/documentation-publication-plan.md), including all three audience guides, the short README, verified examples, and Read the Docs publication setup. Documentation is a release gate for package publication and public documentation launch.

- [ ] **DOC-001:** Write the complete repository README.
  Provide a short product introduction, main features, representative screenshot, prerequisites, licence, and links to the three guides. Keep the full quick-start in the documentation.
- [ ] **DOC-002:** Build the standalone developer guide.
  Document settings, PostgreSQL setup, migrations, identity adapters, permissions, callable APIs, UI integration, and management commands.
- [ ] **DOC-003:** Build the standalone user and administrator guides.
  Document templates, diaries, ownership, dependencies, task completion, orphaned tasks, and validated fixture transfers.
- [ ] **DOC-004:** Review preserved documentation and design examples for standalone use.
  Replace obsolete host-specific instructions and broken links. Review dashboard previews that refer to GarageSale assets.
- [ ] **DOC-005:** Verify documentation examples in a minimal Django host with PostgreSQL.
  Keep test data in a separate PostgreSQL database.
- [ ] **DOC-006:** Complete the ASD-STE100 Issue 9 dictionary and technical-name review.
  English is the current documentation language. Localization is not required.
- [ ] **DOC-007:** Write the minimal, end-to-end quick-start guide, including task templates and Django HTML templates.
- [ ] **DOC-008:** Configure and verify Read the Docs publication through the GitHub integration, including strict documentation builds, release versions, and pull-request previews.
- [ ] **DOC-009:** Reconcile README installation and packaging claims with `pyproject.toml` and verified distribution contents before publication.

## Packaging and release

- [ ] **PKG-001:** Implement installable distribution packaging under the existing DFUT-005 requirement.
  Include the application modules, management commands, migrations, templates, and static assets.
- [ ] **PKG-002:** Decide the distribution name, license, version policy, supported versions, and publication location.
  The repository name is DjangoTaskCalendar. The current Python import name remains `Diary`.
- [ ] **PKG-003:** Verify installation and migration compatibility in an independent Django project.
- [ ] **PKG-004:** Define automated package checks and the release process.

## Database independence and testing

- [ ] **DB-001:** Support and test SQLite alongside PostgreSQL.
  The package should be database independent, with SQLite and PostgreSQL as the minimum verified backends. PostgreSQL remains the current implementation requirement until this work is complete.
  Completion requires:
  - Run the same backend-independent application tests against both SQLite and PostgreSQL in automated checks, using isolated test databases and documented test settings and commands.
  - Apply the complete migration history to an empty database on each backend and verify upgrade paths for existing installations.
  - Replace or adapt PostgreSQL-specific SQL, triggers, locking assumptions, and unconditional backend assertions. Preserve snapshot immutability, date-source provenance, dependency integrity, and API validation on both backends.
  - Verify templates, date calculations, diary creation and editing, permissions, and management commands on both backends. Include SQLite coverage for browser workflows that access the database.
  - Keep backend-specific concurrency and database-enforcement tests explicit. Document differences in guarantees and justify any backend-specific skips; skipping the shared suite or disabling integrity checks does not satisfy this requirement.
  - Update installation and developer documentation with verified backend support and limitations. Do not claim support for other database engines until they have been tested.

## Framework and database version support

- [ ] **COMPAT-001:** Support and test modern Django releases.
  Establish a documented support matrix covering the latest stable Django release and supported Django LTS series, using compatible Python and database versions. Select releases using the [official Django support table](https://www.djangoproject.com/download/#supported-versions).
  Completion requires automated application, migration, management-command, and installed-package integration tests for every declared Django series, including SQLite coverage under DB-001. Test the latest patch release in each series and check the minimum declared dependency version.
  Replace the exact `Django==5.0` dependency pin with a tested compatibility range. Update package metadata and installation documentation only after the corresponding checks pass. Resolve deprecations before they become incompatible changes, and review the matrix for each new Django release.

- [ ] **COMPAT-002:** Support and test modern PostgreSQL releases.
  Establish a documented matrix covering at least the latest stable PostgreSQL major release and its two preceding majors while they remain supported upstream and compatible with the declared Django versions. Use the [official PostgreSQL versioning policy](https://www.postgresql.org/support/versioning/) to review support lifetimes.
  Completion requires automated application tests on each declared PostgreSQL major, using its latest minor release and a compatible database driver. Verify the full migration history, upgrades from existing installations, triggers, constraints, transactions, locking, and concurrency behavior on each major.
  Exercise every declared Django/PostgreSQL combination in automated checks, or explicitly exclude unsupported combinations from the published matrix. Document Python and driver requirements, review new PostgreSQL majors, and remove end-of-life versions through a documented support-policy change. Retain the SQLite checks required by DB-001.

## Diary feature backlog

This section is the canonical list of Diary feature requirements with DFUT identifiers.
Identifiers and existing completion statuses are retained from the V1 checklist.
Unchecked items have no assigned release and are not V1 completion conditions.
Completed items retain their implementation record. The [V1 checklist](Diary/TODO_V1.md)
separately records implemented V1 capabilities and remaining V1 review work.

- [ ] **DFUT-001: Independent diary creation UI.**
  Let an authorized user create a diary from an approved template through Diary's own UI.
  Prompt for the diary name and the selected template's relevant milestone dates.
  Use the existing instance creation API and preserve safe retries without duplicate diaries.
  Require no Garage Sale event or other host business record.
  Define the permitted role and access to the newly created diary before implementation.
  Implementation: Not started. No UI classes, functions, or routes implement this requirement.
  Design: [Independent diary creation UI](docs/design/diary-instance-creation-ui.md).
  Existing API: [api.py](Diary/api.py): `DiaryAPI.create_diary`, `DiaryInstance.create`, `DiaryTemplateVersion.required_milestones`.

- [ ] **DFUT-002: Multiple DiaryUser access groups.**
  Let `DIARY_USER` specify a set of groups, with DiaryUser access through membership in any configured group.
  Support ownership groups with no common members or shared access group.
  Preserve manager permissions and the caller's permitted diary keys.
  Update setting validation, startup checks, API access checks, and person ownership eligibility when implementing this requirement.
  Implementation: Deferred. The current setting accepts one group name and rejects collections.
  Remaining: Implement collection support and verify separate ownership groups without common members.
  Design: [Multiple Diary user groups](docs/design/diary-user-groups.md).
  Documentation only. No executable implementation or verification is complete for this requirement.

- [ ] **DFUT-003: Future date-window filtering in all diary views.**
  Let users select a future due-date window for incomplete tasks in every diary view.
  Preserve task access rules and the selected permitted diary scope.
  Implementation: Deferred. No production controls or executable verification implement this requirement.
  Remaining: Define date boundaries and filter interactions before implementing the controls and task selection.
  Design: [Future date-window filtering](docs/design/diary-v1-remaining-work.md#dfut-003-future-date-window-filtering).
  Documentation only. This requirement has no assigned release and is not a V1 completion condition.

- [ ] **DFUT-004: Controlled dependency editing in existing diaries.**
  Consider a more flexible dependency editor for a later release.
  No relaxed editing policy or release number is approved.
  Keep the V1 dependency freeze until a later implementation explicitly replaces it.
  Implementation: Not started. No supported operation edits dependencies in an existing diary.
  Remaining: Define permissions, permitted changes, completion handling, history, cycle checks, concurrent saves, and closed-diary behavior.
  Design: [Future live dependency editing](docs/design/diary-v1-remaining-work.md#dfut-004-live-diary-dependency-editing).
  Documentation only. This backlog record adds no executable editing interface.

- [ ] **DFUT-005: Installable Python package.**
  Distribute Diary as an installable Python package after V1.
  Keep the package independent of Garage Sale business models and integration code.
  Implementation: Not started. No distribution metadata, build, publication workflow, or installation verification implements this requirement.
  Remaining: Define package names, supported versions, distribution location, release policy, and migration compatibility.
  Design: [Diary installable Python package](docs/design/diary-python-package.md).
  Documentation only. No later release number is assigned, and this item is not a V1 completion condition.

- [ ] **DFUT-006: Host-defined milestone catalogues for different templates in one database.**
  Support multiple templates in the same database with the host supplying different
  sets of available milestones for different templates. Multiple templates already
  exist; this requirement concerns separating their available milestone catalogues.
  Managers must see the catalogue applicable to the template they are editing,
  without a separate manual requirement-selection step. Required dates continue to
  follow task usage; hosts may supply extra unused milestone data, which Diary ignores.
  A substantial design review is required before implementation. Review catalogue
  identity and ownership, template/version binding, milestone key and label collisions,
  host configuration and authorization, editor choices, discovery APIs, management
  commands, fixture transfer, and migration of the current shared catalogue.
  Decide how catalogue changes affect existing versions and diary snapshots, and
  how existing integrations retain their behavior. Do not assume that catalogues
  require separate databases or that this introduces a full tenancy model.
  Implementation: Not started. No release assigned; this is not a publication gate.
  Design decisions remain open. Record the agreed design before making application changes.

- [ ] **DFUT-007: Standard signals for task progression and changes.**
  Confirmed mechanism: use Django Signals (`django.dispatch.Signal`). This is a
  requirement, not an open choice of event framework.
  Provide a documented, standard set of Django signals that hosts can subscribe to
  when tasks progress, including completion and ownership changes.
  Design the complete event set before implementation; consider due-date changes,
  chain completion, and any future progression states without committing to them yet.
  Cover supported task mutations consistently across callable APIs, class views,
  and management commands, rather than relying on view success hooks alone.
  Review signal names, senders, stable payloads (diary/task identifiers, actor and
  relevant changes), privacy, transaction commit timing, rollback, retries,
  idempotent operations, receiver failures, and ordering. Decide whether chain
  completion produces individual task events, an aggregate event, or both.
  Define the relationship to existing host view hooks and document delivery
  guarantees; do not imply durable or exactly-once event delivery from Django signals.
  Implementation: Not started. No release assigned; this is not a publication gate.
  Record the agreed signal contract and verification plan before application changes.

- [ ] **DFUT-008: Task prioritisation fields.**
  Add fields that let tasks express priority. The field set, allowed values,
  defaults, and meaning remain to be designed; do not assume a particular scale
  or scoring scheme.
  Review priority on template tasks and diary tasks, inheritance when creating
  diaries, diary-specific overrides, editing permissions, and migration of existing
  tasks. Define how priority affects display, sorting, filtering, callable APIs,
  management commands, and template transfer. Keep priority distinct from due dates,
  lateness, and dependency readiness. Consider whether priority changes belong in
  the future signal contract (DFUT-007).
  Implementation: Not started. No release assigned; this is not a publication gate.
  Agree the field model and user-facing behaviour before application changes.

- [ ] **DFUT-009: Optional group voting for task progression.**
  Let tasks assigned to a group optionally require agreement from its members before
  progressing. Candidate policies include All, Majority, and At least N.
  Decide whether members submit approval only or approve/reject votes, and how
  rejection affects task status and dependent tasks. Define when dependants remain
  blocked and exactly what agreement permits progression.
  Review voter eligibility, membership changes, denominator and quorum rules,
  abstentions, ties, empty groups, impossible thresholds, vote changes, reopening,
  manager overrides, privacy, audit history, retries, and concurrent voting.
  Distinguish a member's vote from completion of the shared task.
  Implementation: Not started. No release assigned; policy and state transitions need design.

- [ ] **DFUT-010: Decision tasks with conditional branches.**
  Support a yes/no decision task whose outcome activates one of two different
  successor tasks. Define how an outcome is recorded, who may decide, and how
  unselected branches are represented and excluded from normal blocking rules.
  Review branch convergence, shared successors, changing or reopening a decision,
  already completed branch work, and interaction with group voting and loops.
  Preserve the distinction between a decision outcome and task completion.
  Implementation: Not started. No release assigned; branching semantics need design.

- [ ] **DFUT-011: Graphical task graph editor.**
  Provide a graphical editor for tasks and their relationships.
  Decide its scope for templates versus existing diaries, editing permissions,
  versioning, layout, keyboard accessibility, and an equivalent non-graphical workflow.
  Review representations for dependencies, decision branches, voting requirements,
  and deliberate loops. Server-side validation remains authoritative.
  Coordinate with DFUT-004 for any editing of dependencies in existing diaries;
  a graphical interface does not itself authorize live graph changes.
  Partial implementation: the manager template editor has a read-only SVG preview
  in `Diary/templates/Diary/partials/template_editor.html`, `Diary/static/Diary/scripts/template_editor.js`:
  `taskGraph`, and `Diary/static/Diary/styles/diary.css`: `.diary-template-graph`.
  It previews unsaved tasks and dependencies with automatic layout, zoom, pan,
  keyboard access, and task dialogs with separate draft save/cancel actions under DV1-057.
  Verification: `Diary/tests/browser_template_graph.py`: `TemplateGraphBrowserTests`;
  `Diary/tests/test_template_editor.py`: `TemplateEditorTests.test_graph_preview_uses_existing_manager_editor_and_does_not_write`.
  V1 implementation record: [DV1-055, graphical template view](Diary/TODO_V1.md#presentation-and-release-checks).
  Remaining: direct graphical editing, live diary scope, and representations for
  future decisions, votes, and workflow loops. No release assigned for that work.

- [ ] **DFUT-012: Task data capture through arbitrary forms.**
  Allow a task to capture data using an arbitrary form. Decide how forms are
  supplied or defined, including whether the host provides Django forms, stored
  schemas, or another mechanism; no form framework is selected yet.
  Review validation, storage and ownership of submissions, permissions, sensitive
  data, audit history, attachments, form versioning, and template portability.
  Define whether valid submission is required for progression, whether drafts and
  later edits are supported, and how hosts retrieve data and receive notifications.
  Implementation: Not started. No release assigned; form and data contracts need design.

- [ ] **DFUT-013: Deliberate task reactivation and workflow loops.**
  Allow tasks to reactivate previous tasks as explicitly designed workflow loops.
  Review graph validation so deliberate loops are supported and loops without exit
  options are highlighted. Define what constitutes an exit and which cases should
  produce warnings or prevent saving; structural and conditional exits may differ.
  Decide how reactivation affects completion history, task state, dependent tasks,
  votes, decisions, captured data, and repeated workflow passes. Preserve an audit
  trail and define safeguards against unintended or uncontrolled repetition.
  Review existing readiness calculations, traversal, completion, and Close all;
  current assumptions about acyclic dependencies cannot simply be removed.
  Implementation: Not started. No release assigned; execution and exit semantics need design.

The remaining workflow changes under DFUT-009 through DFUT-013 require a coordinated
workflow design review before implementation. They are not publication gates. Review their interaction with
DFUT-007 signals, existing diary snapshots, callable APIs, management commands,
template transfer, migration, and backward compatibility.

- [x] **DFUT-014: Due dates relative to another task's due date.**
  Add a template date rule that selects a source task and a signed calendar-day
  offset from its due date. Date references are separate from completion
  dependencies: using a task's date does not itself require that task to finish first.
  Resolve date-reference chains in order when creating a diary or applying its
  first template, and store the resulting diary due dates as fixed snapshots.
  Reject missing or unresolvable source tasks and circular date references.
  Late or early completion must not move those dates. Later manual edits to a
  source task's due date must also leave previously calculated dates unchanged.
  Cover models and migration, editor controls, callable APIs, fixture transfer,
  documentation, and tests, including chained references and safe creation retries.
  Implementation: `DateKind.TASK`, `EntrySpec.source_task_key`,
  `date_rules.task_date_order`, `date_rules.task_relative_date`,
  `CalendarEntry.task_due_date`, and migration `0013_task_relative_due_dates`.
  Template and diary task forms provide independent source selectors and offsets.
  Template copying, approval, fixture transfer, and callable additions retain and
  validate the rule; model and database guards preserve initialized snapshots.
  Verification: `Diary/tests/test_task_relative_dates.py`: `TaskDateGraphTests`,
  `TaskRelativeDateTests`, `TaskRelativeDateMigrationTests`;
  `Diary/tests/browser_template_graph.py`: `TemplateGraphBrowserTests.test_task_relative_date_controls_save_without_creating_completion_dependencies`.
  V1 implementation record: [DV1-056, task-relative due dates](Diary/TODO_V1.md#implemented-components).

- [ ] **DFUT-015: Track forward impacts on tasks with related due dates.**
  Future work following DFUT-014: identify direct and transitive tasks whose dates
  were calculated from a source task, so managers can review the forward impacts
  of a changed source due date or late completion.
  Preserve the original date-reference provenance needed to explain those links
  after diary creation. Keep date-reference relationships distinct from completion
  dependencies. Tracking impacts must not automatically change stored due dates.
  Review how to present original and current dates, lateness, affected tasks, and
  any suggested dates; define permissions, completed-task handling, and audit needs
  before implementation. Any future rescheduling needs a separately agreed policy.
  Implementation: Deferred. No release assigned; impact display and calculation
  details remain open.

## Scope

GarageSale event creation, settings, URL adapters, page wrappers, and dashboard integration belong to the host repository.
This repository must not acquire dependencies on GarageSale business models.
The [Diary V1 checklist](Diary/TODO_V1.md) tracks V1 implementation and review work under DV1 identifiers.
The Diary feature backlog above retains the original DFUT identifiers and statuses.
