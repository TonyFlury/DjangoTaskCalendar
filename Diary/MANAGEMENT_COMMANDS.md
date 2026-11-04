# Template and diary administration

Diary provides two operator commands in addition to
`validate_diary_configuration` and `transfer_diary_templates`:

- `manage_diary_templates`: enumerate templates and versions, inspect content,
  create templates and drafts, copy versions, approve drafts, and delete unused versions or templates.
- `manage_diaries`: enumerate instances, inspect their tasks, create instances,
  apply a first template, close diaries, and permanently delete instances.

Run commands through the host project's `manage.py`, using its normal settings
and default database. Apply migration `0009_administrative_deletion` before using
deletion operations. PostgreSQL is required.

## Operator identity and output

Template/diary administration and template transfer require `--actor USERNAME`.
Configuration validation does not require an actor. The actor must identify an active user in
the configured `DIARY_MANAGER` group, using the configured user model's username
field. Superuser status alone does not replace that group membership.

These are deployment-operator tools. A manager named by an operator can inspect
all diaries in the database, including private personal tasks. Commands do not
derive scope from HTTP requests, sessions, or the host's event access policy.
They do not grant broader access through the web views.

All Diary management commands use human-readable output by default. Diary and
template lists print one name per line; use `--details` (alias `--full`) for readable
metadata. Add `--uuid` to show each UUID alongside its name, as `UUID  Name`.
These three switches apply only to list operations.

Inspection and lifecycle operations print labelled fields, dates in the project's
time zone, nested task/version information, and explicit deletion previews or
completion messages. Configuration validation and fixture transfer print readable
result messages and fields.

Every command accepts `--json` for scripting, including `show`, `versions`,
`create`, `create-version`, `approve`, `apply-template`, `close`, deletion previews and execution,
configuration validation, and template import/export. JSON output consists of one
JSON value on standard output, without human labels or progress messages. UUIDs and
dates are encoded as strings. Administration lists return arrays and individual
records/deletion plans return objects; validation returns `valid` and `message`;
transfer returns `operation`, `fixture`, `template_count`, `message`, and an import
`dry_run` flag. Fixture files themselves always use Django JSON format, independently
of the command's terminal output format.

`--json` cannot be combined with `--details` or `--full`. JSON list records already
include UUIDs, so `--uuid --json` leaves their schema unchanged. Failures retain
Django's `CommandError` on standard error and a nonzero process exit status.
Use each command's `--help` for argument details.

```sh
python manage.py manage_diaries show --diary DIARY_UUID --actor operator --json
python manage.py manage_diary_templates versions --template "Event preparation" --actor operator --json
python manage.py validate_diary_configuration --json
python manage.py transfer_diary_templates export templates.json --actor operator --json
```

## Templates and versions

Replace `operator`, `Event preparation`, and milestone names with your own values.
Template names are exact, case-insensitive selectors. Version selectors are integer
version numbers within the selected template, not version UUIDs.

```sh
python manage.py manage_diary_templates list --actor operator
python manage.py manage_diary_templates list --uuid --actor operator
python manage.py manage_diary_templates list --details --actor operator
python manage.py manage_diary_templates list --json --actor operator
python manage.py manage_diary_templates versions --template "Event preparation" --actor operator
python manage.py manage_diary_templates show --template "Event preparation" --actor operator
python manage.py manage_diary_templates show --template "Event preparation" --template-version 1 --actor operator
```

`list` prints template names only, one per line, ordered by name. An optional
`--template` filters it to one exact name. An empty selection prints nothing.
Use `--details` (alias `--full`) to display descriptions and all version numbers
and statuses, each version's declared milestones (display label and stable name),
a template-level usage summary, and the names of diaries using each version.
Usage includes both open and closed diary instances, even when only an older version
is referenced. Diary names are listed alphabetically beneath their version;
versions without diaries display `Used by: None`.
Milestone lists include unused required declarations and exclude unrelated catalogue
milestones. Templates without versions and versions without milestones are marked
explicitly. For example:

```text
Event preparation
  Description:   Reusable event tasks
  In use:        Yes (2 diaries)
  Version 1 (approved)
    Milestones:  Event date (event_date), Bookings close (bookings_close)
    Used by:
      - Spring event
      - Summer event
  Version 2 (draft)
    Milestones:  Event date (event_date)
    Used by:     None
```

`--json` retains the original list records: template UUID, name, description, and
version count. It cannot be combined with `--details` or `--full`. The display
switches `--details`, `--full`, and `--uuid` apply only to `list`; `--json` works for
every operation. `versions` includes each version's status,
audit fields, and task, diary, and declared milestone counts. `show` without a
version returns editor data for the highest version, including a draft; with a
version it returns that version's complete tasks, predecessor keys, and milestone
declarations. These reads do not create records.

