# Template and diary administration

Diary provides two operator commands in addition to
`validate_diary_configuration` and `transfer_diary_templates`:

- `manage_diary_templates`: enumerate templates and versions, inspect content,
  create templates and drafts, copy versions, approve drafts, and delete unused versions or templates.
- `manage_diaries`: enumerate instances, inspect their tasks, create instances,
  close diaries, and permanently delete instances.

Run commands through the host project's `manage.py`, using its normal settings
and default database. Apply migration `0009_administrative_deletion` before using
deletion operations. PostgreSQL is required.

## Operator identity and output

Every operation requires `--actor USERNAME`. This must identify an active user in
the configured `DIARY_MANAGER` group, using the configured user model's username
field. Superuser status alone does not replace that group membership.

These are deployment-operator tools. A manager named by an operator can inspect
all diaries in the database, including private personal tasks. Commands do not
derive scope from HTTP requests, sessions, or the host's event access policy.
They do not grant broader access through the web views.

Diary and template lists print one name per line by default. Use `--details` (alias `--full`)
for readable metadata, or `--json` for the full structured list. Add `--uuid` to
show each UUID alongside its name, as `UUID  Name`. It also works with `--details`
or `--full`; JSON already contains UUIDs. This option applies only to `list`. Other operations
write indented JSON, with UUIDs and dates encoded as strings.
JSON lists return arrays; individual records and deletion plans return objects.
Failures use Django's `CommandError` and a nonzero process exit status.
Use each command's `--help` for argument details.

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
version count. It cannot be combined with `--details` or `--full`. These output
switches apply only to `list`. `versions` includes each version's status,
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
It cannot be combined with `--details` or `--full`. These output switches apply only
to `list`. `show` returns the diary and its visible-to-manager task data through the
callable API as JSON. Diary names need not be unique, so instance actions require
an exact `--diary UUID`, available from the detailed or JSON list.

```sh
python manage.py manage_diaries create --name "Summer event" --template "Event preparation" --event-ref "event:17" --milestone event_date=2027-06-27 --milestone bookings_close=2027-06-01 --actor operator
python manage.py manage_diaries close --diary DIARY_UUID --actor operator
```

Creation normally uses the latest approved version. Add `--template-version N` to choose
a particular approved version. Supply every declared milestone through repeated
`--milestone NAME=YYYY-MM-DD` arguments, even when no task uses a declaration.
Missing dates, invalid dates, duplicate inputs, and unknown names are rejected.

An explicit `--event-ref` supports safe retries: identical inputs reuse the diary;
different inputs for the same reference fail. Omitting it creates a fresh reference.
Closure records the actor and time but does not complete outstanding tasks. Repeated
closure preserves the original closure record. Reopening is not supported.

## Deletion

Deletion operates on one explicit target. Without `--yes` it only prints a preview.
`--dry-run` also previews, including when combined with `--yes`. These options apply
only to deletion, not creation or approval.

```sh
python manage.py manage_diaries delete --diary DIARY_UUID --actor operator
python manage.py manage_diaries delete --diary DIARY_UUID --yes --actor operator
python manage.py manage_diary_templates delete-version --template "Event preparation" --template-version 2 --actor operator
python manage.py manage_diary_templates delete-version --template "Event preparation" --template-version 2 --yes --actor operator
python manage.py manage_diary_templates delete --template "Event preparation" --yes --actor operator
```

Preview output includes the exact target, `deleted: false`, and affected counts.
Executed deletion returns `deleted: true`. The selected records are locked and
checked again during execution; a previous preview is not a reservation.

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
