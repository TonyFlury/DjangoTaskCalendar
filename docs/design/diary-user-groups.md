# Multiple Diary user groups

Requirement identifier: **DFUT-002**.
Status: confirmed future requirement, not implemented.
Release: not assigned.

This document supports [DFUT-002 in the Diary checklist](../../Diary/TODO_V1.md#future-requirements).
Implementation can occur in a future release.

## Confirmed requirement

The technical setting `DIARY_USER` must support a set of Django group names.
Membership in any configured group must give the user DiaryUser capabilities.
Users must not need membership in every configured group.
This requirement does not grant DiaryManager capabilities.
The permitted diary keys must still limit access to individual diaries.

The user confirmed that Garage Sale task owners also belong to the `ExecMember` group.
The current setting `DIARY_USER = 'ExecMember'` therefore covers those owners.
Other applications can have ownership groups with no common members or shared access group.
Those applications must be able to include all necessary groups in `DIARY_USER`.
Diary must not require a common parent group or an application-specific membership rule.

The technical setting `DIARY_TASK_OWNER_ROLES` identifies groups that can own tasks.
Group ownership and Diary access remain separate configuration purposes.
The new requirement lets an application give Diary access to members of separate ownership groups.

## Current implementation

`Diary.roles.access_groups()` accepts one group name for each access setting.
It rejects collection values for `DIARY_USER`.
`Diary.roles.validate_access_groups()` checks group existence and current membership.
`Diary.apps.DiaryConfig.ready()` calls these checks during ordinary startup.
The current API and ownership checks also expect one DiaryUser group name.

The current setting format remains in use until this requirement is implemented.
No application code, settings, migrations, or deployed services change for this deferred requirement.

## Proposed implementation

The following changes are proposals, not implemented interfaces.

Retain support for an existing single group name in `DIARY_USER`.
Also accept a nonempty collection of group names.
Convert both input forms to one internal set before checking permissions or ownership eligibility.
Keep `DIARY_MANAGER` as one group name.
Retain the existing rule that managers have DiaryUser capabilities.

Validate each collection element as a nonempty group name without surrounding spaces.
Check each configured group's existence and membership through Django's configured user model.
Keep distinct errors for invalid values, missing groups, empty groups, and database failures.
Identify `DIARY_USER` and the affected group names in each applicable error.
Retain the existing database setup and repair command exceptions.

Review these existing technical names during implementation:

| File | Existing technical names | Required review |
| --- | --- | --- |
| `Diary/roles.py` | `access_groups`, `validate_access_groups` | Setting values, group existence, and membership checks. |
| `Diary/apps.py` | `DiaryConfig.ready` | Startup checks and setup exceptions. |
| `Diary/api.py` | `DiaryAPI.permission_groups`, `_allowed`, `_require` | Public results and access through any configured user group. |
| `Diary/entry_mapping.py` | `validate_entry_owner` | Person eligibility through the configured access groups. |
| `Diary/forms.py` | `TemplateTaskFormSet.__init__` | Eligible person choices across the configured groups. |
| `Diary/views.py` | `DjangoOwnerDirectory.person_in_groups` | Ownership checks without a fixed host group. |

## Open decisions

Select the supported collection types before implementation.
Define the public result format of `DiaryAPI.permission_groups()` and the internal result of `access_groups()`.
Decide whether startup checks must also detect task owners without Diary access.
Such a check must distinguish group-name coverage from current membership coverage across different groups.
Do not assume that an ownership group must have the same name as an access group.

## Completion conditions

Verify access for users in either of two groups with no common members.
Verify denial for users outside every configured user and manager group.
Verify manager inheritance, diary scope, and person ownership eligibility.
Verify existing single-group settings and applications without host business models.
Verify invalid collections, invalid elements, missing groups, empty groups, and database failures.
Verify startup command exceptions and collection handling in every consumer listed above.
Run database tests against a separate PostgreSQL test database.
Update the API guide, deployment instructions, and exact verification references when implementation is complete.

## Review limits

This document records a future requirement and implementation proposals.
ASD-STE100 Issue 9 was available locally.
A full dictionary and technical-name review remains necessary.
This document does not claim full ASD-STE100 compliance.
