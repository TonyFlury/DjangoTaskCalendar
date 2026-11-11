"""Optional compatibility calendar routes; diary role endpoints own presentation switching."""
from django.utils.cache import patch_cache_control, patch_vary_headers
from django.views import View

from .calendar_rendering import CalendarRenderingMixin
from .views import DiaryScopeMixin, DiaryOwnerLabelsMixin


class TaskCalendarView(CalendarRenderingMixin, DiaryScopeMixin, DiaryOwnerLabelsMixin, View):
    """Render the same authorised period used by TaskCalendarDataView.
    Hosts supply permitted diary keys and may replace templates and task URL names.
    """

    access_roles = ('manager', 'user')
    template_name = 'Diary/task_calendar.html'
    calendar_mode = None
    data_only = False

    def dispatch(self, request, *args, **kwargs):
        """Authenticate through the shared scope mixin and prevent shared response caching."""
        response = super().dispatch(request, *args, **kwargs)
        patch_cache_control(response, private=True, no_store=True)
        patch_vary_headers(response, ('Cookie',))
        return response

    def get(self, request, *args, **kwargs):
        """Compatibility calendar route; existing diary routes also provide presentations."""
        return self.render_calendar(request)


class TaskCalendarDataView(TaskCalendarView):
    """JSON equivalent, retaining trusted scope, validation and private/no-store headers."""

    data_only = True
