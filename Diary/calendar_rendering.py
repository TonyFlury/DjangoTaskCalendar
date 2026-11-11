"""DFUT-018: Host-extensible calendar documents, fragments and JSON reads."""
from datetime import timedelta
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django import forms
from django.http import JsonResponse, QueryDict
from django.shortcuts import render

from .api import DiaryAPI
from .calendar_forms import TaskCalendarForm
from .calendar_navigation import calendar_return_token
from .choices import OwnerKind


class CalendarRenderingMixin:
    """Package-owned calendar rendering shared by the existing diary endpoints."""

    calendar_template_name = 'Diary/task_calendar.html'
    calendar_mode = None
    data_only = False

    def render_calendar(self, request, *, presentation=None, filters=None):
        """Validate navigation once, then render HTML or JSON from the shared period service."""
        from .views import DjangoOwnerDirectory
        legacy = filters is not None
        source_filters = filters
        fixed_mode = self.presentation_mode if legacy else self.calendar_mode
        params = request.GET.copy()
        task_status, only_late = 'all', False
        if legacy:
            params = QueryDict(mutable=True)
            for name in ('view', 'period', 'date', 'day', 'page', 'late_page', 'undated_page', 'panel'):
                if name in request.GET:
                    params.setlist(name, request.GET.getlist(name))
            params['view'] = presentation
            params['mode'] = fixed_mode
            selected = filters.cleaned_data
            if fixed_mode == 'personal':
                task_status = selected.get('task_status') or 'all'
                show_blocked = selected['show_blocked'] or task_status != 'all'
                params['hide_blocked'] = '' if show_blocked else '1'
                params['include_whole_team'] = '1' if selected['include_whole_team'] else ''
            else:
                params['include_completed'] = '1' if selected['include_completed'] else ''
                params['hide_blocked'] = '1' if selected['exclude_blocked'] else ''
                only_late = selected['exclude_non_late']
        elif fixed_mode and 'mode' not in params:
            params['mode'] = fixed_mode
        form = TaskCalendarForm(params)
        context = {**self.view_context, 'calendar_form': form, 'calendar_error': '', 'calendar': None}
        if not form.is_valid():
            return self.error(context, 'Choose valid calendar dates and filters.', 400)
        values = form.cleaned_data
        if fixed_mode and values['mode'] != fixed_mode:
            return self.error(context, 'This calendar has a fixed display mode.', 400)
        try:
            key = self.selected_key()
            data = DiaryAPI(actor=self.actor).task_period(view=values['view'], period=values['period'] or None,
                anchor_date=values['date'], selected_day=values['day'], mode=values['mode'], diary_key=key,
                include_completed=values['include_completed'], show_blocked=not values['hide_blocked'],
                include_whole_team=values['include_whole_team'], query=values['query'], owner=values['owner'],
                page=values['page'] or 1, late_page=values['late_page'] or 1, undated_page=values['undated_page'] or 1,
                directory=DjangoOwnerDirectory(), task_status=task_status, only_late=only_late)
        except (ValidationError, ValueError, TypeError, AttributeError) as error:
            message = ' '.join(error.messages) if isinstance(error, ValidationError) else 'Select one valid diary.'
            return self.error(context, message, 400)
        except ObjectDoesNotExist:
            return self.error(context, 'The selected diary is unavailable.', 404)
        if self.data_only:
            return JsonResponse({'data': data})
        # Build links exclusively from validated state; a query never supplies permissions.
        state = {'view': data['view'], 'period': data['period'], 'date': data['anchor_date'].isoformat()}
        if not legacy:
            state['mode'] = data['mode']
        trusted = self.view_context.get('diary_ui', {}).get('trusted_scope')
        if key is not None and not trusted:
            state['diary_key'] = str(key)
        filter_values = source_filters.cleaned_data if legacy else {
            name: values[name] for name in ('query', 'owner', 'include_completed', 'hide_blocked', 'include_whole_team')}
        for name, value in filter_values.items():
            if value:
                state[name] = '1' if value is True else value
        if values['day']:
            state['day'] = data['selected_day'].isoformat()
        if values['panel']:
            state.update(panel=values['panel'], day=data['selected_day'].isoformat())
            for name in ('page', 'late_page', 'undated_page'):
                if values[name]:
                    state[name] = values[name]

        def link(**changes):
            query = {**state, **changes}
            return request.path + '?' + urlencode({name: value for name, value in query.items() if value is not None})

        token = calendar_return_token(request, state)
        groups = [day['tasks'] for day in data['days']] + [data['day']['tasks'], data['late']['tasks'], data['undated']['tasks']]
        tasks = [row for group in groups for row in group]
        owner_rows = [{'role_ref': item['reference'] if item['kind'] == OwnerKind.ROLE else '',
                       'person_ref': item['reference'] if item['kind'] == OwnerKind.PERSON else '',
                       'completed_by_ref': ''} for item in data['owners']]
        labels, _ = self.get_owner_labels([*tasks, *owner_rows])
        owner_choices = [('', 'All owners')]
        for item in data['owners']:
            label = (labels.get(item['reference'], item['reference']) if item['kind'] == OwnerKind.PERSON
                     else item['reference'] if item['kind'] == OwnerKind.ROLE else 'Whole team')
            owner_choices.append((item['value'], label))
        form.fields['owner'].widget = forms.Select(choices=owner_choices, attrs={'class': 'diary-input'})
        for row in tasks:
            row['owner_label'] = (labels.get(row['person_ref'], row['person_ref']) if row['owner_kind'] == OwnerKind.PERSON
                                  else row['role_ref'] if row['owner_kind'] == OwnerKind.ROLE else 'Whole team')
            target = self.task_url(row['entry_key'], row['diary_key'])
            return_state = dict(state)
            if row['date'] is not None and data['start'] <= row['date'] < data['end']:
                return_state.update(day=row['date'].isoformat(), panel='day')
            parts = urlsplit(target)
            query = {**dict(parse_qsl(parts.query)), 'calendar_return': calendar_return_token(request, return_state)}
            if not trusted:
                query['diary_key'] = str(row['diary_key'])
            row['detail_url'] = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        for day in data['days']:
            day['url'] = link(day=day['date'].isoformat(), panel='day', page=None) + '#diary-calendar-day-heading'
            week_anchor = day['date'].isoformat()
            day['week_url'] = link(view='week', period='week', date=week_anchor, day=None, panel=None, page=None)
        for panel, page_param in (('day', 'page'), ('late', 'late_page'), ('undated', 'undated_page')):
            item = data[panel]
            page_panel = None if data['view'] == 'day' and panel == 'day' else panel
            item['previous_url'] = link(**{page_param: item['previous'], 'panel': page_panel, 'day': data['selected_day'].isoformat()}) if item['previous'] else ''
            item['next_url'] = link(**{page_param: item['next'], 'panel': page_panel, 'day': data['selected_day'].isoformat()}) if item['next'] else ''
        data['last_date'] = data['end'] - timedelta(days=1)
        manager_allowed = DiaryAPI.permission_groups()['manager'] in self.actor.groups
        base = {'panel': None, 'day': None, 'page': None, 'late_page': None, 'undated_page': None}
        context.update(calendar=data, calendar_return_token=token,
            calendar_close_url=link(**{**base, 'day': data['selected_day'].isoformat()}),
            calendar_previous_url=link(**{**base, 'date': data['previous_date'].isoformat()}),
            calendar_next_url=link(**{**base, 'date': data['next_date'].isoformat()}),
            calendar_today_url=link(**{**base, 'date': data['today'].isoformat()}),
            calendar_tabs=[{'name': name.capitalize(), 'active': name == data['view'],
                            'url': link(**{**base, 'view': name, 'period': data['period'] if name == 'list' else name,
                                           'date': data['anchor_date'].isoformat() if name == 'list' else data['selected_day'].isoformat(),
                                           'day': data['selected_day'].isoformat() if name == 'list' else None})}
                           for name in ('list', 'day', 'week', 'month')],
            calendar_filters=list(source_filters) if legacy else [form[name] for name in ('query', 'mode', 'include_completed', 'hide_blocked', 'include_whole_team', 'owner')
                              if not (name == 'mode' and (fixed_mode or not manager_allowed))
                              and not (name == 'owner' and data['mode'] != 'manager')
                              and not (name == 'include_whole_team' and data['mode'] != 'personal')],
            calendar_filter_state={name: value for name, value in state.items() if name in {'view', 'period', 'date', 'diary_key', 'day'}},
            calendar_reset_url=link(**{**dict.fromkeys(filter_values, None), **base}),
            calendar_filtered=any(value and not (name == 'task_status' and value == 'all') for name, value in filter_values.items()),
            calendar_show_day=values['panel'] == 'day', calendar_show_late=values['panel'] == 'late',
            calendar_show_undated=values['panel'] == 'undated', calendar_legacy_filters=legacy,
            calendar_presentation_template=f"Diary/partials/calendar_{data['view']}.html")
        # Date navigation is a separate form; supply filter state as hidden fields.
        context['calendar_date_state'] = {name: value for name, value in state.items() if name not in {'date', 'panel', 'day', 'page', 'late_page', 'undated_page'}}
        context['calendar_late_url'] = link(panel='late', day=None, late_page=None) + '#diary-calendar-late-heading'
        context['calendar_undated_url'] = link(panel='undated', day=None, undated_page=None) + '#diary-calendar-undated-heading'
        return render(request, self.calendar_template_name, context)

    def error(self, context, message, status):
        """Return errors without exposing an unvalidated task selection."""
        if self.data_only:
            return JsonResponse({'error': message}, status=status)
        context['calendar_error'] = message
        return render(self.request, self.calendar_template_name, context, status=status)

