"""Named Diary routes for templates, task pages, and private-safe HTTP data reads."""
from django.urls import path

from .views import (DiaryDataView, ManagerDiaryView, PersonalDiaryView, TaskCreateView,
                    TaskDetailView, TemplateApplyView, TemplateCreateView, TemplateEditorView)

app_name = 'Diary'

# DV1-024: Template chooser and selected-template routes.
# DV1-018: Required HTML routes exist. Template-to-diary copying is not required.
urlpatterns = [

    # DV1-031: Read-only data routes retain authenticated identity, trusted scope, and personal-task privacy.
    path('data/diary/', DiaryDataView.as_view(), name='data-diary'),
    path('data/active/', DiaryDataView.as_view(resource='active'), name='data-active'),
    path('data/personal/', DiaryDataView.as_view(resource='personal'), name='data-personal'),
    path('data/search/', DiaryDataView.as_view(resource='search'), name='data-search'),
    path('data/tasks/<uuid:entry_key>/', DiaryDataView.as_view(resource='task'), name='data-task'),
    path('data/tasks/<uuid:entry_key>/predecessors/',
         DiaryDataView.as_view(resource='predecessors'), name='data-predecessors'),

    # DV1-029, DV1-030, DV1-033: Task creation retains the host's permitted diary scope.
    path('tasks/new/', TaskCreateView.as_view(), name='task-create'),

    # DV1-023, DV1-032, DV1-036, DV1-037: A task page retains one selected permitted diary.
    path('tasks/<uuid:entry_key>/', TaskDetailView.as_view(), name='task-detail'),

    # DV1-021, DV1-049: The default Diary page shows the current user's owned tasks.
    path('', PersonalDiaryView.as_view(), name='personal-diary'),

    # DV1-022, DV1-052: A selected diary uses trusted scope and manager-only task filters.
    path('manager/', ManagerDiaryView.as_view(), name='manager-diary'),
    path('templates/apply/', TemplateApplyView.as_view(), name='template-apply'),
    path('templates/', TemplateEditorView.as_view(), name='template-list'),
    path('templates/new/', TemplateCreateView.as_view(), name='template-create'),
    path('templates/edit/<path:template_name>/', TemplateEditorView.as_view(), name='template-edit'),
]
