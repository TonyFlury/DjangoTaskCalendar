# Management command help

Run these commands from a configured Django host project, using its environment
and `manage.py`. The package source repository does not provide a `manage.py`.
Install `Diary`, configure its settings, and apply its migrations first.
Commands use the host's default database; they do not provide a `--database` option.
Use Django's `--settings your_project.settings` option if you need different settings.

| Command | Purpose |
| --- | --- |
| [validate_diary_configuration](validate_diary_configuration.md) | Check configured groups and membership without changing records. |
| [manage_diary_templates](manage_diary_templates.md) | Inspect, create, approve, and delete templates and versions. |
| [manage_diaries](manage_diaries.md) | Inspect, create, apply templates, close, and delete diaries. |
| [transfer_diary_templates](transfer_diary_templates.md) | Export approved template definitions and validate imports. |

## Operator access

**Warning:** administration and transfer commands trust access to the host command
line. They require no Django login or `--actor` argument. Administration can read
every diary, including private tasks, independently of web permissions and host
event scope. Protect terminal output and exported files accordingly.

Writes use the identity `management:operator`; this does not identify the person
running the command. Record operator identity through your deployment procedures
if you need a person-specific audit trail.

Before changing data, confirm the selected settings and database, inspect the
target, and ensure an appropriate database backup is available for permanent deletion.
See the [administration guide](../../Diary/MANAGEMENT_COMMANDS.md) for transaction,
deletion, output, and failure details.

## Help and scripting

```bash
python manage.py help
python manage.py validate_diary_configuration --help
python manage.py manage_diary_templates --help
python manage.py manage_diaries --help
python manage.py transfer_diary_templates --help
```

All four commands accept `--json` to return one JSON value on standard output.
Errors go to standard error with a nonzero exit status. JSON mode does not turn
failures into successful JSON results. UUIDs and dates are strings in JSON.
For administration lists, `--details` (alias `--full`) gives readable metadata,
and `--uuid` adds identifiers to the name-only output. These list options do not
apply to other operations. `--json` cannot be combined with `--details` or `--full`.

Examples use `DIARY_UUID`, template names, milestone names, and file paths as
placeholders. Substitute real values. Template version selectors are integer
numbers within a template, rather than UUIDs.
