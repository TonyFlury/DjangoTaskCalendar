"""Authenticated Diary pages, HTTP data reads, template editing, date editing, and completion."""
import logging
from datetime import date
from uuid import UUID, uuid4
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core import signing
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views import View
from django.views.generic.base import ContextMixin
from django.utils import timezone
from django.utils.cache import patch_cache_control, patch_vary_headers

from .api import Actor, DiaryAPI
from .view_api import DiarySuccessMixin, DiaryViewResult, form_target, submitted_target
from .choices import OwnerKind
from .forms import (ManagerDiaryFilterForm, PersonalDiaryFilterForm, ReusableTaskRuleForm,
                    TaskCompletionForm, TaskCreateForm, TaskDueDateForm, TaskFormSet, TaskOwnerRecoveryForm, TaskNoteForm,
                    TemplateForm, TemplateApplicationChoiceForm, TemplateApplicationDatesForm, editor_task_limit)
from .models import CalendarTemplate, EventCalendar, Milestone, TemplateVersion
from .roles import access_groups
from .ownership import orphaned_entry_keys
from .identity import user_display_name

logger = logging.getLogger(__name__)


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
                pk=reference[5:], is_active=True, groups__name__in=group_names).exists()
        except (ValueError, ValidationError):
            return False


# Partial DV1-018: Authenticated routed views.
class TemplateEditorView(DiarySuccessMixin, LoginRequiredMixin, ContextMixin, View):
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
        self.view_context = self.get_context_data(**kwargs)
        try:
            self.posted_target = submitted_target(request)
        except signing.BadSignature:
            return HttpResponseBadRequest('Invalid form selection. Reload the page before submitting.')
        selectors = [kwargs.get('template_name'), request.GET.get('template_name'), self.template_name,
                     self.view_context.get('template_name'), self.posted_target.get('template_name')]

        # Empty selectors request the chooser. Conflicting values must not select an unintended template.
        names = [value.strip() for value in selectors if value is not None and value.strip()]

        # Reject conflicts between trusted context and URL selectors rather than assigning precedence.
        if len({name.casefold() for name in names}) > 1 or (self.creating and names):
            logger.warning('Diary selector rejected: selector=template_name view=%s reason=conflicting or disallowed selection status=400',
                           type(self).__name__)
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
            return render(request, 'Diary/template_list.html', {**self.view_context, 'templates': self.api.templates()})
        header = TemplateForm(initial=self.header_initial(), editing=not self.creating)
        tasks = TaskFormSet(prefix='tasks', initial=list(self.data['entries']),
                            milestones=self.milestone_choices())
        return self.render_editor(header, tasks)

    def header_initial(self):
        """Return metadata and the base version used for stale-save detection."""
        return {'name': self.data['name'], 'description': self.data['description'],
                'expected_version_key': self.data['version_key']}

    def milestone_choices(self):
        """Offer the full host milestone catalogue during task construction."""
        return tuple(Milestone.objects.order_by('name').values_list('name', 'label'))

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

        if request.POST.get('action') == 'refresh_milestones':
            tasks = TaskFormSet(task_data, prefix='tasks', initial=list(self.data['entries']),
                                milestones=self.milestone_choices())
            return self.render_editor(header, tasks)

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
            tasks = TaskFormSet(task_data, prefix='tasks', initial=list(self.data['entries']),
                                milestones=self.milestone_choices())
            return self.render_editor(header, tasks)
        tasks = TaskFormSet(task_data, prefix='tasks', initial=list(self.data['entries']),
                            milestones=self.milestone_choices())
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
                    saved_version = template.save_version(
                        entries=tasks.specs, predecessors=tasks.graph,
                        expected_version_key=header.cleaned_data['expected_version_key'],
                        description=header.cleaned_data['description'],
                        directory=DjangoOwnerDirectory(),
                    )
            except ValidationError as error:
                for message in error.messages:
                    header.add_error(None, message)
            except IntegrityError:
                header.add_error(None, 'The template changed during this save. Reopen it before trying again.')
            else:
                return self.success_response(result=DiaryViewResult(
                    operation='template_created' if self.creating else 'template_saved',
                    template_name=header.cleaned_data['name'], template_version_key=saved_version.key))
        return self.render_editor(header, tasks, status=400)

    # DV1-017: Empty-group warnings during template editing.
    def render_editor(self, header, tasks, status=200):
        """Render the complete editor document with task-specific ownership warnings."""
        return render(self.request, self.page_template, {
            **self.view_context,
            'diary_target': form_target(self.request, template_name=self.data['name'] if not self.creating else None),
            'diary_form_url': self.request.path,
            'header_form': header, 'task_forms': tasks, 'creating': self.creating,
            'template_data': self.data, 'ownership_warnings': tasks.ownership_warnings(),
            'empty_owner_roles': tasks.empty_roles,
            'milestone_options': list(Milestone.objects.order_by('name').values('name', 'label')),
        }, status=status)


