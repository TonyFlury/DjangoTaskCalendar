"""Forms for complete template revisions and reusable task rules."""
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
from .roles import access_groups, task_owner_roles
from .template_graph import validate_template_graph


class StyledForm(forms.Form):
    """Give every form control a stable Diary styling class."""

    # Partial DV1-041: Complete pages, fragments, and styling interface.
    def __init__(self, *args, **kwargs):
        """Initialize fields and expose a class for each technical field name."""
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs['class'] = f'diary-input diary-template-field-{name.replace("_", "-")}'


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


class TemplateTaskForm(StyledForm):
    """Collect one reusable task, its ownership, and its proposed predecessor keys."""

    entry_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid4)
    name = forms.CharField(max_length=160, label='Task name')
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))
    date_kind = forms.ChoiceField(choices=[(DateKind.SOURCE, 'Milestone date'),
                                          (DateKind.RELATIVE, 'Days from a milestone'),
                                          (DateKind.ANNUAL, 'Annual date')], label='Date rule')
    milestone_name = forms.SlugField(max_length=80, required=False, label='Milestone name',
                                    help_text='Use a stable name. You can select an existing name or enter a new name.',
                                    widget=forms.TextInput(attrs={'list': 'diary-milestone-names'}))
    milestone_label = forms.CharField(max_length=160, required=False, label='New milestone label',
                                     help_text='Optional. Existing milestone labels stay unchanged.')
    day_offset = forms.IntegerField(required=False, min_value=-2147483648, max_value=2147483647,
                                   label='Day offset', help_text='Use negative days before the milestone and positive days after it.')
    month = forms.IntegerField(required=False, min_value=1, max_value=12, label='Month')
    day = forms.IntegerField(required=False, min_value=1, max_value=31, label='Day of month')
    year_offset = forms.IntegerField(required=False, min_value=-32768, max_value=32767, label='Year offset',
                                    help_text='Use zero for the diary year. Use negative values for earlier years.')
    owner_kind = forms.ChoiceField(choices=OwnerKind.choices, initial=OwnerKind.TEAM, label='Owner type')
    person_ref = forms.ChoiceField(choices=(), required=False, label='Person')
    role_ref = forms.ChoiceField(choices=(), required=False, label='Ownership group')
    predecessors = forms.MultipleChoiceField(required=False, choices=(), label='Predecessors',
                                             widget=forms.SelectMultiple(attrs={'size': 5}),
                                             help_text='Select tasks that must finish first. Hold Ctrl or Command to select several tasks.')

    def __init__(self, *args, people=(), roles=(), **kwargs):
        """Use the current configured user model and ownership role choices."""
        super().__init__(*args, **kwargs)
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
            self.add_error('milestone_name', 'Enter a milestone name.')

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
        if kind == DateKind.RELATIVE:
            values['day_offset'] = data.get('day_offset') or 0

        # Annual rules use the caller's diary year and have no milestone reference.
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
        groups = access_groups()
        users = get_user_model()._default_manager.filter(groups__name__in=groups.values()).distinct()
        people = tuple((f'user:{user.pk}', str(user)) for user in users)
        kwargs['form_kwargs'] = {'people': people, 'roles': sorted(task_owner_roles())}
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
        self.milestone_definitions = {}
        for form in forms_to_save:
            spec = form.entry_spec()

            # New milestone labels are optional and never replace an existing global label.
            if spec.milestone_name:
                label = form.cleaned_data.get('milestone_label')

                # Two tasks cannot define different new labels for the same milestone in one save.
                if (label and self.milestone_definitions.get(spec.milestone_name)
                        and self.milestone_definitions[spec.milestone_name] != label):
                    raise ValidationError('Use the same label for each occurrence of a new milestone name.')
                self.milestone_definitions[spec.milestone_name] = (
                    label or self.milestone_definitions.get(spec.milestone_name))
        self.milestone_definitions = {name: label or name for name, label in self.milestone_definitions.items()}

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


TaskFormSet = formset_factory(TemplateTaskForm, formset=TemplateTaskFormSet, extra=0,
                              can_delete=True, max_num=200, validate_max=True, absolute_max=250)
