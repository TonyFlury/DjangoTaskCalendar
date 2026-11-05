# Host page integration

Diary owns the page content and its default formatting.
The host owns its document shell, navigation, authentication, and permitted Diary scope.
Use package partials directly. Do not copy their markup into the host project.

## Include a partial in a host page

The host view must supply the context required by the selected Diary partial.
The authenticated package views can prepare that context and render a host template.
For example, configure `PersonalDiaryView` with the host template name:

```python
PersonalDiaryView.as_view(
    template_name="host/diary.html",
    extra_context={
        "diary_key": current_diary_key,
        "permitted_diary_keys": (current_diary_key,),
    },
)
```

The host must derive `current_diary_key` from its trusted records.
This example uses the package's default navigation routes.
The host template includes the content directly:

```django
{% extends "host/base.html" %}
{% load static %}
{% block extra_styles %}
    {{ block.super }}
    <link rel="stylesheet" href="{% static 'Diary/styles/diary.css' %}">
{% endblock %}
{% block content %}
    {% include "Diary/partials/personal_diary.html" %}
{% endblock %}
```

Replace the example template and block names with the host names.
The host base supplies the header, sidebar, and document elements.
The package partial supplies the Diary content without another document shell.
Load `Diary/styles/diary.css` once in the host shell.
Load `Diary/scripts/template_editor.js` when the host includes the template editor partial.

## Select a base for complete package pages

The complete package pages accept the context value `diary_base_template`.
Its default is `Diary/base.html`.
Set it to the host shell when the host delegates rendering to a complete package page.

```python
extra_context = {
    "diary_base_template": "host/diary_base.html",
    "diary_key": current_diary_key,
    "permitted_diary_keys": (current_diary_key,),
}
```

The host shell must provide `diary_content` for the package content block.
It can also provide `diary_title`, `diary_styles`, `diary_extra_styles`, `diary_head`, and `diary_scripts`.
The template editor uses `diary_scripts` to load its JavaScript.
The host can map these blocks into its normal base template blocks.
No override of `Diary/base.html` is necessary.

## Configure navigation and form fields

The optional context dictionary `diary_ui` controls rendered navigation.
Its absence preserves the existing standalone behavior.

| Key | Default | Purpose |
| --- | --- | --- |
| `trusted_scope` | False | Omit Diary identifier query values and filter selectors when the host supplies scope. |
| `selection_url` | Absent | Enable task and template selection through a host POST endpoint. |
| `task_detail_url` | Current path for task links | Supply the task detail and reload location for host navigation. |
| `form_fields` | Empty | Add escaped hidden fields to selection and edit forms. |

For fixed host URLs, supply values from the host view:

```python
extra_context["diary_ui"] = {
    "trusted_scope": True,
    "selection_url": reverse("Diary:select"),
    "task_detail_url": reverse("Diary:task-detail"),
    "form_fields": {"host_state": signed_state},
}
```

The example names `Diary:select` and `signed_state` belong to the host interface.
Diary does not provide a selection endpoint or a signing policy.
The host must keep the named navigation routes used by the selected package partials.
The host must validate its signed state before it delegates an edit request.
These options change rendering. They do not grant access or replace server validation.
Continue to supply trusted `diary_key` and `permitted_diary_keys` values.

The package renders two hidden selection forms when `selection_url` is present.
Task buttons send `selection=task` and `entry_key`.
Template buttons send `selection=template` and `template_name`.
Each request also includes CSRF protection and the configured `form_fields`.
The host endpoint must authorize the selected record and retain its trusted selection state.
It must redirect to the corresponding fixed page URL.

The package uses `diary-select-task` and `diary-select-template` as form association IDs.
These IDs connect buttons to forms. They are not styling selectors.
Include each complete content partial once per page when POST selection is enabled.
The personal, manager, task creation, and template list partials include their selection forms automatically.
For a low-level `task_list.html` or `manager_tasks.html` include, add `Diary/partials/selection_forms.html` once outside other forms.