# DV1-025: Template authoring interface.
# Partial DV1-018: Authenticated routed views.
class TemplateCreateView(TemplateEditorView):
    """Open an empty editor and create a template only after a valid save request."""

    creating = True


# DV1-013, DV1-019: Shared identity, trusted scope, and diary selectors.
class DiaryScopeMixin(LoginRequiredMixin, ContextMixin):
    """Authenticate a caller and resolve a diary selector within trusted host scope.
    Host views supply permitted_diary_keys or override get_diary_keys().
    A selected key does not grant access to that diary.
    """

    diary_key = None
    permitted_diary_keys = ()
    extra_context = None
    access_roles = ('manager',)
    http_method_names = ['get', 'head', 'options']

    def dispatch(self, request, *args, **kwargs):
        """Require current access-group membership before processing selectors or reading task data."""

        # Anonymous users follow the configured login flow before any diary lookup.
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        groups = frozenset(request.user.groups.values_list('name', flat=True))

        # Trusted context cannot replace active membership in a group allowed by this view.
        configured = access_groups()
        allowed = {configured[role] for role in self.access_roles}
        if not request.user.is_active or not groups.intersection(allowed):
            raise PermissionDenied('Diary access group membership is required for this view.')
        self.view_context = self.get_context_data(**kwargs)
        self.actor = Actor(reference=f'user:{request.user.pk}', groups=groups,
                           calendar_keys=frozenset(UUID(str(key)) for key in self.get_diary_keys()))
        try:
            self.posted_target = submitted_target(request)
        except signing.BadSignature:
            return HttpResponseBadRequest('Invalid form selection. Reload the page before submitting.')
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
        for value in (self.diary_key, self.view_context.get('diary_key'), getattr(self, 'posted_target', {}).get('diary_key')):

            # Unset trusted selectors must not turn an omitted query into an invalid key.
            if value is not None:
                values.append(value)
        keys = {UUID(str(value)) for value in values}

        # Conflicting inputs must not silently select a different permitted diary.
        if len(keys) > 1:
            logger.warning('Diary selector rejected: selector=diary_key view=%s reason=conflicting selections status=400',
                           type(self).__name__)
            raise ValueError('Supply one diary key.')
        return next(iter(keys), None)

    # DV1-023: Host routes supply their own task detail scope through a named view.
    def task_url(self, entry_key, diary_key):
        """Return a task-detail URL that keeps the selected diary and optional host route name."""
        ui = self.view_context.get('diary_ui', {})

        # DV1-041: Host POST selection supplies record scope outside the browser URL.
        if ui.get('selection_url'):
            return ui.get('task_detail_url', self.request.path)
        name = self.view_context.get('task_detail_url_name')
        if name:
            return reverse(name, kwargs={'entry_key': entry_key})
        return reverse('Diary:diary-task-detail', kwargs={'diary_key': diary_key, 'entry_key': entry_key})


