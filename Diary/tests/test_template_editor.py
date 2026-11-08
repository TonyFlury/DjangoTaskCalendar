"""Verify manager template editing, immutable revisions, and HTTP validation."""
from dataclasses import replace
from datetime import date
from uuid import uuid4
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from Diary.api import Actor, DiaryAPI, EntrySpec
from Diary.choices import DateKind, OwnerKind
from Diary.forms import TaskFormSet
from Diary.models import CalendarTemplate, Milestone, TemplateEntry, TemplateVersion
from Diary.views import TemplateCreateView, TemplateEditorView


# Verifies DV1-025: Template authoring interface.
# Partial DV1-044: Regression and concurrency verification.
@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=('Helpers',))
class TemplateEditorTests(TestCase):
    """Exercise complete template revisions with current Django user and group data."""

    def setUp(self):
        """Create configurable access groups and one authenticated template manager."""
        self.managers = Group.objects.create(name='Planners')
        self.users = Group.objects.create(name='Participants')
        self.helpers = Group.objects.create(name='Helpers')
        model = get_user_model()
        self.manager = model.objects.create_user(**{model.USERNAME_FIELD: 'manager@example.test'})
        self.manager.groups.add(self.managers)
        self.user = model.objects.create_user(**{model.USERNAME_FIELD: 'user@example.test'})
        self.user.groups.add(self.users)
        self.actor = Actor(f'user:{self.manager.pk}', frozenset({'Planners'}))
        self.api = DiaryAPI(actor=self.actor)
        self.client.force_login(self.manager)
        self.api.define_milestones(definitions={'target': 'Target date'})
        self.spec = EntrySpec('Prepare', DateKind.RELATIVE, milestone_name='target', day_offset=-3)
        self.other = EntrySpec('Review', DateKind.ANNUAL, month=2, day=29)

    def test_host_success_hook_delegates_all_form_processing(self):
        """Use host navigation after the package saves declared milestones, tasks, and dependencies."""
        results = []
        class HostTemplateView(TemplateEditorView):
            """Change only the saved template destination."""

            creating = True

            def on_success(self, *, result):
                """Record the saved selection and return the fixed host location."""
                self.request.session['saved_template'] = result.template_name
                results.append(result)

            success_url = '/host/template/'

        request = RequestFactory().post('/host/template/new/', self.payload())
        request.user = self.manager
        request.session = {}
        response = HostTemplateView.as_view()(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/host/template/')
        self.assertEqual(request.session['saved_template'], 'Reusable plan')
        data = self.api.template(name='Reusable plan').editor_data()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].operation, 'template_created')
        self.assertEqual(results[0].template_version_key, data['version_key'])
        self.assertIsNone(results[0].diary_key)
        self.assertIsNone(results[0].entry_key)
        self.assertEqual(len(data['entries']), 2)
        self.assertEqual([item['name'] for item in data['milestones']], ['target'])

    def test_inherited_context_selects_template_and_reaches_all_render_paths(self):
        from django.shortcuts import render
        from django.views.generic import TemplateView

        template, version = self.create_template()

        class HostParentView(TemplateView):
            def get_context_data(self, **kwargs):
                context = super().get_context_data(**kwargs)
                self.request.context_calls = getattr(self.request, 'context_calls', 0) + 1
                context['host_marker'] = 'Inherited host context'
                context['diary_ui'] = {'form_fields': {'host_state': 'trusted-host-state'}}
                if self.request.session.get('selected_template'):
                    context['template_name'] = self.request.session['selected_template']
                return context

        class HostEditorView(TemplateEditorView, HostParentView):
            pass

        class HostCreateView(TemplateCreateView, HostParentView):
            pass

        requests = [(HostEditorView, 'get', {}, {}, 'Diary/template_list.html', 200),
                    (HostEditorView, 'get', {}, {'selected_template': 'Reusable plan'}, 'Diary/template_editor.html', 200),
                    (HostCreateView, 'get', {}, {}, 'Diary/template_editor.html', 200)]
        for action, expected_status in (('add_task', 200), ('refresh_milestones', 200), ('save', 400)):
            payload = self.payload(version=version.key)
            payload['action'] = action
            if action == 'save':
                payload['tasks-0-name'] = ''
            requests.append((HostEditorView, 'post', payload, {'selected_template': 'Reusable plan'},
                             'Diary/template_editor.html', expected_status))
        for view_class, method, payload, session, page, status in requests:
            with self.subTest(view=view_class.__name__, method=method, action=payload.get('action')):
                request = getattr(RequestFactory(), method)('/host/template/', payload)
                request.user = self.manager
                request.session = session
                with patch('Diary.views.render', wraps=render) as renderer:
                    response = view_class.as_view(extra_context={'static_marker': 'Extra context'})(request)
                self.assertEqual(response.status_code, status)
                self.assertEqual(request.context_calls, 1)
                self.assertEqual(renderer.call_args.args[1], page)
                context = renderer.call_args.args[2]
                self.assertEqual(context['host_marker'], 'Inherited host context')
                self.assertEqual(context['static_marker'], 'Extra context')
                self.assertIsInstance(context['view'], view_class)
                if page.endswith('template_editor.html'):
                    self.assertContains(response, 'name="host_state"', status_code=status)
                    self.assertEqual(context['template_data']['name'], 'Reusable plan' if session else '')
        self.assertEqual(TemplateVersion.objects.count(), 1)
        request = RequestFactory().post('/host/template/', self.payload(version=version.key))
        request.user = self.manager
        request.session = {'selected_template': 'Reusable plan'}
        response = HostEditorView.as_view()(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(request.context_calls, 1)
        self.assertEqual(template.latest_version().read()['number'], 2)

    def test_inherited_template_selector_cannot_override_url_or_permissions(self):
        self.create_template()
        context_calls = []

        class HostMixin:
            def get_context_data(self, **kwargs):
                context = super().get_context_data(**kwargs)
                context_calls.append(self.request.method)
                context['template_name'] = 'Reusable plan'
                return context

        class HostEditorView(HostMixin, TemplateEditorView):
            pass

        request = RequestFactory().get('/host/template/', {'template_name': 'Another selection'})
        request.user = self.manager
        self.assertEqual(HostEditorView.as_view()(request).status_code, 400)
        self.assertEqual(TemplateVersion.objects.count(), 1)
        context_calls.clear()
        request = RequestFactory().get('/host/template/')
        request.user = self.user
        with self.assertRaises(PermissionDenied):
            HostEditorView.as_view()(request)
        self.assertEqual(context_calls, [])

    def test_graph_preview_uses_existing_manager_editor_and_does_not_write(self):
        template, version = self.create_template()
        url = reverse('Diary:template-edit', kwargs={'template_name': 'Reusable plan'})
        response = self.client.get(url)
        self.assertContains(response, 'Task connections')
        self.assertContains(response, 'data-graph-action="fit"')
        self.assertContains(response, '<noscript>')
        self.assertEqual(template.latest_version().key, version.key)
        self.assertEqual(TemplateVersion.objects.count(), 1)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 403)

    def create_template(self, name='Reusable plan'):
        """Create a template with two reusable tasks and an approved predecessor link."""
        template = self.api.create_template(name=name)
        version = template.save_version(entries=[self.spec, self.other],
                                        predecessors={self.other.entry_key: [self.spec.entry_key]},
                                        expected_version_key=None, milestone_names=('target',))
        return template, version

    def payload(self, specs=None, version=None, name='Reusable plan'):
        """Return a complete formset POST with stable task identities."""

        # Default tasks let each test change only the fields relevant to its scenario.
        if specs is None:
            specs = [self.spec, self.other]
        data = {'name': name, 'milestone_names': ['target'], 'description': 'Reusable tasks', 'expected_version_key': version or '',
                'tasks-TOTAL_FORMS': str(len(specs)), 'tasks-INITIAL_FORMS': str(len(specs)),
                'tasks-MIN_NUM_FORMS': '0', 'tasks-MAX_NUM_FORMS': '200', 'action': 'save'}
        for index, spec in enumerate(specs):
            values = {'entry_key': spec.entry_key, 'name': spec.name, 'description': spec.description,
                      'date_kind': spec.date_kind, 'milestone_name': spec.milestone_name,
                      'milestone_label': '', 'day_offset': spec.day_offset, 'month': spec.month or '',
                      'day': spec.day or '', 'year_offset': spec.year_offset, 'owner_kind': spec.owner_kind,
                      'person_ref': spec.person_ref, 'role_ref': spec.role_ref, 'predecessors': []}
            for field, value in values.items():
                data[f'tasks-{index}-{field}'] = str(value)
            data[f'tasks-{index}-predecessors'] = []
        return data

    # Verifies DV1-024: Template chooser and named template view.
    # Verifies DV1-042: Empty states and invalid selections.
    def test_reads_do_not_create_records_and_missing_name_opens_chooser(self):
        """Keep chooser and editor GET requests free from template creation."""
        response = self.client.get(reverse('Diary:template-list'))
        self.assertContains(response, 'No templates exist')
        self.assertEqual(CalendarTemplate.objects.count(), 0)
        response = self.client.get(reverse('Diary:template-create'))
        self.assertContains(response, 'Save template')
        self.assertContains(response, 'Diary/scripts/template_editor.js')
        self.assertIn('diary-template-field-delete',
                      response.context['task_forms'].empty_form.fields['DELETE'].widget.attrs['class'])
        self.assertEqual(TemplateVersion.objects.count(), 0)

    def test_editor_row_limit_respects_host_post_field_limit(self):
        """Bound the formset before construction using the host request field limit."""
        with self.settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=100):
            forms = TaskFormSet(prefix='tasks')
            self.assertEqual(forms.max_num, 5)
        with self.settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=None):
            self.assertEqual(TaskFormSet(prefix='tasks').max_num, 200)

    def test_declared_milestones_control_choices_and_reject_forged_names(self):
        self.api.define_milestones(definitions={'unused': 'Unused requirement'})
        data = self.payload()
        data['milestone_names'] = ['target', 'unused']
        self.assertEqual(self.client.post(reverse('Diary:template-create'), data).status_code, 302)
        template = self.api.template(name='Reusable plan')
        version = template.latest_version()
        self.assertEqual([item['name'] for item in version.required_milestones()], ['target'])
        page = self.client.get(reverse('Diary:template-edit', args=['Reusable plan']))
        self.assertNotContains(page, 'Required milestones')
        self.assertNotContains(page, 'New milestone label')
        choices = dict(page.context['task_forms'].forms[0].fields['milestone_name'].choices)
        self.assertEqual(choices, {'': 'Select a milestone', 'target': 'Target date', 'unused': 'Unused requirement'})
        for names, task_name in ((['traget'], 'traget'),):
            data = self.payload(version=version.key)
            data['milestone_names'] = names
            data['tasks-0-milestone_name'] = task_name
            response = self.client.post(reverse('Diary:template-edit', args=['Reusable plan']), data)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(TemplateVersion.objects.count(), 1)
        self.assertFalse(Milestone.objects.filter(name='traget').exists())

    def test_milestone_refresh_without_javascript_does_not_save_or_add_rows(self):
        self.api.define_milestones(definitions={'unused': 'Unused requirement'})
        data = self.payload()
        data['milestone_names'] = ['target', 'unused']
        data['action'] = 'refresh_milestones'
        response = self.client.post(reverse('Diary:template-create'), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['task_forms'].forms), 2)
        self.assertIn('unused', dict(response.context['task_forms'].forms[0].fields['milestone_name'].choices))
        self.assertFalse(TemplateVersion.objects.exists())
        self.assertFalse(CalendarTemplate.objects.exists())

    # Verifies DV1-026: Versioned template save and approval.
    def test_create_and_edit_approve_versions_and_preserve_existing_diaries(self):
        """Save two revisions while retaining task keys and an existing diary snapshot."""
        self.user.groups.add(self.helpers)
        data = self.payload()
        data['tasks-1-predecessors'] = [str(self.spec.entry_key)]
        response = self.client.post(reverse('Diary:template-create'), data)
        self.assertEqual(response.status_code, 302)
        template = self.api.template(name='Reusable plan')
        first = template.latest_version()
        self.assertEqual(first.read()['status'], 'approved')
        diary = self.api.create_diary(event_ref='editor:1', name='First diary', milestone_dates={'target': date(2028, 6, 1)}, template_version_key=first.key)
        reader = DiaryAPI(actor=replace(self.actor, calendar_keys=frozenset({diary.key}))).diary(key=diary.key)
        snapshot = reader.read()
        edited = replace(self.spec, name='Prepare equipment', day_offset=-7)
        data = self.payload([edited, self.other], version=first.key)
        data['tasks-1-predecessors'] = [str(edited.entry_key)]
        response = self.client.post(reverse('Diary:template-edit', args=['Reusable plan']), data)
        self.assertEqual(response.status_code, 302)
        second = template.latest_version()
        self.assertEqual(second.read()['number'], 2)
        self.assertEqual(second.read()['status'], 'approved')
        self.assertEqual(set(entry['entry_key'] for entry in second.read()['entries']),
                         {self.spec.entry_key, self.other.entry_key})
        self.assertEqual(reader.read(), snapshot)
        self.assertEqual(first.read()['entries'][0]['name'], 'Prepare')

    # Verifies DV1-024: Template chooser and named template view.
    # Verifies DV1-019: View object selectors.
    # Verifies DV1-042: Empty states and invalid selections.
    def test_named_view_selects_latest_draft_and_supports_url_or_trusted_context(self):
        """Use highest numbered versions and reject conflicting template selectors."""
        template, _ = self.create_template()
        draft = template.create_version(number=2, milestone_names=('target',))
        draft.add_entry(spec=replace(self.spec, name='Draft task'))
        response = self.client.get(reverse('Diary:template-list'), {'template_name': 'Reusable plan'})
        self.assertContains(response, 'Draft task')
        self.assertContains(response, 'Version 2')
        self.assertContains(response, 'draft')
        factory = RequestFactory()
        request = factory.get('/embedded-editor/')
        request.user = self.manager
        trusted_context = {'template_name': 'Reusable plan'}
        configured_view = TemplateEditorView.as_view(extra_context=trusted_context)
        response = configured_view(request)
        self.assertEqual(response.status_code, 200)

        # DV1-019, DEC-001: Template context cannot override a conflicting URL selection without a diagnostic.
        request = factory.get('/embedded-editor/', {'template_name': 'Another'})
        request.user = self.manager
        with self.assertLogs('Diary.views', level='WARNING') as logs:
            self.assertEqual(configured_view(request).status_code, 400)
        self.assertIn('selector=template_name', logs.output[0])
        self.assertIn('status=400', logs.output[0])
        self.assertNotIn('Reusable plan', logs.output[0])
        response = self.client.get(reverse('Diary:template-edit', args=['Reusable plan']), {'template_name': 'Another'})
        self.assertEqual(response.status_code, 400)
        response = self.client.get(reverse('Diary:template-edit', args=['Unknown']))
        self.assertEqual(response.status_code, 404)

    # Verifies DV1-018: Authenticated routed views.
    def test_anonymous_and_ordinary_users_cannot_access_or_save_templates(self):
        """Enforce the same manager gate on direct reads, writes, and callable operations."""
        self.client.logout()
        self.assertEqual(self.client.get(reverse('Diary:template-create')).status_code, 302)
        self.client.force_login(self.user)
        for url in (reverse('Diary:template-list'), reverse('Diary:template-create')):
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, self.payload()).status_code, 403)
        self.assertFalse(CalendarTemplate.objects.exists())
        template, version = self.create_template()
        outsider = DiaryAPI(actor=Actor('user', frozenset({'Participants'})))
        with self.assertRaises(PermissionDenied):
            outsider.templates()
        forged = type(template)(actor=outsider.actor, key=template.key)
        with self.assertRaises(PermissionDenied):
            forged.save_version(entries=[], predecessors={}, expected_version_key=version.key)

    # Verifies DV1-018: Authenticated routed views.
    def test_http_post_requires_csrf_token(self):
        """Reject authenticated browser saves that lack CSRF protection."""
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.manager)
        response = client.post(reverse('Diary:template-create'), self.payload())
        self.assertEqual(response.status_code, 403)
        self.assertFalse(CalendarTemplate.objects.exists())

    # Verifies DV1-017: Empty-group warnings during template editing.
    def test_empty_role_warning_names_task_and_preserves_role_assignment(self):
        """Warn about empty groups on failed posts and saved template reads."""
        role_spec = replace(self.spec, owner_kind=OwnerKind.ROLE, role_ref='Helpers')
        data = self.payload([role_spec])
        data['tasks-0-name'] = ''
        response = self.client.post(reverse('Diary:template-create'), data)
        self.assertContains(response, 'No role members', status_code=400)
        self.assertContains(response, 'Helpers', status_code=400)
        data['tasks-0-name'] = 'Role preparation'
        response = self.client.post(reverse('Diary:template-create'), data)
        self.assertEqual(response.status_code, 302)
        response = self.client.get(response.url)
        self.assertContains(response, 'Role preparation: No role members')
        saved = TemplateEntry.objects.get()
        self.assertEqual(saved.owner_kind, OwnerKind.ROLE)
        self.assertEqual(saved.role_ref, 'Helpers')
        self.user.groups.add(self.helpers)
        self.assertNotContains(self.client.get(reverse('Diary:template-edit', args=['Reusable plan'])), 'No role members')

    # Verifies DV1-013: Generic identity and role adapters.
    def test_person_ownership_uses_configured_user_model_and_rejects_other_users(self):
        """Accept eligible Django references and reject a person without an access group."""
        person = replace(self.spec, owner_kind=OwnerKind.PERSON, person_ref=f'user:{self.user.pk}')
        response = self.client.post(reverse('Diary:template-create'), self.payload([person]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TemplateEntry.objects.get().person_ref, person.person_ref)
        self.user.groups.clear()
        response = self.client.post(reverse('Diary:template-create'), self.payload([person], name='Other plan'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(CalendarTemplate.objects.count(), 1)

    def test_invalid_date_and_duplicate_names_leave_no_partial_template(self):
        """Show validation errors without retaining templates, versions, or new milestones."""
        data = self.payload()
        data['tasks-1-month'] = '2'
        data['tasks-1-day'] = '30'
        response = self.client.post(reverse('Diary:template-create'), data)
        self.assertContains(response, 'valid month and day', status_code=400)
        self.assertFalse(CalendarTemplate.objects.exists())
        self.assertEqual(list(Milestone.objects.values_list('name', flat=True)), ['target'])
        data = self.payload([self.spec, replace(self.other, name='prepare')])
        response = self.client.post(reverse('Diary:template-create'), data)
        self.assertContains(response, 'different name', status_code=400)
        self.assertFalse(TemplateVersion.objects.exists())

    # Verifies DV1-026: Versioned template save and approval.
    def test_stale_save_preserves_submitted_data_and_does_not_add_version(self):
        """Reject a browser edit after another manager saves a newer revision."""
        template, version = self.create_template()
        template.save_version(entries=[self.spec], predecessors={}, expected_version_key=version.key)
        data = self.payload(version=version.key)
        data['tasks-0-name'] = 'My unsaved work'
        response = self.client.post(reverse('Diary:template-edit', args=['Reusable plan']), data)
        self.assertContains(response, 'This template changed', status_code=400)
        self.assertContains(response, 'My unsaved work', status_code=400)
        self.assertEqual(TemplateVersion.objects.count(), 2)

    def test_callable_save_rolls_back_new_version_milestones_and_description_on_error(self):
        """Roll back all writes when a later task fails model validation."""
        template, version = self.create_template()
        invalid = replace(self.other, month=13)
        with self.assertRaises(ValidationError):
            template.save_version(entries=[self.spec, invalid], predecessors={}, expected_version_key=version.key,
                                  description='Must roll back', milestone_names=('target', 'unused'))
        self.assertEqual(TemplateVersion.objects.count(), 1)
        self.assertFalse(Milestone.objects.filter(name='unused').exists())
        self.assertEqual(template.editor_data()['description'], '')

    # Verifies DV1-027: Safe template predecessor editor.
    def test_complete_graph_rejects_cycles_self_links_duplicates_and_foreign_predecessors(self):
        """Validate all dependency endpoints before writing a new revision."""
        template, version = self.create_template()
        invalid_graphs = (
            {self.spec.entry_key: [self.other.entry_key], self.other.entry_key: [self.spec.entry_key]},
            {self.spec.entry_key: [self.spec.entry_key]},
            {self.spec.entry_key: [uuid4()]},
            {uuid4(): [self.spec.entry_key]},
        )
        for graph in invalid_graphs:
            with self.assertRaises(ValidationError):
                template.save_version(entries=[self.spec, self.other], predecessors=graph,
                                      expected_version_key=version.key)
        with self.assertRaises(ValidationError):
            template.save_version(entries=[self.spec, self.spec], predecessors={}, expected_version_key=version.key)
        self.assertEqual(TemplateVersion.objects.count(), 1)

    # Verifies DV1-027: Safe template predecessor editor.
    def test_predecessor_choices_exclude_self_and_unsaved_indirect_successors(self):
        """Use the complete proposed graph before the new version exists in the database."""
        third = replace(self.other, entry_key=uuid4(), name='Finish')
        data = self.payload([self.spec, self.other, third])
        data['tasks-1-predecessors'] = [str(self.spec.entry_key)]
        data['tasks-2-predecessors'] = [str(self.other.entry_key)]
        formset = TaskFormSet(data, prefix='tasks', milestones=(('target', 'Target date'),))
        self.assertTrue(formset.is_valid(), formset.errors)
        self.assertEqual(list(formset.forms[0].fields['predecessors'].choices), [])
        self.assertEqual(dict(formset.forms[1].fields['predecessors'].choices), {str(self.spec.entry_key): 'Prepare'})
        data['tasks-0-predecessors'] = [str(third.entry_key)]
        response = self.client.post(reverse('Diary:template-create'), data)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(CalendarTemplate.objects.exists())

    def test_remove_task_creates_new_version_and_keeps_previous_version(self):
        """Remove a task and its dependencies only from the new template revision."""
        template, version = self.create_template()
        data = self.payload(version=version.key)
        data['tasks-1-DELETE'] = 'on'
        response = self.client.post(reverse('Diary:template-edit', args=['Reusable plan']), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(template.latest_version().read()['entries']), 1)
        self.assertEqual(len(version.read()['entries']), 2)

    def test_add_without_javascript_does_not_save_and_management_tampering_is_rejected(self):
        """Support a server add action and reject missing formset management data."""
        data = self.payload([])
        data['action'] = 'add_task'
        response = self.client.post(reverse('Diary:template-create'), data)
        self.assertContains(response, 'tasks-0-name')
        self.assertFalse(CalendarTemplate.objects.exists())
        response = self.client.post(reverse('Diary:template-create'), {'name': 'Incomplete'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(CalendarTemplate.objects.exists())

    def test_output_escapes_task_text_and_has_no_inline_presentation(self):
        """Render complete pages without treating submitted names as HTML."""
        self.create_template(name='<Unsafe plan>')
        response = self.client.get(reverse('Diary:template-edit', args=['<Unsafe plan>']))
        self.assertContains(response, '&lt;Unsafe plan&gt;')
        self.assertNotContains(response, 'style=')
        self.assertEqual(response.content.lower().count(b'<!doctype html>'), 1)


# Verifies DV1-026: Versioned template save and approval.
# Partial DV1-044: Regression and concurrency verification.
@override_settings(DIARY_MANAGER='Planners', DIARY_USER='Participants', DIARY_TASK_OWNER_ROLES=())
class TemplateRevisionConcurrencyTests(TransactionTestCase):
    """Verify that concurrent complete saves cannot overwrite the same base revision."""

    available_apps = ['Diary']

    def test_two_saves_from_same_version_allow_one_revision_only(self):
        """Serialize saves on the template and reject the second stale revision."""
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        from django.db import close_old_connections, connection

        self.assertEqual(connection.vendor, 'postgresql')
        actor = Actor('planner', frozenset({'Planners'}))
        template = DiaryAPI(actor=actor).create_template(name='Concurrent revisions')
        spec = EntrySpec('Start', DateKind.ANNUAL, month=1, day=1)
        original = template.save_version(entries=[spec], predecessors={}, expected_version_key=None)
        start = Barrier(2)

        def save(name):
            """Attempt one complete revision through a separate database connection."""
            close_old_connections()
            try:
                start.wait(timeout=10)
                template.save_version(entries=[replace(spec, name=name)], predecessors={},
                                      expected_version_key=original.key)
                return 'saved'
            except ValidationError:
                return 'stale'
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(save, name) for name in ('First edit', 'Second edit')]
            results = [future.result(timeout=20) for future in futures]
        self.assertCountEqual(results, ['saved', 'stale'])
        self.assertEqual(TemplateVersion.objects.count(), 2)
