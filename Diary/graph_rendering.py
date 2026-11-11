"""DFUT-019: Graph presentation using the existing manager endpoint and host hooks."""
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.shortcuts import render

from .api import DiaryAPI
from .calendar_navigation import calendar_return_token
from .choices import OwnerKind


class ManagerGraphRenderingMixin:
    """Render live graph data without requiring graph-specific host controllers."""

    graph_template_name = 'Diary/manager_graph.html'

    def render_manager_graph(self, request, key, filters):
        """Keep matching filters and task navigation shared with the manager's List view."""
        from .views import DjangoOwnerDirectory
        context = {**self.view_context, **self.presentation_context(filters), 'filters': filters, 'graph_error': ''}
        try:
            graph = DiaryAPI(actor=self.actor).diary(key=key).graph(**filters.cleaned_data, directory=DjangoOwnerDirectory())
        except ObjectDoesNotExist:
            context['graph_error'] = 'The selected diary is unavailable.'
            return render(request, self.graph_template_name, context, status=404)
        except ValidationError as error:
            context['graph_error'] = ' '.join(error.messages)
            return render(request, self.graph_template_name, context, status=400)
        state = {'view': 'graph'}
        trusted = self.view_context.get('diary_ui', {}).get('trusted_scope')
        if not trusted:
            state['diary_key'] = str(key)
        state.update({name: '1' for name, value in filters.cleaned_data.items() if value})
        token = calendar_return_token(request, state)
        tasks = [node for node in graph['nodes'] if node['kind'] == 'task']
        labels, members = self.get_owner_labels(tasks)
        for node in tasks:
            node['owner_label'] = (labels.get(node['person_ref'], 'Unavailable owner') if node['owner_kind'] == OwnerKind.PERSON
                                   else node['role_ref'] if node['owner_kind'] == OwnerKind.ROLE else 'Whole team')
            node['owner_members'] = members.get(node['role_ref'], ())
            node['completed_by_label'] = labels.get(node['completed_by_ref'], 'deleted user')
            parts = urlsplit(self.task_url(node['entry_key'], key))
            query = [(name, value) for name, value in parse_qsl(parts.query, keep_blank_values=True)
                     if name != 'calendar_return' and (trusted or name != 'diary_key')]
            query.append(('calendar_return', token))
            if not trusted:
                query.append(('diary_key', str(key)))
            node['detail_url'] = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        context.update(graph_data=graph, tasks=tasks, diary_data=graph['diary'], calendar_return_token=token,
            graph_refresh_url=request.path + '?' + urlencode(state),
            graph_reset_url=request.path + '?' + urlencode({name: value for name, value in state.items()
                                                          if name in {'view', 'diary_key'}}),
            graph_filter_state={name: value for name, value in state.items() if name in {'view', 'diary_key'}})
        return render(request, self.graph_template_name, context)