Use `form_fields` for additional host state only.
Do not use reserved Diary field names, `diary_target`, or `csrfmiddlewaretoken` as host field names.
Field names and values remain HTML-escaped.
The package does not interpret these additional values.
Task recovery, date changes, completion, task creation, and template saves all retain these fields.

## Styling and verification

Existing component classes remain available.
POST navigation uses buttons with the existing task and template link classes.
The package adds these classes:

| Class | Purpose |
| --- | --- |
| `diary-selection-form` | Hidden task or template selection form. |
| `diary-selection-kind` | Hidden selection type. |
| `diary-host-field` | Additional hidden host field. |

No CSS variables are added by this interface.
Verification is in `Diary/tests/test_host_embedding.py`, class `HostEmbeddingTests`.
The host must also test its selection endpoint, authorization checks, and signed state validation.

Language review limit: The full ASD-STE100 Issue 9 dictionary review is not complete.

## Template save navigation

`TemplateEditorView` owns all template form and task formset processing.
Hosts must delegate POST requests to that view.
Override `get_success_url(*, result)` to change navigation after a successful save.
The hook receives a `DiaryViewResult`; `result.template_name` identifies the saved template. Use `on_success(*, result)` to retain host selection and `get_success_url(*, result)` to return a fixed URL.
The package calls the hook after it saves the approved version.
The default hook returns the existing named template editor URL.
The hook does not receive forms or change template validation.
Verification: `Diary/tests/test_template_editor.py`: `TemplateEditorTests.test_host_success_hook_delegates_all_form_processing`.

## Template editor context

`TemplateEditorView` and `TemplateCreateView` support Django's `ContextMixin` and
`get_context_data(**kwargs)`. Host mixins and parent views can extend context using
`super().get_context_data(**kwargs)` without replacing Diary's GET/POST handlers.

```python
from Diary.views import TemplateEditorView

class HostTemplateEditor(TemplateEditorView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['host_navigation'] = build_host_navigation(self.request.user)
        selected = self.request.session.get('selected_diary_template')
        if selected:
            context['template_name'] = selected
        return context
```

`build_host_navigation` is a host-provided function. Session selection is optional
host code; Diary does not read that session key itself. Template selection does not
grant manager access.

Context is resolved once per request after manager authorization and before Diary
selects a template or builds forms. The hook can access `self.request`, `self.kwargs`,
and `self.api`, but Diary's `self.data` and selected template are not initialized yet.
Return a dictionary and call `super()` to preserve parent context and `extra_context`.
Use cooperative Django context mixins/parent views when composing multiple bases.

The resolved context reaches the chooser, editor, creation page, validation errors,
and server-side task-row/milestone refreshes. Diary supplies its own form and template
metadata keys afterwards, so host context cannot replace validated package forms.
A context `template_name` participates in the same conflict checks as URL/path and
view-attribute selections; conflicting selections return HTTP 400. Creation views
reject a selected template, including one supplied by inherited context.

## Empty diaries and template application

Create a diary through `DiaryAPI.create_diary(..., without_template=True)` before
registering its UUID in the host's records and permitted scope. Users can then
create private tasks without any template. Reads do not create a missing diary;
a missing/unauthorized UUID must not be treated as permission to create one.

For managers, register `TemplateApplyView` with the same trusted scope policy as
`ManagerDiaryView`. It accepts `diary_key` from trusted context or the normal GET
selector. Configure the manager context's `template_apply_url` (full URL) or
`template_apply_url_name` (route name) for host navigation. The application page
can extend `diary_base_template`, or a host template can include
`Diary/partials/template_apply.html` with its prepared context. The view uses CSRF-protected POST requests
to choose an approved version and apply it; it requires
dates for milestones used by template tasks and preserves personal work. Override
`get_success_url(*, result)` to return a fixed host page after success.

## Consistent write-view API