# DV1-031: HTTP data reads use the same identity, scope, and privacy checks as the callable API.
class DiaryDataView(DiaryScopeMixin, View):
    """Return read-only JSON task data within the authenticated host's permitted diary scope.
    Hosts must supply trusted diary keys. Query parameters cannot grant access.
    """

    access_roles = ('manager', 'user')
    resource = 'diary'

    def dispatch(self, request, *args, **kwargs):
        """Authenticate each request and prevent storage or sharing of its response."""
        response = super().dispatch(request, *args, **kwargs)
        patch_cache_control(response, private=True, no_store=True)
        patch_vary_headers(response, ('Cookie',))
        return response

    def get(self, request, entry_key=None, *args, **kwargs):
        """Return a permitted read result or a generic selector, validation, or lookup error."""
        try:
            key = self.selected_key()
        except (ValueError, TypeError, AttributeError):
            return JsonResponse({'error': 'Supply one valid diary key.'}, status=400)
        api = DiaryAPI(actor=self.actor)
        try:

            # Search can span permitted diaries and must never search raw model records.
            if self.resource == 'search':
                data = api.search_tasks(diary_key=key, query=request.GET.get('q', ''))

            # Personal results retain assignment selection across permitted open diaries.
            elif self.resource == 'personal':
                data = api.personal_tasks(diary_key=key)

            # Diary metadata and task-specific resources require one explicit or trusted selector.
            else:

                # A task identifier alone cannot select a diary or grant diary scope.
                if key is None:
                    return JsonResponse({'error': 'Select a permitted diary.'}, status=400)
                diary = api.diary(key=key)

                # Metadata includes only tasks and related references visible to this actor.
                if self.resource == 'diary':
                    data = diary.read()

                # Active results preserve blocking state calculated from the complete private graph.
                elif self.resource == 'active':
                    data = diary.active_tasks()

                # Task inspection masks inaccessible blockers and completion targets.
                elif self.resource == 'task':
                    data = diary.task(entry_key=entry_key)

                # Existing predecessor choices remain readable despite the V1 dependency edit restriction.
                elif self.resource == 'predecessors':
                    data = diary.available_predecessors(entry_key=entry_key)

                # Unsupported host configuration cannot expose a broader default resource.
                else:
                    return JsonResponse({'error': 'Unknown Diary data resource.'}, status=400)
        except ObjectDoesNotExist:
            return JsonResponse({'error': 'The selected diary or task is unavailable.'}, status=404)
        except ValidationError:
            return JsonResponse({'error': 'The request contains invalid Diary data.'}, status=400)
        return JsonResponse({'data': data})


# Partial DV1-040: Shared current owner labels for task pages.
class DiaryOwnerLabelsMixin:
    """Resolve current Django names without changing stored task ownership."""

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
            name = user_display_name(user)
            labels[f'user:{user.pk}'] = name
            for group in user.groups.all():

                # Access groups unrelated to task ownership must not add membership labels.
                if group.name in members:
                    members[group.name].append(name)
        return labels, {role: tuple(sorted(names, key=str.casefold)) for role, names in members.items()}


class TemplateApplyView(DiarySuccessMixin, DiaryScopeMixin, View):
    """Let a manager apply one approved template to an existing permitted diary."""

    http_method_names = ['get', 'post', 'head', 'options']
    template_name = 'Diary/template_apply.html'

    def get(self, request, *args, **kwargs):
        return self.respond()

    def post(self, request, *args, **kwargs):
        choosing = request.POST.get('action') == 'choose_template'
        return self.respond(submitted=not choosing, choosing=choosing)

    def respond(self, *, submitted=False, choosing=False):
        context = {**self.view_context, 'application_error': '', 'diary_data': None}
        try:
            key = self.selected_key()
        except (ValueError, TypeError, AttributeError):
            key = None
        if key is None:
            context['application_error'] = 'Select a permitted diary before applying a template.'
            return render(self.request, self.template_name, context, status=400)
        try:
            diary = DiaryAPI(actor=self.actor).diary(key=key)
            context['diary_data'] = diary.read()
        except ObjectDoesNotExist:
            raise Http404('The selected diary is unavailable.')
        context.update(diary_target=form_target(self.request, diary_key=key), diary_form_url=self.request.path)
        if context['diary_data']['closed']:
            context['application_error'] = 'This diary is closed. A template cannot be applied.'
            return render(self.request, self.template_name, context, status=400)
        if context['diary_data']['template_version_key'] and not submitted:
            context['application_error'] = 'A template is already applied to this diary.'
            return render(self.request, self.template_name, context)
        data = self.request.POST if submitted or choosing else self.request.GET
        picker = TemplateApplicationChoiceForm(data if submitted or choosing or data.get('template_version_key') else None)
        context['application_picker'] = picker
        status = 200
        if picker.is_bound and picker.is_valid():
            version = DiaryAPI(actor=self.actor).template_version(key=picker.cleaned_data['template_version_key'])
            milestones = version.required_milestones()
            dates = TemplateApplicationDatesForm(self.request.POST if submitted else None, milestones=milestones)
            context.update(application_dates=dates, application_version_key=version.key)
            if submitted:
                status = 400
                if dates.is_valid():
                    try:
                        diary.apply_template(template_version_key=version.key, milestone_dates=dates.milestone_dates())
                    except (ValidationError, IntegrityError) as error:
                        if isinstance(error, ValidationError):
                            for message in error.messages:
                                dates.add_error(None, message)
                        else:
                            dates.add_error(None, 'The diary or template changed. Reload before applying the template.')
                    else:
                        version_data = version.read()
                        template_name = CalendarTemplate.objects.get(pk=version_data['template_key']).name
                        return self.success_response(result=DiaryViewResult(operation='template_applied',
                            diary_key=key, template_name=template_name, template_version_key=version.key))
        elif picker.is_bound:
            status = 400
        return render(self.request, self.template_name, context, status=status)


