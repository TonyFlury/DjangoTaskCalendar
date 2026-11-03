# Independent diary creation UI

Requirement identifier: **DFUT-001**.
Status: future requirement, not implemented.
Release: not assigned.

This document supports [DFUT-001 in the Diary checklist](../../Diary/TODO_V1.md#future-requirements).
It does not add work to V1.

## Confirmed requirement

An authorized user can independently create a diary instance from a template through Diary's own UI.
The UI prompts for the relevant milestone dates.
It does not require a Garage Sale event or another host business record.
The existing project authentication and diary access policy still apply.

## Existing API

[Diary/api.py](../../Diary/api.py) provides the implemented creation entry points:

| Existing technical name | Purpose |
| --- | --- |
| `DiaryAPI.create_diary()` | Create a diary through a caller context. |
| `DiaryInstance.create()` | Create a diary directly through the instance factory. |
| `DiaryTemplateVersion.required_milestones()` | Read named milestones used by the selected template version. |
| `Actor.calendar_keys` | Identify the diary instances the host permits the caller to access. |
| `event_ref` | Existing API argument for a stable, unique caller reference. |

Creation selects an approved template and copies task rules, owners, stable keys, and dependencies in one transaction.
It validates configured ownership groups against current membership.
Repeated identical inputs with the same caller reference reuse the existing diary key.
Unspecified milestone dates are permitted and produce tasks with no calculated date.
The returned reference does not automatically expand `Actor.calendar_keys`.

Template metadata reads currently require DiaryManager access.
Creation permits configured DiaryUsers and DiaryManagers through the trusted callable API.
Those existing permissions do not determine the future UI's final authorization rule.

## Proposed workflow

The following workflow is a proposal, not an implemented interface.

1. Authenticate the user.
2. Check permission to use the independent creation page.
3. Show approved templates available under that permission.
4. Let the user select a template version.
5. Prompt for a diary name.
6. Read the selected version's named milestones.
7. Prompt for each relevant milestone date using its label.
8. Show the selected version, diary name, and milestone dates for confirmation.
9. Submit the confirmed values through the existing creation API.
10. Confirm the result and provide permitted navigation to the new diary.

Read requests must not create a diary.
The server must recheck permission during submission.
Browser writes require CSRF protection.
Ownership validation failures must preserve entered values and explain which groups need repair.

## Proposed technical behavior

Use the selected approved version key for the confirmed submission.
Do not silently substitute a newer template version after the user reviews the form.
Use the version's milestone names as API keys and its labels as visible prompts.
Use the creation API to calculate fixed dates from the diary creation date.
Do not request a diary year.

Generate a stable internal caller reference for this independent workflow.
Keep it unchanged across retries of the same submission.
Do not require the user to enter an API reference or create a host event record.
The reference must not collide with references supplied by other callers.

Use the creation API's transaction and ownership checks.
Do not copy template tasks or dependencies in the view.
Keep the new diary key subject to the project's normal access policy.
A successful creation must not grant unrelated diary access.

Use the documented `.diary` namespace and stable `diary-` classes for all controls and states.
Document implemented classes in [Diary/README.md](../../Diary/README.md).
No new class names or route names are established by this proposal.

## Open decisions

| Decision | Detail |
| --- | --- |
| Authorized role | Decide whether the page is available to DiaryManagers only or to specified DiaryUsers. |
| Template discovery | Define permitted template choices and milestone reads if ordinary DiaryUsers can create diaries. |
| Missing dates | Decide whether the UI requires every milestone date or permits the API's unset-date behavior. |
| New diary access | Define how the host permits access to an independently created diary key. |
| Caller reference | Define the internal reference namespace and retry-state storage. |

Template discovery for DiaryUsers must not grant template editing or expose unauthorized template information.
These decisions do not change the implemented API or its current permissions.

## Completion conditions

Verify permitted and denied users on both reads and submissions.
Verify the correct prompts for different approved templates.
Verify diary names, fixed-date calculations, milestone dates, and the selected version.
Verify failed submissions without partial diary records.
Verify repeated submissions without duplicate diaries.
Verify that creating a diary requires no host business record.
Verify permitted access to the result without an expanded unrelated diary scope.
Record implementation files, exact symbols, and verification references when this future item is implemented.

## Review limits

This document records a confirmed future requirement and a proposed implementation.
It does not change application code, migrations, or deployed services.
ASD-STE100 Issue 9 was available locally.
A full dictionary and technical-name review remains necessary.
This document does not claim full ASD-STE100 compliance.
