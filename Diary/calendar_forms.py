"""DFUT-018: Bounded calendar navigation and filter inputs."""
from django import forms

from .forms import StyledForm


class TaskCalendarForm(StyledForm):
    """Keep invalid period/filter values from silently broadening the result."""

    view = forms.ChoiceField(choices=(('list', 'List'), ('day', 'Day'), ('week', 'Week'), ('month', 'Month')))
    period = forms.ChoiceField(required=False, choices=(('day', 'Day'), ('week', 'Week'), ('month', 'Month')))
    date = forms.DateField(required=False, input_formats=('%Y-%m-%d',), widget=forms.DateInput(attrs={'type': 'date'}), label='Go to date')
    day = forms.DateField(required=False, input_formats=('%Y-%m-%d',))
    mode = forms.ChoiceField(choices=(('personal', 'My tasks'), ('manager', 'Manager diary')))
    query = forms.CharField(required=False, max_length=160, label='Find tasks')
    include_completed = forms.BooleanField(required=False, label='Show completed tasks')
    hide_blocked = forms.BooleanField(required=False, label='Hide blocked tasks')
    include_whole_team = forms.BooleanField(required=False, label='Include whole-team tasks')
    owner = forms.CharField(required=False, max_length=200, label='Owner')
    page = forms.IntegerField(required=False, min_value=1, max_value=1000000)
    late_page = forms.IntegerField(required=False, min_value=1, max_value=1000000)
    undated_page = forms.IntegerField(required=False, min_value=1, max_value=1000000)
    panel = forms.ChoiceField(required=False, choices=(('day', 'Day'), ('late', 'Late'), ('undated', 'Undated')))

    def __init__(self, data=None, **kwargs):
        """Default navigation controls while keeping unchecked filters false."""
        data = data.copy() if data is not None else {}
        data.setdefault('view', 'week')
        data.setdefault('mode', 'personal')
        super().__init__(data, **kwargs)

    def clean(self):
        """Reject repeated controls rather than silently choosing one conflicting value."""
        data = super().clean()
        if hasattr(self.data, 'getlist') and any(len(self.data.getlist(name)) > 1 for name in self.fields):
            raise forms.ValidationError('Supply each calendar option once.')
        return data
