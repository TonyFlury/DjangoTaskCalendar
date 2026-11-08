"""Forms for template revisions, task creation, due-date editing, and completion."""
from dataclasses import replace
from datetime import date
from uuid import uuid4

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.forms import BaseFormSet, formset_factory
from django.utils.functional import cached_property

from .api import EntrySpec
from .choices import DateKind, OwnerKind
from .models import Milestone, TemplateVersion
from .roles import access_groups, task_owner_roles
from .template_graph import validate_template_graph
from .identity import user_display_name
from .date_rules import task_date_order


class StyledForm(forms.Form):
    """Give every form control a stable Diary styling class."""

    # Partial DV1-041: Complete pages, fragments, and styling interface.
    def __init__(self, *args, **kwargs):
        """Initialize fields and expose a class for each technical field name."""
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs['class'] = f'diary-input diary-template-field-{name.replace("_", "-")}'


class TemplateApplicationChoiceForm(StyledForm):
    template_version_key = forms.ChoiceField(label='Template version')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['template_version_key'].choices = [('', 'Select a template version'),
            *((str(version.pk), f'{version.template.name} — version {version.number}') for version in
              TemplateVersion.objects.filter(status='approved').select_related('template').order_by('template__name', '-number'))]


class TemplateApplicationDatesForm(StyledForm):
    def __init__(self, *args, milestones, **kwargs):
        super().__init__(*args, **kwargs)
        self.milestones = milestones
        for milestone in milestones:
            field = forms.DateField(label=milestone['label'], widget=forms.DateInput(attrs={'type': 'date'}))
            field.widget.attrs['class'] = 'diary-input diary-apply-milestone-date'
            self.fields['milestone_' + milestone['name']] = field

    def milestone_dates(self):
        return {item['name']: self.cleaned_data['milestone_' + item['name']] for item in self.milestones}


# DV1-025: Template authoring interface.
class TemplateForm(StyledForm):
    """Collect template metadata and the version the manager opened."""

    name = forms.CharField(max_length=160, label='Template name')
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))
    expected_version_key = forms.UUIDField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, editing=False, **kwargs):
        """Keep an existing template name fixed while accepting description changes."""
        super().__init__(*args, **kwargs)
        self.fields['name'].disabled = editing


# DV1-052: Read-only manager filters for one diary.
class ManagerDiaryFilterForm(forms.Form):
    """Select completion history, blocking, and lateness filters without changing tasks."""

    include_completed = forms.BooleanField(required=False, label='include completed tasks')
    exclude_blocked = forms.BooleanField(required=False, label='exclude blocked tasks')
    exclude_non_late = forms.BooleanField(required=False, label='exclude non-late tasks')

    def __init__(self, *args, **kwargs):
        """Give each checkbox a stable class for host style overrides."""
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs['class'] = f'diary-manager-checkbox diary-manager-filter-{name.replace("_", "-")}'


# DV1-021, DV1-049: Personal task display filters.
class PersonalDiaryFilterForm(forms.Form):
    """Select blocked tasks, whole-team tasks, and non-overlapping status categories."""

    show_blocked = forms.BooleanField(required=False, label='show blocked also')
    include_whole_team = forms.BooleanField(required=False, label='include whole-team tasks')
    task_status = forms.ChoiceField(required=False, label='Task status', choices=(
        ('all', 'All open tasks'), ('late', 'Late only'), ('ready', 'Ready and not late'),
        ('blocked', 'Blocked and not late'),
    ))

    def __init__(self, *args, **kwargs):
        """Give each personal filter a stable class without relying on its element ID."""
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs['class'] = f'diary-personal-control diary-personal-filter-{name.replace("_", "-")}'