`TemplateCreateView`, `TemplateEditorView`, `TemplateApplyView`, `TaskCreateView`,
and `TaskDetailView` share the public `DiarySuccessMixin` contract from
`Diary.view_api`. Read pages and write pages support cooperative
`get_context_data(**kwargs)`. No host override of `dispatch`, `get`, or `post` is
needed to supply trusted context or receive save results.

| Hook | Purpose |
| --- | --- |
| `get_context_data(**kwargs)` | Call `super()` and add host context and trusted selections. |
| `on_success(*, result)` | Record a successful Diary operation in the host. |
| `get_success_url(*, result)` | Return the redirect destination; default honors `success_url`. |
| `success_response(*, result)` | Return the complete response; default calls `on_success` once, then redirects to `get_success_url`. |

`success_url` accepts a URL path or a named URL that needs no arguments. For
variable destinations, override `get_success_url`. Keep selection updates in
`on_success`, so computing a destination has no side effects.

```python
from Diary.views import TaskCreateView, TaskDetailView

class HostDiaryPolicy:
    success_url = '/work/diary/'

    def get_diary_keys(self):
        return permitted_diary_keys(self.request.user)  # Host authorization policy.

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selection = current_host_selection(self.request)  # Trusted host records/state.
        context['diary_key'] = selection.diary_key
        if selection.entry_key is not None:
            context['entry_key'] = selection.entry_key
        context['diary_base_template'] = 'host/diary_base.html'
        return context

    def on_success(self, *, result):
        remember_host_selection(self.request, result)  # Host chooses storage/lifetime.
        super().on_success(result=result)

class HostTaskCreate(HostDiaryPolicy, TaskCreateView):
    pass

class HostTaskDetail(HostDiaryPolicy, TaskDetailView):
    pass
```

The three example functions are host code. Register these subclasses at the host's
fixed creation/detail paths. `TaskDetailView` accepts `entry_key` from a path
argument, view attribute, or trusted context. Diary keys use the normal trusted
context/path/attribute selectors. Conflicting selections return HTTP 400. Selecting
a record never grants access: current membership, permitted diary keys, ownership,
and concurrency checks still apply. Register all destination views with the host's
scope policy too; a redirect does not carry authorization forward.

### Save results

`Diary.view_api.DiaryViewResult` is an immutable dataclass. Its fields are
`operation`, `diary_key`, `entry_key`, `template_name`, and `template_version_key`.
Keys are `uuid.UUID` objects; identifiers unrelated to the operation are `None`.

| Operation | Identifiers supplied |
| --- | --- |
| `template_created`, `template_saved` | Template name and newly saved version key. |
| `template_applied` | Diary key, template name, and applied version key. |
| `task_created` | Diary and task entry keys. If also saved to a template, template name and newly saved version key. |
| `task_date_updated`, `task_owner_updated` | Diary and task entry keys. |
| `task_completed`, `task_chain_completed` | Diary and selected task entry keys. |

For chain completion, `entry_key` identifies the selected task, not a list of all
completed predecessors. Query the callable API if the host needs the resulting
state. A result describes a successful operation, including a successful idempotent
retry; it is not an exactly-once event delivery mechanism.

Hooks run after Diary's save block succeeds, before the response is returned. GET,
chooser/refresh actions, invalid forms, denied access, and failed saves do not call
them. Host hook exceptions propagate rather than being presented as Diary form
validation failures. The Diary save may already have succeeded at that point.
When a host uses an outer transaction or `ATOMIC_REQUESTS`, final commit still
belongs to that outer transaction. Schedule external side effects with
`transaction.on_commit()` and handle retries appropriately.

To return JSON instead of redirecting:

```python
from dataclasses import asdict
from django.http import JsonResponse

class HostTaskJSON(HostDiaryPolicy, TaskCreateView):
    def success_response(self, *, result):
        self.on_success(result=result)
        return JsonResponse(asdict(result))
```

An overridden `success_response` owns notification and response construction;
call `on_success` exactly once if that behavior is required. This changes successful
responses only; ordinary validation errors still render the package form.

