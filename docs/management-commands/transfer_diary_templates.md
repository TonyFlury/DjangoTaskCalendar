# transfer_diary_templates

[All commands and operator access warning](README.md)

Exchange approved template definitions between deployments using validated Django
JSON fixtures. This command does not transfer live diaries or restore a database.

```bash
python manage.py transfer_diary_templates export FIXTURE_PATH [options]
python manage.py transfer_diary_templates import FIXTURE_PATH [options]
python manage.py transfer_diary_templates --help
```

| Option | Applies to | Meaning |
| --- | --- | --- |
| `--template NAME` | export | Select an exact, case-sensitive template name. Repeat to select several; omit to export all templates. |
| `--person-map SOURCE_EMAIL=LOCAL_EMAIL` | import | Map an exported person owner to a destination email. Repeat for multiple people. |
| `--new-version` | import | Permit a new approved version when an existing template's content differs. |
| `--dry-run` | import | Run validation and import, then roll back all database changes. |
| `--json` | Both | Return the operation result as JSON. The fixture itself is always JSON. |

## Export on the source deployment

```bash
python manage.py transfer_diary_templates export preparation.json --template "Preparation"
```

The export contains each selected template's latest approved version, tasks,
dependencies, and referenced milestone definitions. Drafts, older versions, live
diaries, notes, users, and groups are excluded. A selected template with no
approved version causes failure. Existing output files are never overwritten.

**Data warning:** fixtures contain task content and person-owner email addresses.
Store and transfer them using access appropriate to that information. An export
is not a complete backup of task history or the source database.

## Validate on the destination deployment

Create the configured groups and required users before importing. The command
does not create users, groups, or memberships. Validate using the same destination
settings and mappings that you intend to use for the actual import:

```bash
python manage.py transfer_diary_templates import preparation.json --dry-run
python manage.py transfer_diary_templates import preparation.json --person-map alex@old.example=alex@new.example --dry-run
```

Person owners are matched by email, without letter-case differences, to exactly
one active destination user with eligible Diary access. Missing or ambiguous
matches fail. Ownership group names must be configured on the destination and
have members. Milestone names with conflicting labels or descriptions fail.
Graph, date, ownership, and model validation also apply.

## Import

```bash
python manage.py transfer_diary_templates import preparation.json
```

Retain any `--person-map` arguments used for the successful dry run. Import is
atomic: one failure rolls back the whole fixture. Identical approved content is
skipped. Different content for an existing template requires explicit consent:

```bash
python manage.py transfer_diary_templates import preparation.json --new-version --dry-run
python manage.py transfer_diary_templates import preparation.json --new-version
```

**Import warning:** without `--dry-run`, valid input is saved immediately with no
confirmation prompt. New definitions are approved. `--new-version` can therefore
change the latest approved template used for future diary creation. Review the
fixture, destination, owner mappings, and dry-run result before executing it.
Existing diary copies and previous template versions remain unchanged.

Import uses fresh destination database identifiers and local version numbering,
while retaining stable task keys. It does not restore source approval history or
database primary keys. Use this command rather than `loaddata` for template
transfers requiring Diary's ownership and dependency validation.

See the [transfer reference](../../Diary/README.md#template-fixture-transfer)
for matching rules and validation details.
