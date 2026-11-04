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
Do not use reserved Diary field names or `csrfmiddlewaretoken` as host field names.
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
Override `get_success_url(template_name=...)` to change navigation after a successful save.
The hook receives the saved template name. It can retain the host selection and return a fixed URL.
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