```sh
python manage.py manage_diary_templates create --template "Event preparation" --description "Event tasks" --actor operator
python manage.py manage_diary_templates create-version --template "Event preparation" --milestone event_date --milestone bookings_close --actor operator
python manage.py manage_diary_templates create-version --template "Event preparation" --copy-version 1 --actor operator
python manage.py manage_diary_templates approve --template "Event preparation" --template-version 2 --actor operator
```

`create` creates an unversioned template. `create-version` allocates the next number
after the current highest version and creates a draft. Without `--copy-version`,
the draft has no tasks and declares the existing catalogue milestones passed through
repeated `--milestone NAME` options. Unknown milestone names are rejected; the
command does not create catalogue identifiers.

`--copy-version N` copies that version's tasks, stable task keys, dependencies,
ownership, and all declarations, including unused required milestones, into a
new draft. It cannot be combined with `--milestone`. Current ownership eligibility
is checked while copying. A failed copy leaves no partial draft.

Use the template editor or callable API to author task content. Use
`transfer_diary_templates` to exchange complete definitions. `approve` approves a
draft through the normal API and is idempotent for an approved version. Existing
diaries remain unchanged by these operations.

## Diary instances

```sh
python manage.py manage_diaries list --actor operator
python manage.py manage_diaries list --uuid --actor operator
python manage.py manage_diaries list --details --actor operator
python manage.py manage_diaries list --json --actor operator
python manage.py manage_diaries list --state open --template "Event preparation" --actor operator
python manage.py manage_diaries list --event-ref "event:17" --actor operator
python manage.py manage_diaries show --diary DIARY_UUID --actor operator
```

`list` prints only diary names, one per line, ordered by name. Duplicate names are
retained; an empty selection produces no output. All output formats support
`--state all|open|closed`, `--template`, and `--event-ref` filters.

`--details` (or `--full`) prints a labelled block for each diary with its UUID,
open/closed status, creation date, source template/version, total/completed/open
task counts, host reference, and closure date when applicable. Dates use Django's
project time zone. For example:

```text
Summer event
  ID:             12345678-1234-5678-1234-567812345678
  Status:         Open
  Created:        04 Nov 2026 12:00 GMT
  Template:       Event preparation (version 1)
  Tasks:          12 total, 3 completed, 9 open
  Host reference: event:17
```

Use `--json` for the original full structured list, including identifiers and counts.
It cannot be combined with `--details` or `--full`. `--details`, `--full`, and `--uuid` apply only
to `list`; `--json` works for every operation. `show` returns the diary and its visible-to-manager task data through the
callable API, with readable output by default and JSON when requested. Diary names need not be unique, so instance actions require
an exact `--diary UUID`, available from the detailed or JSON list.

```sh
python manage.py manage_diaries create --name "Summer event" --template "Event preparation" --event-ref "event:17" --milestone event_date=2027-06-27 --milestone bookings_close=2027-06-01 --actor operator
python manage.py manage_diaries close --diary DIARY_UUID --actor operator
```

A diary does not need a template. To create one independently of a configured
default template, use:

```sh
python manage.py manage_diaries create --name "Summer event" --event-ref "event:17" --without-template --actor operator
python manage.py manage_diaries apply-template --diary DIARY_UUID --template "Event preparation" --milestone event_date=2027-06-27 --milestone bookings_close=2027-06-01 --actor operator
```

Creation with no template selection and no configured `DIARY_TEMPLATE_NAME` also
creates an empty diary. `--without-template` explicitly ignores that setting and
cannot be combined with a template selector or milestone dates. Personal tasks can
be added immediately. Detailed list output shows **Template: Not applied**.

