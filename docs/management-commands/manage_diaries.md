# manage_diaries

[All commands and operator access warning](README.md)

Inspect and administer diary instances in the host's default database.

```bash
python manage.py manage_diaries OPERATION [options]
python manage.py manage_diaries --help
```

| Operation | Required arguments | Behavior |
| --- | --- | --- |
| `list` | None | List diary names; optionally filter the results. |
| `show` | `--diary UUID` | Show diary details and tasks, including private tasks. |
| `create` | `--name NAME` | Create a diary, optionally using an approved template. |
| `apply-template` | `--diary UUID --template NAME` | Apply the first template to an open diary without one. |
| `close` | `--diary UUID` | Close a diary while preserving its records. |
| `delete` | `--diary UUID` | Permanently remove a diary and its related records. |

| Option | Applies to | Meaning |
| --- | --- | --- |
| `--diary UUID` | show, apply-template, close, delete | Select the exact instance; names need not be unique. |
| `--state all\|open\|closed` | list | Filter by closure state; default `all`. |
| `--template NAME` | list, create, apply-template | Filter by template or select a template to copy. |
| `--template-version N` | create, apply-template | Select an approved version; requires `--template`. Otherwise use the latest approved version. |
| `--name NAME` | create | Diary display name. |
| `--event-ref REF` | list, create | Filter by host reference or supply an explicit creation retry key. |
| `--milestone NAME=YYYY-MM-DD` | create, apply-template | Supply a required milestone date; repeat for multiple names. |
| `--without-template` | create | Ignore the configured default template; cannot be combined with template selectors. |
| `--uuid` | list | Include UUIDs beside names. |
| `--details`, `--full` | list | Include dates, template, state, and task counts. |
| `--json` | All | Structured output. |
| `--dry-run` | delete | Preview only; never prompt or delete, even with `--force`. |
| `--force`, `--yes` | delete | Execute without interactive confirmation. |

## Inspect and create

```bash
python manage.py manage_diaries list --state open --details
python manage.py manage_diaries show --diary DIARY_UUID --json
python manage.py manage_diaries create --name "Summer event" --event-ref "event:17" --without-template
python manage.py manage_diaries create --name "Event preparation" --event-ref "event:18" --template "Preparation" --milestone event_date=2027-06-27
```

**Creation warning:** omitting `--event-ref` creates a new diary on each invocation.
Use the same explicit reference and identical inputs for safe retries. Conflicting
inputs for an existing reference fail. Without an explicit template selection,
creation uses `DIARY_TEMPLATE_NAME` if configured; use `--without-template` to
guarantee an empty diary. Empty diary creation does not retain milestone inputs.

## Apply a template

```bash
python manage.py manage_diaries apply-template --diary DIARY_UUID --template "Preparation" --milestone event_date=2027-06-27
```

Existing tasks and history are preserved. Conflicting copied names receive a
`(template)` suffix. All required milestone dates must be supplied. Annual rules
use the diary's original creation date. Identical retries are safe.

**Warning:** there is no command to detach or replace an applied template.
Inspect the selected template version before applying it. This operation changes
data immediately and has no dry-run or confirmation prompt.

## Close or delete

```bash
python manage.py manage_diaries close --diary DIARY_UUID
python manage.py manage_diaries delete --diary DIARY_UUID --dry-run
python manage.py manage_diaries delete --diary DIARY_UUID
```

**Closure warning:** closing takes effect immediately with no prompt. It does not
complete outstanding tasks. Reopening is not supported. Closed diaries remain
readable, and task notes can still be added under the normal note permissions.

**Permanent deletion warning:** deletion removes open and completed tasks, notes,
completion history, dependencies, and diary milestone dates. It accepts both open
and closed diaries. There is no undo. Source templates and other diaries remain,
and host business records or stored references are not cleaned up automatically.

Deletion previews the target and asks for confirmation by default; Enter cancels.
Use `--force` only after inspecting the target. JSON deletion never prompts:
use `--json --dry-run` to preview or `--json --force` to execute. A preview does
not reserve records; the command rechecks the target before deleting it.
