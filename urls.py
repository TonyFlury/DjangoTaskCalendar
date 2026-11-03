"""Named routes for the generic Diary template workflow."""
from django.urls import path

from .views import TemplateCreateView, TemplateEditorView

app_name = 'Diary'

# DV1-024: Template chooser and selected-template routes.
# Partial DV1-018: Template routes are implemented. Task routes remain outstanding.
urlpatterns = [
    path('templates/', TemplateEditorView.as_view(), name='template-list'),
    path('templates/new/', TemplateCreateView.as_view(), name='template-create'),
    path('templates/edit/<path:template_name>/', TemplateEditorView.as_view(), name='template-edit'),
]
