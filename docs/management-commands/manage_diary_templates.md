# manage_diary_templates

[All commands and operator access warning](README.md)

Manage template definitions and numbered versions in the host's default database.

```bash
python manage.py manage_diary_templates OPERATION [options]
python manage.py manage_diary_templates --help
```

| Operation | Required arguments | Behavior |
| --- | --- | --- |
| `list` | None | List template names, optionally filtered by `--template`. |
| `versions` | `--template NAME` | List versions, status, audit fields, and counts. |
| `show` | `--template NAME` | Show the highest version, including a draft; optionally select a version. |
| `create` | `--template NAME` | Create a template without a version or tasks. |
| `create-version` | `--template NAME` | Create the next numbered draft, optionally copied from a version. |
| `approve` | `--template NAME --template-version N` | Approve a version through the callable API. |
| `delete-version` | `--template NAME --template-version N` | Permanently delete one unused version. |
| `delete` | `--template NAME` | Permanently delete a template and all its versions. |

| Option | Applies to | Meaning |
| --- | --- | --- |
| `--template NAME` | All | Exact template name, matched without letter-case differences. |
| `--template-version N` | show, approve, delete-version | Integer version number within the selected template. |
| `--copy-version N` | create-version | Copy tasks, stable task keys, dependencies, ownership, and used milestones into a new draft. |
| `--milestone NAME` | create-version | Declare an existing catalogue name on an empty draft; repeat as needed. Cannot accompany `--copy-version`. |
| `--description TEXT` | create | Initial description. |
| `--uuid` | list | Include template UUIDs beside names. |
| `--details`, `--full` | list | Show descriptions, versions, milestone requirements, and diary usage. |
| `--json` | All | Structured output. |
| `--dry-run` | delete, delete-version | Preview deletion without prompting or changing records. |
| `--force`, `--yes` | delete, delete-version | Delete without interactive confirmation. |

## Inspect and create

```bash
python manage.py manage_diary_templates list --details
python manage.py manage_diary_templates versions --template "Preparation"
python manage.py manage_diary_templates show --template "Preparation" --template-version 1 --json
python manage.py manage_diary_templates create --template "Preparation" --description "Reusable event tasks"
python manage.py manage_diary_templates create-version --template "Preparation"
python manage.py manage_diary_templates create-version --template "Preparation" --copy-version 1
```

Without `--copy-version`, a new draft has no tasks. `--milestone` does not create
catalogue definitions; unknown names are rejected. Approval derives actual
milestone requirements from task usage. Author tasks using the web template
editor, callable API, or [validated fixture transfer](transfer_diary_templates.md).

**Warning:** `create-version` creates another draft on each successful invocation;
it is not a safe-retry operation. Inspect existing versions before retrying.
Copying rechecks current ownership eligibility and rolls back a failed copy.

## Approve

```bash
python manage.py manage_diary_templates approve --template "Preparation" --template-version 2
```

**Approval warning:** approval takes effect immediately without confirmation or
dry-run support. An approved version can be selected for future diaries; if it
is the highest approved version, it becomes the default approved selection.
Inspect tasks, dependencies, owners, and required dates first. An approved
version cannot be edited in place: create a new draft for later changes.
Existing diary copies are preserved. Repeated approval is idempotent.

## Delete

```bash
python manage.py manage_diary_templates delete-version --template "Preparation" --template-version 2 --dry-run
python manage.py manage_diary_templates delete-version --template "Preparation" --template-version 2
python manage.py manage_diary_templates delete --template "Preparation" --dry-run
```

**Permanent deletion warning:** version deletion removes its tasks, dependencies,
and milestone declarations. Template deletion removes every version and its
content. There is no undo. Shared catalogue milestones remain.

Deletion is blocked if any diary references the selected template or version,
including closed diaries. Review usage with `list --details` first. Deleting the
latest approved version can change the default version for future creation.
Deleting the highest version allows that version number to be reused later.

The command previews and prompts by default; Enter cancels. `--force` bypasses
confirmation. `--dry-run` never deletes, including with `--force`. JSON deletion
requires `--json --dry-run` to preview or `--json --force` to execute.
See the [deletion reference](../../Diary/MANAGEMENT_COMMANDS.md#deletion) for
locking, audit logging, and related-record behavior.