# DV1-029, DV1-030, DV1-033: Authenticated creation within a selected permitted diary.
class TaskCreateView(DiarySuccessMixin, DiaryScopeMixin, View):
    """Create self-owned or manager-assigned tasks with an optional atomic template revision."""

    access_roles = ('manager', 'user')
    http_method_names = ['get', 'post', 'head', 'options']
    template_name = 'Diary/task_create.html'

    def get(self, request, *args, **kwargs):
        """Show the diary chooser or a new task form without changing any records."""
        return self.respond()

    def post(self, request, *args, **kwargs):
        """Validate task ownership and save both requested additions in one transaction."""
        return self.respond(submitted=True)

    def respond(self, *, submitted=False):
        """Resolve trusted scope and render kept input after validation or storage errors."""
        context = {**self.view_context, 'diary_data': None, 'creation_error': ''}
        try:
            key = self.selected_key()
        except (ValueError, TypeError, AttributeError):
            context['creation_error'] = 'Supply one valid diary key.'
            return render(self.request, self.template_name, context, status=400)

        # The chooser lists only open diaries within trusted host scope and cannot create a task.
        if key is None:
            context['creation_diaries'] = EventCalendar.objects.filter(
                pk__in=self.actor.calendar_keys, closed_at__isnull=True).order_by('name', 'pk')

            # POST cannot infer a target diary from a submitted form field.
            if submitted:
                context['creation_error'] = 'Select a permitted diary before saving.'
            return render(self.request, self.template_name, context, status=400 if submitted else 200)
        try:
            diary = DiaryAPI(actor=self.actor).diary(key=key)
            context['diary_data'] = diary.read()
        except ObjectDoesNotExist:
            context['creation_error'] = 'The selected diary does not exist.'
            return render(self.request, self.template_name, context, status=404)

        # Closed diaries remain identifiable but must never accept a new task.
        if context['diary_data']['closed']:
            context['creation_error'] = 'This diary is closed. You cannot add a task.'
            return render(self.request, self.template_name, context, status=400 if submitted else 200)
        manager = access_groups()['manager'] in self.actor.groups
        initial = {'entry_key': uuid4()}

        # Only managers can inspect template metadata or request its revision.
        template_data = None
        if manager:
            calendar = EventCalendar.objects.select_related('template_version__template').get(pk=key)
            if calendar.template_version_id:
                template_data = DiaryAPI(actor=self.actor).template(key=calendar.template_version.template_id).editor_data()
                initial['expected_version_key'] = template_data['version_key']
                context['creation_template'] = template_data

        # GET initializes an unbound form, while POST keeps the caller's submitted values.
        data = self.request.POST if submitted else None
        form = TaskCreateForm(data, actor=self.actor, initial=initial, source_tasks=context['diary_data']['entries'])
        form.fields['milestone_name'].choices = [('', 'Select a milestone'),
            *Milestone.objects.filter(calendar_dates__calendar_id=key).order_by('name').values_list('name', 'label')]
        future = ReusableTaskRuleForm(data, prefix='future', use_required_attribute=False,
                                      source_tasks=template_data['entries'] if template_data else ())
        future.fields['milestone_name'].choices = [('', 'Select a milestone'),
            *Milestone.objects.order_by('name').values_list('name', 'label')] if template_data else [('', 'Select a milestone')]
        if not context['diary_data']['template_version_key']:
            form.fields['add_to_template'].disabled = True
            form.fields['add_to_template'].widget = forms.HiddenInput(attrs=form.fields['add_to_template'].widget.attrs)
            form.initial['add_to_template'] = False
            form.fields['date_kind'].choices = [(value, label) for value, label in form.fields['date_kind'].choices
                                                if value in {'annual', 'once', 'task'}]
            hidden_date_fields = ['milestone_name']
            if not any(entry['date'] is not None for entry in context['diary_data']['entries']):
                form.fields['date_kind'].choices = [(value, label) for value, label in form.fields['date_kind'].choices
                                                    if value != 'task']
                hidden_date_fields.extend(('day_offset', 'source_task_key'))
            for name in hidden_date_fields:
                form.fields[name].disabled = True
                form.fields[name].widget = forms.HiddenInput(attrs=form.fields[name].widget.attrs)
        context.update(creation_form=form, future_form=future, creation_manager=manager)

        context.update(diary_target=form_target(self.request, diary_key=key), diary_form_url=self.request.path)
        if not submitted:
            return render(self.request, self.template_name, context)
        valid = form.is_valid()
        if not context['diary_data']['template_version_key'] and self.request.POST.get('add_to_template'):
            form.add_error(None, 'Apply a template before adding tasks to it for future diaries.')
            valid = False
        add_to_template = manager and form.cleaned_data.get('add_to_template', False)

        # The future rule is required only when the manager explicitly requests a template addition.
        if add_to_template:
            valid = future.is_valid() and valid

        # No data operation can run until all applicable forms pass validation.
        if valid:
            try:
                spec = form.entry_spec()

                # A separate rule prevents silent conversion of an exact date into an annual date.
                template_spec = future.entry_spec(spec) if add_to_template else None
                with transaction.atomic():
                    diary.create_task(spec=spec, template_spec=template_spec,
                                      expected_version_key=form.cleaned_data.get('expected_version_key'),
                                      directory=DjangoOwnerDirectory())
                    saved_version_key = None
                    if template_spec is not None:
                        saved_version_key = TemplateVersion.objects.filter(
                            template_id=calendar.template_version.template_id).order_by('-number').values_list('pk', flat=True).first()
            except ValidationError as error:
                for message in error.messages:
                    form.add_error(None, message)
            except IntegrityError:
                form.add_error(None, 'The task or template changed. Check the task name and open a new form.')
            except ObjectDoesNotExist:
                form.add_error(None, 'The selected diary, milestone, or template is no longer available.')
            else:
                return self.success_response(result=DiaryViewResult(operation='task_created', diary_key=key,
                    entry_key=spec.entry_key, template_name=template_data['name'] if template_spec is not None else None,
                    template_version_key=saved_version_key))
        return render(self.request, self.template_name, context, status=400)


