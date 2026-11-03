from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.staticfiles import finders
from django.template.loader import get_template
from django.test import SimpleTestCase, override_settings


# Verifies DV1-011: Base template and reusable task fragment.
# Verifies DV1-041: Complete pages, fragments, and styling interface.
class DiaryStyleOverrideTests(SimpleTestCase):
    @override_settings(
        STATIC_URL='/static/',
        TEMPLATES=[{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [], 'APP_DIRS': True}],
    )
    def test_task_list_is_a_full_page_and_can_be_embedded_without_nested_documents(self):
        from django.template import engines
        context = {'tasks': [{'name': '<Unsafe title>', 'state': 'blocked', 'late': True, 'owner_kind': 'team'}]}
        page = get_template('Diary/task_list.html').render(context)
        self.assertEqual(page.lower().count('<!doctype html>'), 1)
        self.assertIn('Diary/styles/diary.css', page)
        self.assertIn('Blocked', page)
        self.assertIn('Late', page)
        self.assertIn('&lt;Unsafe title&gt;', page)
        host = engines['django'].from_string(
            '<!doctype html><html><head><title>Host</title></head><body>'
            '{% include "Diary/partials/task_list.html" %}</body></html>'
        ).render(context)
        self.assertEqual(host.lower().count('<!doctype html>'), 1)
        self.assertEqual(host.count('<html>'), 1)
        self.assertEqual(host.count('<body>'), 1)
        self.assertIn('diary-task-list', host)

    @override_settings(STATIC_URL='/static/')
    def test_project_template_can_extend_default_and_add_styles(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            override = root / 'Diary' / 'base.html'
            override.parent.mkdir()
            override.write_text(
                '{% extends "Diary/base.html" %}'
                '{% block diary_extra_styles %}<link href="/custom.css" rel="stylesheet">{% endblock %}'
                '{% block diary_content %}<h1>Host calendar</h1>{% endblock %}'
            )
            engines = [{'BACKEND': 'django.template.backends.django.DjangoTemplates',
                        'DIRS': [str(root)], 'APP_DIRS': True}]
            with override_settings(TEMPLATES=engines):
                html = get_template('Diary/base.html').render({})
            self.assertIn('Diary/styles/diary.css', html)
            self.assertIn('/custom.css', html)
            self.assertIn('<h1>Host calendar</h1>', html)

    def test_project_static_directory_can_replace_default_stylesheet(self):
        with override_settings(STATICFILES_DIRS=[]):
            default = finders.find('Diary/styles/diary.css')
        self.assertIsNotNone(default)
        with TemporaryDirectory() as folder:
            override = Path(folder) / 'Diary' / 'styles' / 'diary.css'
            override.parent.mkdir(parents=True)
            override.write_text('.diary { --diary-accent: navy; }')
            with override_settings(STATICFILES_DIRS=[folder]):
                self.assertEqual(Path(finders.find('Diary/styles/diary.css')), override)