class TemplateTaskForm(StyledForm):
    """Collect one reusable task, its ownership, and its proposed predecessor keys."""

    entry_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid4)
    name = forms.CharField(max_length=160, label='Task name')
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))
    date_kind = forms.ChoiceField(choices=[(DateKind.SOURCE, 'Milestone date'),
                                          (DateKind.RELATIVE, 'Days from a milestone'),
                                          (DateKind.TASK, 'Days from another task'),
                                          (DateKind.ANNUAL, 'Annual date')], label='Date rule')
    milestone_name = forms.ChoiceField(required=False, label='Milestone',
        help_text='Select a milestone made available by your site.', choices=())
    source_task_key = forms.ChoiceField(required=False, choices=(), label='Source task',
        help_text='Use this task’s due date when the diary is initialized. Later changes do not move this task.')
    day_offset = forms.IntegerField(required=False, min_value=-2147483648, max_value=2147483647,
                                   label='Day offset', help_text='Use negative days before the source date and positive days after it.')
    month = forms.IntegerField(required=False, min_value=1, max_value=12, label='Month')
    day = forms.IntegerField(required=False, min_value=1, max_value=31, label='Day of month')
    year_offset = forms.IntegerField(required=False, min_value=-32768, max_value=32767, label='Year offset',
                                    help_text='Use zero for the next matching date after diary creation. Negative values select earlier years.')
    owner_kind = forms.ChoiceField(choices=OwnerKind.choices, initial=OwnerKind.TEAM, label='Owner type')
    person_ref = forms.ChoiceField(choices=(), required=False, label='Person')
    role_ref = forms.ChoiceField(choices=(), required=False, label='Ownership group')
    predecessors = forms.MultipleChoiceField(required=False, choices=(), label='Predecessors',
                                             widget=forms.SelectMultiple(attrs={'size': 5}),
                                             help_text='Select tasks that must finish first. Hold Ctrl or Command to select several tasks.')

    def __init__(self, *args, people=(), roles=(), milestones=(), **kwargs):
        """Use the current configured user model and ownership role choices."""
        super().__init__(*args, **kwargs)
        self.fields['milestone_name'].choices = [('', 'Select a milestone'), *milestones]
        self.fields['person_ref'].choices = [('', 'Select a person'), *people]
        self.fields['role_ref'].choices = [('', 'Select a group'), *((role, role) for role in roles)]

    # DV1-025: Template authoring interface.
    def clean(self):
        """Require the fields selected by each date and ownership rule.
        Ignore values from inactive rule fields when constructing the EntrySpec.
        """
        data = super().clean()
        kind = data.get('date_kind')

        # Milestone rules require a stable milestone name, rather than a host event date.
        if kind in {DateKind.SOURCE, DateKind.RELATIVE} and not data.get('milestone_name'):
            self.add_error('milestone_name', 'Select a milestone.')
        if kind == DateKind.TASK and not data.get('source_task_key'):
            self.add_error('source_task_key', 'Select a source task.')

        # Annual dates must be possible in a leap year, including February 29.
        if kind == DateKind.ANNUAL:
            try:
                date(2000, data.get('month'), data.get('day'))
            except (TypeError, ValueError):
                self.add_error('day', 'Enter a valid month and day.')

        # A selected owner type must have its corresponding reference.
        if data.get('owner_kind') == OwnerKind.PERSON and not data.get('person_ref'):
            self.add_error('person_ref', 'Select a person.')

        # Role selection is optional only for the other ownership types.
        if data.get('owner_kind') == OwnerKind.ROLE and not data.get('role_ref'):
            self.add_error('role_ref', 'Select an ownership group.')
        return data

    # DV1-025: Template authoring interface.
    def entry_spec(self):
        """Return an EntrySpec from this valid form with irrelevant rule fields cleared."""
        data = self.cleaned_data
        values = {name: data[name] for name in ('entry_key', 'name', 'description', 'date_kind', 'owner_kind')}
        kind = data['date_kind']

        # Milestone rules share the same named reference.
        if kind in {DateKind.SOURCE, DateKind.RELATIVE}:
            values['milestone_name'] = data['milestone_name']

        # Relative dates use a signed day offset, including zero.
        if kind in {DateKind.RELATIVE, DateKind.TASK}:
            values['day_offset'] = data.get('day_offset') or 0
        if kind == DateKind.TASK:
            values['source_task_key'] = data['source_task_key']

        # DV1-051: Annual rules use the next matching date after diary creation.
        if kind == DateKind.ANNUAL:
            values.update(month=data['month'], day=data['day'], year_offset=data.get('year_offset') or 0)

        # Person and role references are mutually exclusive in stored entries.
        if data['owner_kind'] == OwnerKind.PERSON:
            values['person_ref'] = data['person_ref']

        # Whole-team ownership keeps both individual reference fields empty.
        elif data['owner_kind'] == OwnerKind.ROLE:
            values['role_ref'] = data['role_ref']
        return EntrySpec(**values)


