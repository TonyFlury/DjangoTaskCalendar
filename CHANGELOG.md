# Version timeline

## 0.1.11.1 — 11 November 2026

- Delivered DFUT-018 calendar presentations through the existing personal and
  manager diary endpoints. List, Day, Week and Month use package-owned templates;
  hosts retain one URL per role and their existing wrapper and access policy.
- Kept the existing role-specific filters and defaults consistent across
  presentations. Added a paginated daily agenda alongside the weekly/monthly
  calendars, busy-day expansion, responsive layouts and late/undated panels.
- Remembered presentation choices per authenticated user/session and role. An
  explicit `view` parameter overrides the preference; scope and permissions are
  checked on every request and are never restored from the preference.
- Preserved identifier-free host POST task selection and signed calendar return
  navigation through existing host redirects, including task-note saves. Existing
  standalone calendar routes remain available for compatibility.
- Updated host/user documentation. Integration requires the normal package/static
  asset deployment; no new host calendar views, URLs, dependencies or database
  migrations are required when using the existing package wrapper hooks.
- Verification: the 378-test server suite, browser regression checks, and focused
  presentation/redirect tests passed. Package publication is not recorded here.

## Recorded versions

Updated on 11 November 2026 using committed package metadata through
**0.1.10.2** (`34d1098`) and the prepared **0.1.11.1** changes.
Calendar implementation commit `b4a9c86` retained the 0.1.10.2 version number
and is included in the following 0.1.11.1 snapshot under the grouping rule below.
The repository's primary branch is named `main`; there is no `master` branch.

Mainline version numbers come from first-parent committed `[project].version` values in
`pyproject.toml`. Dates are the version-change commits' dates, not verified
package publication dates. There are no release tags in the available history.
Each entry describes changes since the preceding version-change commit through
the named commit, inclusive. This groups implementation commits immediately
before a version-only bump with that new version. Commits after a version bump
are included in the following snapshot, rather than assumed to be published
under the previous version. The first entry includes the earlier baseline.

