"""Named routes for Diary templates and the manager diary view."""
from django.urls import path

from .views import ManagerDiaryView, TemplateCreateView, TemplateEditorView

app_name = 'Diary'

# DV1-024: Template chooser and selected-template routes.
# Partial DV1-018: Template and manager-list routes exist. Other task routes remain outstanding.
urlpatterns = [

    # DV1-022, DV1-052: A selected diary uses trusted scope and manager-only task filters.
    path('manager/', ManagerDiaryView.as_view(), name='manager-diary'),
    path('templates/', TemplateEditorView.as_view(), name='template-list'),
    path('templates/new/', TemplateCreateView.as_view(), name='template-create'),
    path('templates/edit/<path:template_name>/', TemplateEditorView.as_view(), name='template-edit'),
]