class TemplateTaskFormSet(BaseFormSet):
    """Validate a complete proposed task graph, including unsaved dependency edits."""

    # DV1-027: Safe template predecessor editor.
    # Partial DV1-013: Generic identity and role adapters.
    def __init__(self, *args, **kwargs):
        """Build current person, group, and predecessor choices for all submitted task rows."""
        milestones = kwargs.pop('milestones', ())
        groups = access_groups()
        users = get_user_model()._default_manager.filter(groups__name__in=groups.values()).distinct()
        people = tuple((f'user:{user.pk}', str(user)) for user in users)
        kwargs['form_kwargs'] = {'people': people, 'roles': sorted(task_owner_roles()), 'milestones': milestones}
        self.max_num = editor_task_limit()
        self.absolute_max = self.max_num + 50
        super().__init__(*args, **kwargs)
        choices = []
        successors = {}
        for form in self.forms:
            key = form['entry_key'].value()
            name = form['name'].value()

            # Only complete task identities can be presented as predecessor choices.
            if key and name and not form['DELETE'].value():
                choices.append((str(key), name))
                for predecessor in form['predecessors'].value() or ():
                    successors.setdefault(str(predecessor), set()).add(str(key))
        for form in self.forms:
            excluded, pending = set(), [str(form['entry_key'].value())]

            # Current submitted successors cannot be predecessors without creating a cycle.
            while pending:
                key = pending.pop()

                # Visit each task once even when several dependency paths reach it.
                if key not in excluded:
                    excluded.add(key)
                    pending.extend(successors.get(key, ()))

            # Apply the same exclusions to server-rendered choices and browser updates.
            form.fields['predecessors'].choices = [(key, name) for key, name in choices if key not in excluded]
            # Date references have their own graph; completion dependencies do not restrict these choices.
            form.fields['source_task_key'].choices = [('', 'Select a source task'),
                *((key, name) for key, name in choices if key != str(form['entry_key'].value()))]

    def add_fields(self, form, index):
        """Apply deletion-control classes to stored rows and the empty browser prototype."""
        super().add_fields(form, index)
        form.fields['DELETE'].widget.attrs['class'] = 'diary-input diary-template-field-delete'

    # DV1-027: Safe template predecessor editor.
    def clean(self):
        """Reject duplicate task names and invalid proposed dependency graphs before saving."""
        super().clean()

        # Individual field errors must be corrected before cross-task validation can run.
        if any(self.errors):
            return

        # Deleted and unused extra rows do not belong to the proposed version.
        forms_to_save = [form for form in self.forms if form.cleaned_data and not self._should_delete_form(form)]
        names = [form.cleaned_data['name'].casefold() for form in forms_to_save]

        # Case-insensitive names must be unique within each saved version.
        if len(names) != len(set(names)):
            raise ValidationError('Use a different name for each task.')
        self.graph = validate_template_graph(
            (form.cleaned_data['entry_key'] for form in forms_to_save),
            {form.cleaned_data['entry_key']: form.cleaned_data['predecessors'] for form in forms_to_save},
        )
        self.specs = tuple(form.entry_spec() for form in forms_to_save)
        task_date_order(self.specs)

    # DV1-017: Empty-group warnings during template editing.
    @cached_property
    def empty_roles(self):
        """Return configured ownership groups without current members for this request."""
        populated = set(Group.objects.filter(user__isnull=False).values_list('name', flat=True))
        return sorted(task_owner_roles() - populated)

    # DV1-017: Empty-group warnings during template editing.
    def ownership_warnings(self):
        """Return task-specific warnings for selected groups with no current members."""
        warnings = []
        for form in self.forms:
            kind = form['owner_kind'].value()
            role = form['role_ref'].value()

            # Warnings apply only to selected role ownership and do not change its assignment.
            if kind == OwnerKind.ROLE and role and role in self.empty_roles and not form['DELETE'].value():
                warnings.append(f'{form["name"].value() or "Unnamed task"}: No role members — {role}.')
        return warnings


