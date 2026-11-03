"""DV1-041: Verify package fragments in independent host shells and clean POST navigation."""
from django.template import engines
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings


class HostEmbeddingTests(SimpleTestCase):
    """Keep package markup reusable without copied partials or host application imports."""

    def context(self):
        """Return a selected Diary and one visible task with optional host rendering controls."""
        task = {'name': 'Host task', 'entry_key': 'task-key', 'detail_url': '/host/task/',
                'can_edit_date': True, 'orphaned': True, 'ready': True}
        return {'diary_data': {'key': 'diary-key', 'name': 'Host Diary'},
                'tasks': [task], 'task': task, 'task_groups': [{'key': 'diary-key', 'name': 'Host Diary', 'tasks': [task]}],
                'templates': [{'name': 'Host template'}], 'creation_form': True,
                'diary_ui': {'trusted_scope': True, 'selection_url': '/host/select/', 'task_detail_url': '/host/task/',
                             'form_fields': {'host_state': '\"><script>unsafe</script>'}}}

    def test_fragments_use_host_post_selection_and_escape_fields(self):
        """Render host task and template controls without identifier URLs or an extra document shell."""
        for partial in ('personal_diary', 'manager_diary', 'template_list', 'task_create'):
            with self.subTest(partial=partial):
                html = render_to_string(f'Diary/partials/{partial}.html', self.context())
                self.assertIn('action="/host/select/"', html)
                self.assertIn('name="host_state"', html)
                self.assertIn('&lt;script&gt;unsafe&lt;/script&gt;', html)
                self.assertNotIn('<script>unsafe</script>', html)
                self.assertNotIn('?diary_key=', html)
                self.assertNotIn('<!doctype', html.lower())
        html = render_to_string('Diary/partials/manager_diary.html', self.context())
        self.assertIn('form="diary-select-task"', html)
        html = render_to_string('Diary/partials/template_list.html', self.context())
        self.assertIn('form="diary-select-template"', html)

    def test_edit_forms_include_escaped_host_fields(self):
        """Carry host state in task recovery, date, completion, creation, and template edit forms."""
        for partial, count in (('task_detail', 3), ('task_create', 3), ('template_editor', 1)):
            with self.subTest(partial=partial):
                html = render_to_string(f'Diary/partials/{partial}.html', self.context())
                self.assertEqual(html.count('name="host_state"'), count)
                self.assertNotIn('?diary_key=', html)

    def test_default_navigation_keeps_standalone_links_and_selectors(self):
        """Preserve the package's existing GET navigation when a host supplies no rendering controls."""
        context = self.context()
        context.pop('diary_ui')
        html = render_to_string('Diary/partials/manager_diary.html', context)
        self.assertIn('?diary_key=diary-key', html)
        self.assertIn('href="/host/task/"', html)
        self.assertNotIn('diary-select-task', html)

    def test_complete_pages_can_use_host_base_or_direct_includes(self):
        """Use a host base or a direct fragment include without duplicating the package content."""
        templates = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'OPTIONS': {'loaders': [
            ('django.template.loaders.locmem.Loader', {'host/base.html':
                '<!doctype html><html><body><aside>Host sidebar</aside>{% block diary_content %}{% endblock %}</body></html>'}),
            'django.template.loaders.app_directories.Loader']}}]
        with override_settings(TEMPLATES=templates):
            context = self.context()
            context['diary_base_template'] = 'host/base.html'
            for name in ('personal_diary', 'manager_diary', 'task_detail', 'task_create', 'template_list', 'template_editor'):
                with self.subTest(page=name):
                    html = render_to_string(f'Diary/{name}.html', context)
                    self.assertEqual(html.lower().count('<!doctype html>'), 1)
                    self.assertIn('<aside>Host sidebar</aside>', html)
                    self.assertNotIn('class="diary-document"', html)
            html = engines['django'].from_string(
                '<!doctype html><html><body>{% include "Diary/partials/personal_diary.html" %}</body></html>'
            ).render(context)
            self.assertEqual(html.lower().count('<!doctype html>'), 1)
            self.assertIn('Host task', html)

    def test_manager_filter_actions_stay_inside_panel(self):
        """Keep Apply filters and Clear filters inside the package's manager filter fieldset."""
        html = render_to_string('Diary/partials/manager_diary.html', self.context())
        panel = html.split('<fieldset class="diary-manager-filter-group">', 1)[1].split('</fieldset>', 1)[0]
        self.assertIn('diary-manager-filter-controls', panel)
        self.assertIn('diary-manager-apply', panel)
        self.assertIn('diary-manager-reset', panel)
        self.assertIn('Clear filters', panel)
        self.assertIn('diary-manager-filter-help', panel)