# DV1-023, DV1-032, DV1-035, DV1-036, DV1-037, DV1-038: Task details, due-date edits, and completion.
class TaskDetailView(DiarySuccessMixin, DiaryScopeMixin, DiaryOwnerLabelsMixin, View):
    """Show an accessible task and apply date edits or completion within trusted host scope."""

    access_roles = ('manager', 'user')
    http_method_names = ['get', 'post', 'head', 'options']
    template_name = 'Diary/task_detail.html'
    entry_key = None

    def get(self, request, entry_key=None, *args, **kwargs):
        """Show task details and open predecessors without changing records."""
        return self.respond(entry_key)

    def post(self, request, entry_key=None, *args, **kwargs):
        """Apply one explicit task action after validating its submitted state."""
        return self.respond(entry_key, submitted=True)

    def selected_entry_key(self, route_key):
        values = [value for value in (route_key, self.entry_key, self.view_context.get('entry_key'),
                                      self.posted_target.get('entry_key')) if value is not None]
        keys = {UUID(str(value)) for value in values}
        if len(keys) != 1:
            raise ValueError('Supply one task selection.')
        if self.request.method == 'POST' and route_key is None and not self.posted_target.get('entry_key'):
            raise ValueError('Reload the task before submitting its form.')
        return next(iter(keys))

    def respond(self, entry_key, *, submitted=False):
        """Resolve task scope, apply an action, and retain input when a save fails."""
        context = {**self.view_context, 'task': None, 'detail_error': ''}
        try:
            entry_key = self.selected_entry_key(entry_key)
            key = self.selected_key()
        except (ValueError, TypeError, AttributeError):
            context['detail_error'] = 'Select one valid diary and task. Reload the page before submitting.'
            return render(self.request, self.template_name, context, status=400)

        # A task key cannot select a diary or expand the host's permitted scope.
        if key is None:
            context['detail_error'] = 'Select a permitted diary for this task.'
            return render(self.request, self.template_name, context, status=400)
        try:
            diary = DiaryAPI(actor=self.actor).diary(key=key)
            task = diary.task(entry_key=entry_key)
        except ObjectDoesNotExist:
            context['detail_error'] = 'The selected task is unavailable.'
            return render(self.request, self.template_name, context, status=404)
        labels, members = self.get_owner_labels((task,))
        task.update(owner_label=self.owner_label(task, labels), owner_members=members.get(task['role_ref'], ()),
                    completed_by_label=labels.get(task['completed_by_ref'], 'deleted user'))
        task['completion_action_label'] = {'complete': 'Complete', 'close_all': 'Close all',
                                           'forced_predecessor': 'Close all: predecessor'}.get(
                                               task['completion_action'], 'Earlier completion')

        # Human-readable source labels explain provenance without exposing model field names.
        task['source_label'] = 'Template task' if task['source'] == 'template' else 'Diary addition'
        context['task'] = task
        context.update(diary_target=form_target(self.request, diary_key=key, entry_key=entry_key),
                       diary_form_url=self.request.path)
        initial = {'revision': task['revision'], 'due_date': task['date'], 'blocker_token': task['blocker_token']}

        # Only the requested action binds a form, so unrelated required fields cannot prevent completion.
        action = self.request.POST.get('action') if submitted else None

        # Distinct task-specific IDs keep date and completion forms accessible within the same document.
        due_form = TaskDueDateForm(self.request.POST if action == 'save_date' else None, initial=initial,
                                   auto_id=f'diary-date-{entry_key}-%s')
        completion_form = TaskCompletionForm(self.request.POST if action in {'complete', 'close_all'} else None,
                                             initial=initial, auto_id=f'diary-completion-{entry_key}-%s')

        # DV1-040: Only managers inspect template ownership recovery through the normal task editor.
        task['orphaned'] = False

        # Ordinary users must not receive manager ownership review controls.
        if task['manager']:
            task['orphaned'] = bool(orphaned_entry_keys((task,), directory=DjangoOwnerDirectory()))
        recovery_form = TaskOwnerRecoveryForm(self.request.POST if action == 'save_owner' else None,
            initial={'entry_key': entry_key, 'revision': task['revision']},
            auto_id=f'diary-recovery-{entry_key}-%s')
        note_form = TaskNoteForm(self.request.POST if action == 'add_note' else None,
                                 initial={'note_key': uuid4()}, auto_id=f'diary-note-{entry_key}-%s')
        context.update(due_form=due_form, completion_form=completion_form, recovery_form=recovery_form,
                       note_form=note_form)

        # GET shows the current state, while POST must name one supported action.
        if not submitted:
            return render(self.request, self.template_name, context)

        # Unknown actions must never fall through to a different mutation.
        if action not in {'save_date', 'save_owner', 'complete', 'close_all', 'add_note'} or len(self.request.POST.getlist('action')) != 1:
            context['detail_error'] = 'Select one supported task action.'
            return render(self.request, self.template_name, context, status=400)
        result = None
        try:

            # DV1-040: Ownership changes recheck manager scope, template provenance, and current eligibility in the API.
            if action == 'add_note':
                if note_form.is_valid():
                    diary.add_note(entry_key=entry_key, text=note_form.cleaned_data['text'],
                                   note_key=note_form.cleaned_data['note_key'])
                    result = DiaryViewResult(operation='task_note_added', diary_key=key, entry_key=entry_key)
            elif action == 'save_owner':

                # Invalid owner controls must not change the inspected task.
                if recovery_form.is_valid():
                    diary.reassign_task(entry_key=entry_key, expected_revision=recovery_form.cleaned_data['revision'],
                        owner_kind=recovery_form.cleaned_data['owner_kind'],
                        person_ref=recovery_form.cleaned_data['person_ref'], role_ref=recovery_form.cleaned_data['role_ref'],
                        directory=DjangoOwnerDirectory())
                    result = DiaryViewResult(operation='task_owner_updated', diary_key=key, entry_key=entry_key)

            # Date changes have separate ownership permissions from task completion.
            elif action == 'save_date':

                # Validate dates and revision numbers before invoking the callable API.
                if due_form.is_valid():
                    diary.update_due_date(entry_key=entry_key, due_date=due_form.cleaned_data['due_date'],
                                          expected_revision=due_form.cleaned_data['revision'])
                    result = DiaryViewResult(operation='task_date_updated', diary_key=key, entry_key=entry_key)

            # Completion always rechecks the live predecessor chain inside the database transaction.
            elif completion_form.is_valid():
                diary.complete(entry_key=entry_key, expected_revision=completion_form.cleaned_data['revision'],
                               close_all=action == 'close_all',
                               expected_blockers=completion_form.cleaned_data['blocker_token'])
                result = DiaryViewResult(operation='task_chain_completed' if action == 'close_all' else 'task_completed',
                                         diary_key=key, entry_key=entry_key)
        except ValidationError as error:
            context['detail_error'] = ' '.join(error.messages)
        except ObjectDoesNotExist:
            context['detail_error'] = 'The selected task is unavailable.'
            return render(self.request, self.template_name, context, status=404)
        else:
            if result is not None:
                return self.success_response(result=result)
        return render(self.request, self.template_name, context, status=400)

    def owner_label(self, task, labels):
        """Return a current person name, configured role name, or whole-team label."""

        # Person references can use an opaque namespace outside the configured Django user model.
        if task['owner_kind'] == OwnerKind.PERSON:
            return labels.get(task['person_ref'], 'deleted user')

        # Role tasks keep their group name and current membership separately.
        if task['owner_kind'] == OwnerKind.ROLE:
            return task['role_ref']
        return 'Whole team'