def editor_task_limit():
    """Return a task row limit based on the host's Django POST field limit.
    Reserve twenty fields for metadata and formset management, with an upper bound of two hundred tasks.
    """
    limit = settings.DATA_UPLOAD_MAX_NUMBER_FIELDS

    # An unlimited host request still uses the editor's bounded task row limit.
    if limit is None:
        return 200
    return min(200, max(0, (limit - 20) // (len(TemplateTaskForm.base_fields) + 1)))


# DV1-029, DV1-030, DV1-033: Task creation with server-controlled ownership.
class TaskCreateForm(TemplateTaskForm):
    """Define diary task fields and reject ownership choices outside the caller's permissions."""

    fixed_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}), label='One-time date')
    add_to_template = forms.BooleanField(required=False, label='Add to template for future diaries')
    expected_version_key = forms.UUIDField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, actor, source_tasks=(), **kwargs):
        """Read current eligible owners and configure controls for the authenticated caller."""
        self.actor = actor
        self.manager = access_groups()['manager'] in actor.groups
        users = get_user_model()._default_manager.filter(
            is_active=True, groups__name__in=access_groups().values()).distinct()
        people = tuple((f'user:{user.pk}', user_display_name(user)) for user in users)
        super().__init__(*args, people=people, roles=sorted(task_owner_roles()), **kwargs)
        self.fields.pop('predecessors')
        self.fields['source_task_key'].choices = [('', 'Select a source task'),
            *((str(entry['entry_key']), entry['name']) for entry in source_tasks if entry.get('date') is not None)]
        self.fields['source_task_key'].help_text = 'Use a visible task’s current due date once, when this task is added. Later source changes do not move this date.'
        self.fields['milestone_name'].choices = [('', 'Select a milestone'),
            *Milestone.objects.order_by('name').values_list('name', 'label')]
        self.fields['milestone_name'].help_text = 'Select an existing milestone for a milestone date rule.'
        self.fields['date_kind'].choices = [*self.fields['date_kind'].choices, (DateKind.ONCE, 'One-time date')]
        self.initial.setdefault('date_kind', DateKind.ONCE)
        self.initial.setdefault('owner_kind', OwnerKind.PERSON)
        self.initial.setdefault('person_ref', actor.reference)

        # Ordinary users cannot change ownership or request a template revision through hidden fields.
        if not self.manager:
            for name in ('owner_kind', 'person_ref', 'role_ref', 'add_to_template', 'expected_version_key'):
                self.fields[name].disabled = True
                self.fields[name].widget = forms.HiddenInput()
        for name, field in self.fields.items():
            field.widget.attrs['class'] = f'diary-create-control diary-create-field-{name.replace("_", "-")}'

    def clean(self):
        """Validate the selected date rule and reject forged ordinary-user ownership inputs."""
        data = super().clean()

        # An exact date is required when this task uses a one-time rule.
        if data.get('date_kind') == DateKind.ONCE and not data.get('fixed_date'):
            self.add_error('fixed_date', 'Enter a one-time date.')

        # Disabled fields protect storage, while explicit rejection exposes modified ownership requests.
        if not self.manager:
            allowed = {'owner_kind': OwnerKind.PERSON, 'person_ref': self.actor.reference,
                       'role_ref': '', 'add_to_template': '', 'expected_version_key': ''}
            for name, value in allowed.items():

                # Forms accept plain dictionaries and query dictionaries with repeated field values.
                values = (self.data.getlist(self.add_prefix(name)) if hasattr(self.data, 'getlist')
                          else (self.data.get(self.add_prefix(name), value),))

                # Every submitted value must agree with the server's personal ownership rule.
                if any(item != value for item in values):
                    self.add_error(None, 'Personal tasks must belong to you and cannot change a template.')
                    break
        return data

    def entry_spec(self):
        """Return the validated task specification with an exact date when selected."""
        spec = super().entry_spec()

        # One-time rules store an exact date instead of a milestone or annual rule.
        if spec.date_kind == DateKind.ONCE:
            spec = replace(spec, fixed_date=self.cleaned_data['fixed_date'])
        return spec


