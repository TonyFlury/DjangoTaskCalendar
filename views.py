"""Authenticated template editing and read-only manager diary pages."""
from datetime import date
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic.base import ContextMixin
from django.utils import timezone

from .api import Actor, DiaryAPI
from .choices import OwnerKind
from .forms import ManagerDiaryFilterForm, TaskFormSet, TemplateForm, editor_task_limit
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


# DV1-022, DV1-052: Manager list and completion history for one permitted diary.
# Partial DV1-013, DV1-018, DV1-019, DV1-041, DV1-042, DV1-044.
class ManagerDiaryView(LoginRequiredMixin, ContextMixin, View):
    """Display a permitted diary selected by GET input or trusted view context.
    Host views supply permitted_diary_keys or override get_diary_keys().
    A selected key does not grant access to that diary.
    """

    diary_key = None
    permitted_diary_keys = ()
    extra_context = None
    template_name = 'Diary/manager_diary.html'
    http_method_names = ['get', 'head', 'options']

    def dispatch(self, request, *args, **kwargs):
        """Require an active manager before processing selectors or reading task data."""

        # Anonymous users follow the configured login flow before any diary lookup.
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        groups = frozenset(request.user.groups.values_list('name', flat=True))

        # A manager role is necessary even when trusted context supplies a diary key.
        if not request.user.is_active or access_groups()['manager'] not in groups:
            raise PermissionDenied('DiaryManager membership is required for this view.')
        self.view_context = self.get_context_data(**kwargs)
        self.actor = Actor(reference=f'user:{request.user.pk}', groups=groups,
                           calendar_keys=frozenset(UUID(str(key)) for key in self.get_diary_keys()))
        return super().dispatch(request, *args, **kwargs)

    def get_diary_keys(self):
        """Return permitted keys from trusted context, with no access granted by default.
        The host can override this method for its own diary access policy.
        """
        return self.view_context.get('permitted_diary_keys', self.permitted_diary_keys)

    def selected_key(self):
        """Return one UUID from GET values, the view attribute, or trusted context.
        Raise ValueError for malformed, blank, or conflicting selectors.
        """
        values = self.request.GET.getlist('diary_key')
        for value in (self.diary_key, self.view_context.get('diary_key')):

            # Unset trusted selectors must not turn an omitted query into an invalid key.
            if value is not None:
                values.append(value)
        keys = {UUID(str(value)) for value in values}

        # Conflicting inputs must not silently select a different permitted diary.
        if len(keys) > 1:
            raise ValueError('Supply one diary key.')
        return next(iter(keys), None)

    def get(self, request, *args, **kwargs):
        """Render a selected diary or an explicit empty selection without changing data."""
        filters = ManagerDiaryFilterForm(request.GET)
        filters.is_valid()
        context = {**self.view_context, 'filters': filters, 'diary_data': None, 'tasks': ()}
        try:
            key = self.selected_key()
        except (ValueError, TypeError, AttributeError):
            context['manager_error'] = 'Supply one valid diary key.'
            return render(request, self.template_name, context, status=400)

        # This manager page must not choose an arbitrary diary when the selector is absent.
        if key is None:
            return render(request, self.template_name, context)
        try:
            data = DiaryAPI(actor=self.actor).diary(key=key).read()
        except ObjectDoesNotExist:
            context['manager_error'] = 'The selected diary does not exist.'
            return render(request, self.template_name, context, status=404)
        context.update(diary_data=data, tasks=self.get_tasks(data, filters.cleaned_data))
        return render(request, self.template_name, context)

    def get_tasks(self, data, filters):
        """Select and order permitted tasks, including completion history when requested.
        Completed entries are never late or blocked in this manager view.
        Partial DV1-039: Identify late tasks and blocked tasks with late direct predecessors.
        """
        today = timezone.localdate(timezone=ZoneInfo(getattr(settings, 'DIARY_TIME_ZONE', settings.TIME_ZONE)))
        labels, members = self.get_owner_labels(data['entries'])
        late_keys = set()
        for entry in data['entries']:

            # Completed and undated tasks must not count as late predecessors.
            if entry['completed_at'] is None and entry['date'] is not None and entry['date'] <= today:
                late_keys.add(entry['entry_key'])
        tasks = []
        for entry in data['entries']:
            completed = entry['completed_at'] is not None
            blocked = not completed and bool(entry['blocking_predecessors'])
            late = entry['entry_key'] in late_keys

            # The default excludes history, and selected exclusions apply together.
            if ((completed and not filters['include_completed'])
                    or (blocked and filters['exclude_blocked'])
                    or (not late and filters['exclude_non_late'])):
                continue
            task = {**entry, 'completed': completed, 'blocked': blocked, 'late': late,
                    'blocked_late': blocked and bool(set(entry['blocking_predecessors']) & late_keys),
                    'owner_members': (), 'completed_by_label': labels.get(entry['completed_by_ref'], entry['completed_by_ref'])}

            # Resolve current Django person names without changing opaque person references.
            if entry['owner_kind'] == OwnerKind.PERSON:
                task['owner_label'] = labels.get(entry['person_ref'], entry['person_ref'])

            # Group ownership retains the group reference and shows its current members.
            elif entry['owner_kind'] == OwnerKind.ROLE:
                task['owner_label'] = entry['role_ref']
                task['owner_members'] = members.get(entry['role_ref'], ())

            # Whole-team ownership has no person or group reference.
            else:
                task['owner_label'] = 'Whole team'
            tasks.append(task)
        return tuple(sorted(tasks, key=self.task_order))

    @staticmethod
    def task_order(task):
        """Order entries by due date, then name and stable key, with unset dates last."""
        return task['date'] or date.max, task['name'].casefold(), str(task['entry_key'])

    def get_owner_labels(self, entries):
        """Resolve Django person names and current role members with at most two database queries.
        Keep unknown person references available as display labels.
        Partial DV1-040: Display current ownership without changing stored task owners.
        """
        model = get_user_model()
        person_ids = []
        roles = set()
        for entry in entries:
            roles.add(entry['role_ref'])
            for reference in (entry['person_ref'], entry['completed_by_ref']):

                # Opaque references outside the Django namespace need no user lookup.
                if not reference.startswith('user:'):
                    continue
                try:
                    person_ids.append(model._meta.pk.to_python(reference[5:]))
                except (ValueError, TypeError, ValidationError):

                    # Invalid references must not prevent the remaining task records from being displayed.
                    continue
        users = model._default_manager.filter(Q(pk__in=person_ids) | Q(groups__name__in=roles)).distinct().prefetch_related('groups')
        labels = {}
        members = {role: [] for role in roles}
        for user in users:
            name = user.get_full_name().strip() or user.get_username()
            labels[f'user:{user.pk}'] = name
            for group in user.groups.all():

                # Access groups unrelated to task ownership must not add membership labels.
                if group.name in members:
                    members[group.name].append(name)
        return labels, {role: tuple(sorted(names, key=str.casefold)) for role, names in members.items()}