| Date | Version | Version commit | Changes in this snapshot |
| --- | --- | --- | --- |
| 3 November 2026 | **0.1.2** | `eed4c21` | First recorded package metadata. Baseline includes the class-based callable API, versioned templates, personal and manager task views, privacy and ownership controls, task creation, date editing, completion, and template fixture transfer. Added runtime configuration-checking middleware, a configuration validation command, and further host-template extensibility. |
| 4 November 2026 | **0.1.2.1** | `7d46837` | Compacted manager filters, kept actions within their panel, and adjusted personal diary markup and styling. The version commit itself only changes metadata; the UI changes are in `9462e91` and `b864cbf`. |
| 4 November 2026 | **0.1.2.2** | `383786a` | Changed template milestone declarations to reference an existing host catalogue. Added template/version milestone relationships and migration `0008`, plus API, editor, transfer, validation, and documentation changes. |
| 4 November 2026 | **0.1.2.3** | `8ab6257` | Added `manage_diaries` and `manage_diary_templates`, administrative deletion support and migration `0009`. Also included the template success-navigation hook from `c39518d`. |
| 4 November 2026 | **0.1.2.4** | `9412a63` | Added `--uuid` listing options, deletion confirmation prompts and management output improvements. Exposed template editor context through `get_context_data()` for host subclasses. |
| 4 November 2026 | **0.1.3.1** | `724c7f6` | Allowed diaries and tasks before a template is deployed. Added later template application, the application page, API/command support, and migration `0010` for optional diary templates. |
| 4 November 2026 | **0.1.4.1** | `cfa895a` | Expanded success callbacks and host navigation across write views, with signed form targets and host integration documentation. Included follow-up optional-template fixes and browser coverage from `bf30e21`. |
| 4 November 2026 | **0.1.4.2** | `7a51cd1` | Introduced the shared `DiarySuccessMixin` / `DiaryViewResult` host response contract. Derived required template milestones from task rules, removing manual milestone selection; migration `0011` handles existing declarations. |
| 5 November 2026 | **0.1.5.1** | `628f475` | Added task notes through the API and task detail UI, with migration `0012`. Removed the `--actor` requirement from administration commands. Also recorded additional future requirements. |
| 8 November 2026 | **0.1.6.1** | `6092aa5` | Added the graphical template viewer with task/dependency layout, zoom, pan, and keyboard links to editing forms. Includes the build guide and command-specific help pages from `842ef78`, which did not change the package version. |
| 8 November 2026 | **0.1.7.1** | `ad56990` | Implemented DFUT-014: task due dates relative to other task due dates, using signed offsets and source-first resolution. Resolved dates remain fixed after initialization. Includes validation, provenance, API/forms/transfer support, migration `0013`, and tests from `bf86c44`; the version commit itself is metadata-only. |
| 8 November 2026 | **0.1.8.1** | `5193cf7` | Reduced graph crossings with connected-component layout and routing around task boxes. Changed predecessor and date-source choices to creation/subgraph order instead of alphabetical order. |
| 8 November 2026 | **0.1.8.4** | `f2af6b5` | Displayed referenced milestones as shared diamonds and added date-relation arrows. Positioned milestones/tasks using signed offsets; zero offsets connect at task tops without changing actual dates. Suppressed duplicate date arrows where a completion relationship already connects the same tasks. Includes `590b851`. |
| 9 November 2026 | **0.1.9.1** | `b629174` | DV1-057 template UI refresh: graph-first navigation, compact task dialogs, draft Save task / Cancel, separate Save template, searchable task finder, and one shared task/milestone date-source picker. Moved the DFUT backlog into the root TODO and documented completed graph/task-relative-date capabilities. |
| 10 November 2026 | **0.1.9.4** | `acc4895` | Moved title/description and version status into Settings, automatically opened for new templates; moved guidance into Help. Added the navigator toolbar, separators, icon-only actions, and CSS hooks for host graphics, labels, and tooltips. Fixed zoom to keep the panel size stable with scrollable content. Includes left alignment of task search and the future subgraph/manual-layout requirements from `08f6f71`; those future features are not implemented. |
| 10 November 2026 | **0.1.10.1** | Merge of `167e724` into main | Integrated DFUT-007 signals for task creation, notes, dependency changes, closure, and ownership changes. Events carry actor email, task key, and task name; dispatch occurs after commit and isolates receiver errors. Preserves task-relative date ordering and source validation added on main. Includes signal tests and this reconstructed changelog. |
| 10 November 2026 | **0.1.10.2** | `34d1098` | Added diary/version scope keys to all five task signals and task/note/predecessor API records, resolving reused task UUID ambiguity. Added cross-diary/version and HTTP identity tests. |
| 11 November 2026 | **0.1.11.1** | Prepared in working tree | DFUT-018 calendar delivery and rework: package-owned List/Day/Week/Month switching on existing diary URLs, shared role filters, per-user/session preferences, identifier-free POST navigation, signed task returns, responsive layouts and updated integration guidance. Includes the initial weekly/monthly implementation from `b4a9c86`. |

## Signals development and merge

On **6 November 2026**, commit `167e724` on
`feature/dfut-007-task-signals` changed its package version from **0.1.5.1** to
**0.1.5.2**. That was the development branch version, not a mainline version.
The branch is integrated into main as **0.1.10.1** on **10 November 2026**.

It adds DFUT-007 task-created, note-added, dependency-changed, closed, and
ownership-changed signals, carrying the actor email, task key, and task name.
Dispatch runs after transaction commit, with robust receiver handling so signal
errors cannot undo committed changes. The commit includes API/UI integration and
signal tests. Mainline versions up to **0.1.9.4** do not contain this work;
**0.1.10.1** is the first mainline version that includes it.

## Numbering and history limits

- The earliest committed `pyproject.toml` version is **0.1.2**. Earlier commits
  exist on 2–3 November, but this history does not establish versions 0.1.0 or 0.1.1.
- `b864cbf` says “version 0.1.3” in its subject but does not change package
  metadata; the next version recorded in `pyproject.toml` is **0.1.2.1**.
- `628f475` says “0.1.5” in its subject; its actual package version is **0.1.5.1**.
- No first-parent mainline package versions **0.1.3**, **0.1.4**, **0.1.5**,
  **0.1.8.2**, **0.1.8.3**, **0.1.9.2**, or **0.1.9.3** were found. Skipped
  numbers are not evidence of missing releases.
- This history describes repository snapshots, not confirmation of uploaded
  distributions. The 0.1.10.1 merge also sets `pyproject.toml` to that version.

To reproduce the version markers and inspect a snapshot:

```sh
git log main --first-parent --reverse -p -- pyproject.toml
git log --reverse --oneline PREVIOUS_VERSION_COMMIT..VERSION_COMMIT
git diff --stat PREVIOUS_VERSION_COMMIT VERSION_COMMIT
git show VERSION_COMMIT:pyproject.toml
git merge-base --is-ancestor feature/dfut-007-task-signals main
```