# DV1-033: Require a separate reusable rule before a template addition.
class ReusableTaskRuleForm(StyledForm):
    """Define future date fields while keeping the diary task's identity and owner."""

    date_kind = forms.ChoiceField(label='Future date rule', choices=(
        (DateKind.SOURCE, 'Milestone date'), (DateKind.RELATIVE, 'Days from a milestone'),
        (DateKind.TASK, 'Days from another task'),
        (DateKind.ANNUAL, 'Annual date')))
    milestone_name = forms.ChoiceField(required=False, label='Future milestone')
    source_task_key = forms.ChoiceField(required=False, choices=(), label='Future source task')
    day_offset = forms.IntegerField(required=False, min_value=-2147483648, max_value=2147483647, label='Future day offset')
    month = forms.IntegerField(required=False, min_value=1, max_value=12, label='Future month')
    day = forms.IntegerField(required=False, min_value=1, max_value=31, label='Future day')
    year_offset = forms.IntegerField(required=False, min_value=-32768, max_value=32767, label='Future year offset')

    def __init__(self, *args, source_tasks=(), **kwargs):
        """Use existing milestones and stable styling classes for each future-rule control."""
        super().__init__(*args, **kwargs)
        self.fields['date_kind'].choices = [('', 'Select a future date rule'), *self.fields['date_kind'].choices]
        self.fields['milestone_name'].choices = [('', 'Select a milestone'),
                                                *Milestone.objects.order_by('name').values_list('name', 'label')]
        self.fields['source_task_key'].choices = [('', 'Select a source task'),
            *((str(entry['entry_key']), entry['name']) for entry in source_tasks)]
        for name, field in self.fields.items():
            field.widget.attrs['class'] = f'diary-create-control diary-create-future-{name.replace("_", "-")}'

    def clean(self):
        """Require the fields needed by the explicitly selected reusable rule."""
        data = super().clean()

        # Milestone rules cannot silently select an unrelated source date.
        if data.get('date_kind') in {DateKind.SOURCE, DateKind.RELATIVE} and not data.get('milestone_name'):
            self.add_error('milestone_name', 'Select a future milestone.')
        if data.get('date_kind') == DateKind.TASK and not data.get('source_task_key'):
            self.add_error('source_task_key', 'Select a future source task.')

        # A leap year permits February 29 while rejecting impossible annual dates.
        if data.get('date_kind') == DateKind.ANNUAL:
            try:
                date(2000, data.get('month'), data.get('day'))
            except (TypeError, ValueError):
                self.add_error('day', 'Enter a valid future month and day.')
        return data

    def entry_spec(self, task):
        """Return the reusable rule with the diary task's unchanged identity, text, and owner."""
        data = self.cleaned_data
        values = {'date_kind': data['date_kind'], 'fixed_date': None, 'milestone_name': '',
                  'month': None, 'day': None, 'day_offset': 0, 'year_offset': 0, 'source_task_key': None}

        # Annual rules need only their explicit month, day, and optional year offset.
        if data['date_kind'] == DateKind.ANNUAL:
            values.update(month=data['month'], day=data['day'], year_offset=data.get('year_offset') or 0)
        elif data['date_kind'] == DateKind.TASK:
            values.update(source_task_key=data['source_task_key'], day_offset=data.get('day_offset') or 0)

        # Source and relative rules both keep the chosen milestone.
        else:
            values['milestone_name'] = data['milestone_name']

            # Only relative rules use the signed offset from the milestone date.
            if data['date_kind'] == DateKind.RELATIVE:
                values['day_offset'] = data.get('day_offset') or 0
        return replace(task, **values)