`apply-template` requires an open diary without an applied template. It preserves
all existing tasks, privacy, dates, and completion history. The UUID/name of the
diary stays unchanged. Copies with conflicting task names receive **(template)**
suffixes. Every declared milestone date is required. Annual rules use the diary's
original creation date. The operation is atomic and identical retries do not
produce duplicate tasks; a different template or different dates are rejected
once a template is applied. Applying a template needs no deletion confirmation.
The web manager workflow is described in the [user guide](USER_GUIDE.md#apply-a-template-to-a-diary).

Apply migration `0010_optional_diary_template` before using these operations.
Existing template-backed diaries remain unchanged. Add `--json` to either command
for scripting. Explicitly naming a template during creation still selects its
latest approved version, as described below.

Creation normally uses the latest approved version. Add `--template-version N` to choose
a particular approved version. Supply every declared milestone through repeated
`--milestone NAME=YYYY-MM-DD` arguments, even when no task uses a declaration.
Missing dates, invalid dates, duplicate inputs, and unknown names are rejected.

An explicit `--event-ref` supports safe retries: identical inputs reuse the diary;
different names or conflicting template-backed creation inputs for the same reference fail.
Retrying the original template-free creation after later application returns the
existing diary without detaching its template. Omitting a reference creates a new diary.
Closure records the actor and time but does not complete outstanding tasks. Repeated
closure preserves the original closure record. Reopening is not supported.

## Deletion

Deletion operates on one explicit target. By default the command first displays
the human-readable name, UUID, selected versions where applicable, and affected
record counts. It then asks `Delete the item shown above? [y/N]:`.
Answer `y` or `yes` to delete. Answer `n` or `no`, press Enter, or end input to cancel
without changing records. Invalid answers repeat the question.

Use `--force` to execute without confirmation. `--yes` remains an alias for
compatibility. `--dry-run` only displays a preview and never prompts or deletes,
even when combined with `--force`. These flags apply only to deletion.

JSON-mode deletion never prompts: supply `--json --force` to execute, or
`--json --dry-run` to preview. Omitting both flags in JSON mode fails clearly
instead of waiting for input or performing an implicit delete.

```sh
python manage.py manage_diaries delete --diary DIARY_UUID --actor operator
python manage.py manage_diaries delete --diary DIARY_UUID --dry-run --actor operator
python manage.py manage_diaries delete --diary DIARY_UUID --force --actor operator
python manage.py manage_diary_templates delete-version --template "Event preparation" --template-version 2 --actor operator
python manage.py manage_diary_templates delete-version --template "Event preparation" --template-version 2 --force --json --actor operator
python manage.py manage_diary_templates delete --template "Event preparation" --force --actor operator
```

Human-readable previews identify the exact target, affected counts, and that no
records were deleted; executed deletion prints a completion message. With `--json`,
previews include `deleted: false` and executed deletion returns `deleted: true`.
The command rechecks the target under lock after confirmation. If its identity or
affected counts have changed, it fails and requires a fresh inspection rather
than deleting a different selection. A preview does not reserve the records.

- Diary deletion removes the entire instance, including completed tasks and their
  completion history, open tasks, dependency links, and supplied milestone dates.
  Both open and closed diaries can be deleted. Source templates and other diaries remain.
- Version deletion removes the selected draft or approved version, its tasks,
  dependencies, and declarations. Its parent template and other versions remain.
- Template deletion removes the named template and all its versions and tasks.
- A template or version referenced by any diary cannot be deleted, including when
  the diary is closed. Delete the relevant instances explicitly first if removal is intended.
- Shared catalogue milestone definitions are retained.

Each deletion is atomic. Failure restores the complete target and its related
records. Migration `0009` allows cleanup of dependencies, milestone dates, and
declarations only when their parent is being removed in the same transaction;
normal edits to surviving diaries and approved version declarations remain blocked.
The commands never disable database triggers.

Deletion is permanent. The host may retain external diary UUIDs or host references;
these commands do not modify host business records. Arrange any host cleanup in
the host project. Deleting the latest approved version can change which remaining
version the default selection returns. Removing the highest version also allows
its number to be allocated again by a later version creation.

Successful deletion logs actor and target identifiers to `Diary.management` after
commit. Configure a logging handler if those messages must be retained; the command
does not create a separate persistent deletion audit table.

Verification is in `Diary/tests/test_administration_commands.py`. The existing
live-dependency, milestone, and template-declaration tests verify that ordinary
immutability rules remain enforced.

## Failure messages

Create and delete failures identify the operation and selected name or UUID (and
version number when supplied), followed by a clear reason. Examples include a
name already in use, missing required milestone dates, a nonexistent target,
diaries still referencing a template version, or a target changed during
confirmation. Failed deletion leaves the target intact. Database connection failures advise checking connectivity and migrations. Integrity
errors preserve the PostgreSQL reason and available details, table, constraint,
and SQLSTATE. A foreign-key failure identifies the referencing table/constraint
and key in the database detail rather than hiding them behind a generic blocker.
A legacy Diary protection-trigger failure points to migration
`0009_administrative_deletion` and the commands to check/apply it.

Errors are reported as Django `CommandError` messages on standard error, with a
nonzero exit status in both text and JSON modes. JSON mode does not replace errors
with a success object. A declined confirmation is a cancellation, not an error.