# DV1-022, DV1-052: Manager list and completion history for one permitted diary.
class ManagerDiaryView(DiaryScopeMixin, DiaryOwnerLabelsMixin, View):
    """Display the manager's selected diary and read-only completion history."""

    template_name = 'Diary/manager_diary.html'

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
        if data['template_version_key'] is None and not data['closed']:
            name = self.view_context.get('template_apply_url_name')
            context['template_apply_url'] = self.view_context.get('template_apply_url') or (
                reverse(name) if name else reverse('Diary:diary-template-apply', kwargs={'diary_key': data['key']}))
        return render(request, self.template_name, context)

    def get_tasks(self, data, filters):
        """Select and order permitted tasks, including completion history when requested.
        Completed entries are never late or blocked in this manager view.
        Partial DV1-039: Identify late tasks and blocked tasks with late direct predecessors.
        """
        today = timezone.localdate(timezone=ZoneInfo(getattr(settings, 'DIARY_TIME_ZONE', settings.TIME_ZONE)))
        labels, members = self.get_owner_labels(data['entries'])
        orphaned = orphaned_entry_keys(data['entries'], directory=DjangoOwnerDirectory())
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
            task = {**entry, 'orphaned': entry['entry_key'] in orphaned, 'completed': completed, 'blocked': blocked, 'late': late,
                    'blocked_late': blocked and bool(set(entry['blocking_predecessors']) & late_keys),
                    'owner_members': (), 'completed_by_label': labels.get(entry['completed_by_ref'], 'deleted user')}

            # Resolve current Django person names without changing opaque person references.
            if entry['owner_kind'] == OwnerKind.PERSON:
                task['owner_label'] = labels.get(entry['person_ref'], 'deleted user')

            # Group ownership retains the group reference and shows its current members.
            elif entry['owner_kind'] == OwnerKind.ROLE:
                task['owner_label'] = entry['role_ref']
                task['owner_members'] = members.get(entry['role_ref'], ())

            # Whole-team ownership has no person or group reference.
            else:
                task['owner_label'] = 'Whole team'
            task['detail_url'] = self.task_url(task['entry_key'], data['key'])
            tasks.append(task)
        return tuple(sorted(tasks, key=self.task_order))

    @staticmethod
    def task_order(task):
        """DV1-040: Put orphaned template tasks first, then retain date, name, and stable-key ordering."""
        return not task['orphaned'], task['date'] or date.max, task['name'].casefold(), str(task['entry_key'])