# DV1-032: Due-date edits use a revision from the inspected task.
class TaskDueDateForm(forms.Form):
    """Read a required due date and the task revision used for stale-form detection."""

    due_date = forms.DateField(label='Due date', widget=forms.DateInput(attrs={
        'type': 'date', 'class': 'diary-detail-control diary-detail-due-date'}))
    revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput(attrs={'class': 'diary-detail-revision'}))


# DV1-036, DV1-037: Completion controls carry an opaque fingerprint without private task identifiers.
class TaskCompletionForm(forms.Form):
    """Read the inspected task revision and opaque predecessor-state fingerprint."""

    revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput(attrs={'class': 'diary-detail-revision'}))
    blocker_token = forms.CharField(max_length=64, widget=forms.HiddenInput(attrs={'class': 'diary-detail-blocker-token'}))


TaskFormSet = formset_factory(TemplateTaskForm, formset=TemplateTaskFormSet, extra=0,
                              can_delete=True, max_num=200, validate_max=True, absolute_max=250)


# DV1-040: Explicit recovery keeps unresolved template tasks visible to managers.
class TaskOwnerRecoveryForm(forms.Form):
    """Collect a task revision and an eligible replacement owner without changing template versions."""

    entry_key = forms.UUIDField(widget=forms.HiddenInput)
    revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    owner_kind = forms.ChoiceField(choices=OwnerKind.choices, label='New owner type')
    person_ref = forms.ChoiceField(required=False, label='New person')
    role_ref = forms.ChoiceField(required=False, label='New ownership group')

    def __init__(self, *args, **kwargs):
        """Read active DiaryUser members and configured ownership groups for current form choices."""
        super().__init__(*args, **kwargs)
        users = get_user_model()._default_manager.filter(
            is_active=True, groups__name=access_groups()['user']).distinct()
        self.fields['person_ref'].choices = [('', 'Select a person'),
            *((f'user:{user.pk}', user_display_name(user)) for user in users)]
        self.fields['role_ref'].choices = [('', 'Select a group'),
            *((role, role) for role in sorted(task_owner_roles()))]
        for name, field in self.fields.items():
            field.widget.attrs['class'] = f'diary-recovery-control diary-recovery-{name.replace("_", "-")}'

    def clean(self):
        """Require the selected owner reference and clear references for inactive owner types."""
        data = super().clean()

        # Person ownership requires an active member of the configured DiaryUser group.
        if data.get('owner_kind') == OwnerKind.PERSON and not data.get('person_ref'):
            self.add_error('person_ref', 'Select a person.')

        # Role ownership requires an explicit configured group selection.
        if data.get('owner_kind') == OwnerKind.ROLE and not data.get('role_ref'):
            self.add_error('role_ref', 'Select an ownership group.')

        # Other ownership types must not retain a previous person reference.
        if data.get('owner_kind') != OwnerKind.PERSON:
            data['person_ref'] = ''

        # Whole-team and person ownership must not retain a previous role reference.
        if data.get('owner_kind') != OwnerKind.ROLE:
            data['role_ref'] = ''
        return data


class TaskNoteForm(StyledForm):
    """Keep the note key across validation errors and repeated submissions."""

    note_key = forms.UUIDField(widget=forms.HiddenInput)
    text = forms.CharField(label='Note', widget=forms.Textarea(attrs={'rows': 4}),
                           help_text='Add to the history. Saved notes cannot be edited or removed.')
