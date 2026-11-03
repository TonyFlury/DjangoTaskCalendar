"""Authenticated template creation, selection, and complete revision editing."""
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views import View

from .api import Actor, DiaryAPI
from .forms import TaskFormSet, TemplateForm, editor_task_limit
from .models import Milestone
from .roles import access_groups


class DjangoOwnerDirectory:
    """Resolve user:primary-key references through the configured Django user model."""

    # Partial DV1-013: Generic identity and role adapters.
    def person_in_groups(self, reference, group_names):
        """Return whether a referenced user exists in a configured access group."""

        # References from other namespaces cannot identify a Django person selection.
        if not reference.startswith('user:'):
            return False
        try:
            return get_user_model()._default_manager.filter(
                pk=reference[5:], groups__name__in=group_names).exists()
        except (ValueError, ValidationError):
            return False


# Partial DV1-018: Authenticated routed views.
class TemplateEditorView(LoginRequiredMixin, View):
    """Show the chooser or edit a template selected by URL or trusted view configuration."""

    template_name = None
    extra_context = None
    creating = False
    page_template = 'Diary/template_editor.html'

    # DV1-024: Template chooser and named template view.
    # Partial DV1-013: Generic identity and role adapters.
    # Partial DV1-019: View object selectors.
    # Partial DV1-042: Empty states and invalid selections.
    def dispatch(self, request, *args, **kwargs):
        """Require current Django manager membership before reading or changing templates."""

        # Anonymous requests use the normal Django login redirect before any template lookup.
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        groups = frozenset(request.user.groups.values_list('name', flat=True))

        # Direct URLs and forged POSTs must receive the same manager-only restriction.
        if access_groups()['manager'] not in groups:
            raise PermissionDenied('DiaryManager membership is required for template editing.')
        self.api = DiaryAPI(actor=Actor(reference=f'user:{request.user.pk}', groups=groups))
        selectors = [kwargs.get('template_name'), request.GET.get('template_name'), self.template_name,
                     (self.extra_context or {}).get('template_name')]

        # Empty selectors request the chooser. Conflicting values must not select an unintended template.
        names = [value.strip() for value in selectors if value is not None and value.strip()]

        # Reject conflicts between trusted context and URL selectors rather than assigning precedence.
        if len({name.casefold() for name in names}) > 1 or (self.creating and names):
            return HttpResponseBadRequest('Supply one template name.')
        self.selected_name = next(iter(names), None)
        self.template = None
        self.data = {'name': '', 'description': '', 'version_key': None, 'number': 0, 'entries': ()}

        # A selected name must resolve exactly and cannot fall back to the configured default.
        if self.selected_name is not None:
            try:
                self.template = self.api.template(name=self.selected_name)
                self.data = self.template.editor_data()
            except ObjectDoesNotExist as error:
                raise Http404('The selected template does not exist.') from error
        return super().dispatch(request, *args, **kwargs)

    # DV1-024: Template chooser and named template view.
    # Partial DV1-042: Empty states and invalid selections.
    def get(self, request, *args, **kwargs):
        """Show the template chooser or initialize a read-only request for the editor."""

        # A missing name must show all templates without creating an empty template or version.
        if self.template is None and not self.creating:
            return render(request, 'Diary/template_list.html', {'templates': self.api.templates()})
        header = TemplateForm(initial=self.header_initial(), editing=not self.creating)
        tasks = TaskFormSet(prefix='tasks', initial=list(self.data['entries']))
        return self.render_editor(header, tasks)

    def header_initial(self):
        """Return metadata and the base version used for stale-save detection."""
        return {'name': self.data['name'], 'description': self.data['description'],
                'expected_version_key': self.data['version_key']}

    # DV1-025: Template authoring interface.
    def post(self, request, *args, **kwargs):
        """Validate all forms and atomically save an approved template revision.
        Keep submitted values visible when validation or a concurrent save fails.
        """

        # Chooser requests cannot mutate templates through an omitted selector.
        if self.template is None and not self.creating:
            return HttpResponseBadRequest('Select a template before saving.')
        header = TemplateForm(request.POST, initial=self.header_initial(), editing=not self.creating)
        task_data = request.POST.copy()

        # The server add action also works when JavaScript is unavailable and does not save records.
        if request.POST.get('action') == 'add_task':
            try:
                total = int(task_data.get('tasks-TOTAL_FORMS', '0'))
            except ValueError:
                return HttpResponseBadRequest('Invalid task form count.')

            # Cap additional rows before form construction to bound request work.
            if not 0 <= total < editor_task_limit():
                return HttpResponseBadRequest('The task row count exceeds the configured request limit.')
            task_data['tasks-TOTAL_FORMS'] = str(total + 1)
            task_data[f'tasks-{total}-entry_key'] = str(uuid4())
            task_data[f'tasks-{total}-owner_kind'] = 'team'
            task_data[f'tasks-{total}-date_kind'] = 'source'
            tasks = TaskFormSet(task_data, prefix='tasks', initial=list(self.data['entries']))
            return self.render_editor(header, tasks)
        tasks = TaskFormSet(task_data, prefix='tasks', initial=list(self.data['entries']))
        header_valid = header.is_valid()
        tasks_valid = tasks.is_valid()

        # Both sets must be checked so a single response shows all input errors.
        if header_valid and tasks_valid:
            try:
                with transaction.atomic():
                    template = self.template

                    # New templates and their first approved version must be saved together.
                    if self.creating:
                        template = self.api.create_template(name=header.cleaned_data['name'])
                    template.save_version(
                        entries=tasks.specs, predecessors=tasks.graph,
                        expected_version_key=header.cleaned_data['expected_version_key'],
                        description=header.cleaned_data['description'],
                        milestone_definitions=tasks.milestone_definitions, directory=DjangoOwnerDirectory(),
                    )
                return redirect('Diary:template-edit', template_name=header.cleaned_data['name'])
            except ValidationError as error:
                for message in error.messages:
                    header.add_error(None, message)
            except IntegrityError:
                header.add_error(None, 'The template changed during this save. Reopen it before trying again.')
        return self.render_editor(header, tasks, status=400)

    # DV1-017: Empty-group warnings during template editing.
    def render_editor(self, header, tasks, status=200):
        """Render the complete editor document with task-specific ownership warnings."""
        return render(self.request, self.page_template, {
            'header_form': header, 'task_forms': tasks, 'creating': self.creating,
            'template_data': self.data, 'ownership_warnings': tasks.ownership_warnings(),
            'empty_owner_roles': tasks.empty_roles,
            'milestones': Milestone.objects.order_by('name'),
        }, status=status)


# DV1-025: Template authoring interface.
# Partial DV1-018: Authenticated routed views.
class TemplateCreateView(TemplateEditorView):
    """Open an empty editor and create a template only after a valid save request."""

    creating = True