### Clean URLs and safe form targets

Successful package redirects contain no result query parameters. Defaults use
named paths scoped by diary/task UUIDs (`diary-personal`, `diary-manager`,
`diary-task-create`, `diary-task-detail`, and `diary-template-apply` in the `Diary`
namespace). Template saves use the named template editor path. Hosts wanting
identifier-free URLs should set `success_url` or override `get_success_url`.
The package does not persist the host's selected diary/task/template in a session.

Package write forms post to the current path without its query string. They carry
`diary_target`, a signed, user-bound hidden field containing the displayed target
identifiers. The signature grants no permission. Diary rechecks scope and current
permissions on submission and rejects mismatches with current host selection.
For fixed-path task detail POSTs, this token is mandatory; path-selected legacy
forms remain supported. This protects against edits crossing targets when two
browser tabs share host selection state. CSRF and revision/blocker checks remain
required. Preserve `diary_target` when replacing a package form; the shared
`Diary/partials/form_fields.html` includes it automatically. Do not override it
through `diary_ui.form_fields`. Its styling class is `diary-form-target`.

Legacy GET selectors remain accepted, and read-only search/filter controls still
use query parameters. Hosts can enable POST selection navigation with `diary_ui`
as described above. Write results are passed directly to hooks, so wrappers need
no redirect inspection or query-parameter interception.

The default `on_success` adds a standard Django **Task added.** message after task
creation. For that notice, enable `django.contrib.messages`, its middleware and
template context processor, and render messages in the host shell. The package
base offers a `diary_messages` block. Message storage is optional; lack of message
middleware does not prevent saves. Hosts may override notification handling. This
uses Django's configured message storage, independently of host selection state.

### Updating an existing wrapper

Replace `get_success_url(template_name=...)` and
`get_success_url(diary_key=...)` overrides with the shared keyword-only
`get_success_url(*, result)` signature. Read identifiers from `result` and move
selection updates into `on_success`. Remove code that extracts `added` or
`diary_key` from a redirect's query string. The `added` GET flag no longer produces
a success notice. Configure the new scoped destinations with your authorization
policy, or explicitly return your existing fixed host URLs. No database migration
is required for this interface change.

Verification: `Diary/tests/test_view_host_api.py`, plus the template editor, task
creation/editing, optional-template, and host embedding suites.

Explicit `task_detail_url_name` routes receive `entry_key` as their only URL
argument and must supply the diary through trusted host context. Explicit
`template_apply_url_name` routes receive no URL arguments and likewise supply
trusted diary selection themselves. Diary does not append selectors to these
host destinations. Use `selection_url` for POST-based task selection when the
host also wants to hide task identifiers during navigation.

## Host milestone catalogue

Template tasks choose directly from the catalogue registered by the host. No
manager declaration step is needed. Hosts can continue passing their entire
milestone-date mapping when creating a diary or applying a template. Diary
validates dates used by that version and silently ignores unused keys and values.
Existing integration signatures remain supported. Apply migration
`0011_derive_template_milestones`; existing diary snapshots stay unchanged.

## Task note integration

Apply migration `0012_task_notes`. The existing task detail partial now displays
notes and allows assigned users and managers to append notes, including on completed
tasks and closed diaries. Each POST uses `action=add_note`, `text`, and `note_key`,
plus the normal CSRF and signed `diary_target` fields. Do not suppress the notes
section just because a task or diary is closed.

The shared success hooks receive operation `task_note_added`, with `diary_key` and
`entry_key`. `DiaryViewResult` keeps its existing fields. The default response
redirects to the clean task detail path. Custom `success_response` implementations
work as for other task actions. Notes are available through `DiaryInstance.notes()`
and the `notes`/`can_add_note` fields of `DiaryInstance.task()`.

Author, owner and completion labels use First Name Last Name and `deleted user`
for unresolved users/names; email login names are not a display fallback. Internal
user references remain stable. The host must continue supplying trusted current
identity, groups and permitted diary scope.
