"""Package-owned presentation selection for the personal and manager diary URLs."""
from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.utils.cache import patch_cache_control, patch_vary_headers

from .calendar_rendering import CalendarRenderingMixin

SESSION_KEY = 'diary.presentation.v1'
PRESENTATIONS = ('list', 'day', 'week', 'month')


class DiaryPresentationMixin(CalendarRenderingMixin):
    """Keep view preferences per authenticated user and diary role, never as access state."""

    presentation_mode = 'personal'

    def dispatch(self, request, *args, **kwargs):
        """Persist only an explicit, valid presentation after an authorised successful response."""
        response = super().dispatch(request, *args, **kwargs)
        patch_cache_control(response, private=True, no_store=True)
        patch_vary_headers(response, ('Cookie',))
        if response.status_code == 200 and getattr(self, 'presentation', None) in PRESENTATIONS and 'view' in request.GET:
            session = getattr(request, 'session', None)
            if session is not None:
                preferences = session.get(SESSION_KEY, {})
                if not isinstance(preferences, dict) or preferences.get('user') != str(request.user.pk):
                    preferences = {'user': str(request.user.pk)}
                session[SESSION_KEY] = {**preferences, self.presentation_mode: self.presentation}
        return response

    def selected_presentation(self):
        """An explicit URL wins over a user-bound session preference; List remains the default."""
        values = self.request.GET.getlist('view')
        if values:
            if len(values) != 1 or values[0] not in PRESENTATIONS:
                raise ValidationError('Select List, Day, Week, or Month once.')
            self.presentation = values[0]
        else:
            session = getattr(self.request, 'session', None)
            saved = session.get(SESSION_KEY, {}) if session is not None else {}
            self.presentation = (saved.get(self.presentation_mode, 'list')
                                 if isinstance(saved, dict) and saved.get('user') == str(self.request.user.pk) else 'list')
            if self.presentation not in PRESENTATIONS:
                self.presentation = 'list'
        return self.presentation

    def presentation_context(self, filters):
        """Use the same endpoint and validated filter names for every presentation link."""
        query = {name: '1' if value is True else value for name, value in filters.cleaned_data.items() if value}
        for name in ('date', 'day', 'period'):
            if self.request.GET.get(name):
                query[name] = self.request.GET[name]
        if not self.view_context.get('diary_ui', {}).get('trusted_scope'):
            key = self.selected_key()
            if key is not None:
                query['diary_key'] = str(key)
        navigation = {name: value for name, value in query.items() if name in {'date', 'day', 'period', 'diary_key'}}
        return {'diary_presentations': [
            {'name': view.capitalize(), 'active': view == self.presentation,
             'url': self.request.path + '?' + urlencode({**query, 'view': view, 'day': '', 'period': ''})}
            for view in PRESENTATIONS], 'diary_presentation': self.presentation,
            'diary_presentation_state': {'view': self.presentation, **{name: value for name, value in navigation.items() if name != 'diary_key'}},
            'diary_list_reset_url': self.request.path + '?' + urlencode({**navigation, 'view': self.presentation})}