# DV1-020, DV1-021, DV1-049: Personal tasks within one or all host-authorized diaries.
class PersonalDiaryView(DiaryScopeMixin, DiaryOwnerLabelsMixin, View):
    """Display owned open tasks with safe selectors and personal display filters."""

    access_roles = ('manager', 'user')
    template_name = 'Diary/personal_diary.html'

    def get(self, request, *args, **kwargs):
        """Render filtered owned tasks without changing diary records or expanding host scope."""
        filters = PersonalDiaryFilterForm(request.GET)
        context = {**self.view_context, 'filters': filters, 'diary_data': None, 'task_groups': (), 'status_links': ()}

        # Invalid status choices must not silently display a broader task selection.
        if not filters.is_valid():
            context['personal_error'] = 'Select a valid task status.'
            return render(request, self.template_name, context, status=400)
        try:
            key = self.selected_key()
        except (ValueError, TypeError, AttributeError):
            context['personal_error'] = 'Supply one valid diary key.'
            return render(request, self.template_name, context, status=400)
        client = DiaryAPI(actor=self.actor)
        try:

            # A selected diary retains its name and context even when it has no active owned tasks.
            if key is not None:
                context['diary_data'] = client.diary(key=key).read()
            tasks = client.personal_tasks(diary_key=key, include_whole_team=filters.cleaned_data['include_whole_team'])
        except ObjectDoesNotExist:
            context['personal_error'] = 'The selected diary does not exist.'
            return render(request, self.template_name, context, status=404)
        context.update(self.filter_context(tasks, filters.cleaned_data, key))
        return render(request, self.template_name, context)

    def filter_context(self, tasks, filters, key):
        """Build non-overlapping status links and the ready-by-default personal task groups."""
        status = filters['task_status'] or 'all'
        counts = {'late': 0, 'ready': 0, 'blocked': 0}
        selected = []
        for task in tasks:

            # Late has priority over readiness so each task belongs to one status category.
            category = 'late' if task['late'] else task['state']
            counts[category] += 1

            # Explicit status links select their exact category, including blocked late tasks in Late.
            if status != 'all':

                # A status-specific selection excludes every other status category.
                if category != status:
                    continue

            # The default selection includes blocked tasks only through the explicit checkbox.
            elif task['state'] == 'blocked' and not filters['show_blocked']:
                continue
            selected.append(dict(task))
        labels, members = self.get_owner_labels(selected)
        groups = {}
        for task in selected:

            # A person owner can have an opaque reference outside the configured Django user model.
            if task['owner_kind'] == OwnerKind.PERSON:
                task['owner_label'] = labels.get(task['person_ref'], 'deleted user')

            # Group labels show current members without changing the stored role reference.
            elif task['owner_kind'] == OwnerKind.ROLE:
                task['owner_label'] = task['role_ref']
                task['owner_members'] = members.get(task['role_ref'], ())

            # Whole-team tasks appear only when the caller selected their explicit option.
            else:
                task['owner_label'] = 'Whole team'
            group = groups.setdefault(task['diary_key'], {'key': task['diary_key'], 'name': task['diary_name'], 'tasks': []})
            task['detail_url'] = self.task_url(task['entry_key'], task['diary_key'])
            group['tasks'].append(task)
        links = []
        for category, count in counts.items():
            params = {'task_status': category}

            # DV1-041: Trusted host scope replaces selectors without expanding permitted Diary access.
            if key is not None and not self.view_context.get('diary_ui', {}).get('trusted_scope'):
                params['diary_key'] = str(key)

            # Keep optional display choices when following a status count.
            if filters['include_whole_team']:
                params['include_whole_team'] = 'on'

            # This value takes effect again when the user returns to All open tasks.
            if filters['show_blocked']:
                params['show_blocked'] = 'on'
            links.append({'category': category, 'label': category.capitalize(), 'count': count,
                          'url': '?' + urlencode(params)})
        return {'task_groups': tuple(groups.values()), 'status_links': tuple(links), 'task_count': len(selected)}
