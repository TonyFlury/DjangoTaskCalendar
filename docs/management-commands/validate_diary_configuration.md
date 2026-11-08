# validate_diary_configuration

[All commands](README.md)

Check that the configured Diary access and ownership groups exist and each
contains at least one user. This is a read-only check; it does not create groups,
assign members, or repair configuration.

```bash
python manage.py validate_diary_configuration
python manage.py validate_diary_configuration --json
python manage.py validate_diary_configuration --help
```

| Option | Effect |
| --- | --- |
| `--json` | Return `valid: true` and a success message as JSON. |

The command validates `DIARY_MANAGER`, `DIARY_USER`, and any groups named in
`DIARY_TASK_OWNER_ROLES`. It uses the configured Django user model. A group member
does not have to be active to satisfy this configuration check; eligibility checks
for individual task operations are separate.

Run it after database migrations and initial group setup, and after changing
configured groups or membership. A missing or empty group, invalid setting, or
database validation failure produces a command error and nonzero exit status.

**Deployment warning:** a successful result describes the database at that moment.
It does not continuously monitor membership or confirm that every task has an
eligible owner. Django startup validates setting values without this database
check. If enabled, [validation middleware](../../Diary/README.md#optional-validation-middleware)
checks groups on each worker's first request and stops checking after success.

If validation fails, check the selected database, apply pending migrations, and
create the required groups and memberships through the host's administration
process. Repeat the command after correcting the problem.
