"""Public response hooks and signed form targets for host-wrapped Diary views."""
from dataclasses import dataclass
from uuid import UUID

from django.contrib import messages
from django.core import signing
from django.shortcuts import redirect, resolve_url
from django.urls import reverse

__all__ = ['DiaryViewResult', 'DiarySuccessMixin']

@dataclass(frozen=True)
class DiaryViewResult:
    """Identify a successful write. Unaffected identifiers are None; keys are UUIDs."""

    operation: str
    diary_key: UUID | None = None
    entry_key: UUID | None = None
    template_name: str | None = None
    template_version_key: UUID | None = None


class DiarySuccessMixin:
    """Provide the same success contract to every Diary write view."""

    success_url = None

    def on_success(self, *, result):
        """Notify the host after the Diary save; override and optionally call super()."""
        if result.operation == 'task_created':
            messages.success(self.request, 'Task added.', extra_tags='diary-task-created', fail_silently=True)

    def get_success_url(self, *, result):
        """Use a host destination or query-free package route; never encode results in query parameters."""
        if self.success_url is not None:
            return resolve_url(self.success_url)
        if result.operation in {'template_created', 'template_saved'}:
            return reverse('Diary:template-edit', kwargs={'template_name': result.template_name})
        if result.operation == 'template_applied':
            return reverse('Diary:diary-manager', kwargs={'diary_key': result.diary_key})
        if result.operation == 'task_created':
            return reverse('Diary:diary-task-create', kwargs={'diary_key': result.diary_key})
        if result.operation in {'task_date_updated', 'task_owner_updated', 'task_completed', 'task_chain_completed'}:
            return reverse('Diary:diary-task-detail', kwargs={'diary_key': result.diary_key, 'entry_key': result.entry_key})
        raise ValueError(f'No default success URL for operation {result.operation!r}.')

    def success_response(self, *, result):
        """Notify exactly once, then redirect. Hosts may override this for a different response type."""
        self.on_success(result=result)
        return redirect(self.get_success_url(result=result))


TARGET_FIELD = 'diary_target'
TARGET_SALT = 'Diary.view-target.v1'


def submitted_target(request):
    """Read a user-bound form target. This identifies records; it grants no access."""
    if request.method != 'POST' or TARGET_FIELD not in request.POST:
        return {}
    if len(request.POST.getlist(TARGET_FIELD)) != 1:
        raise signing.BadSignature('Supply one form target.')
    target = signing.loads(request.POST[TARGET_FIELD], salt=TARGET_SALT)
    if not isinstance(target, dict) or set(target) - {'user', 'diary_key', 'entry_key', 'template_name'}:
        raise signing.BadSignature('Invalid form target.')
    if target.get('user') != str(request.user.pk):
        raise signing.BadSignature('The form belongs to another user.')
    for name in ('diary_key', 'entry_key'):
        if name in target:
            try:
                target[name] = UUID(target[name])
            except (ValueError, TypeError, AttributeError) as error:
                raise signing.BadSignature('Invalid form target.') from error
    if 'template_name' in target and (not isinstance(target['template_name'], str) or not target['template_name'].strip()):
        raise signing.BadSignature('Invalid form target.')
    return target


def form_target(request, *, diary_key=None, entry_key=None, template_name=None):
    """Sign identifiers from already authorised view data, without storing session selection."""
    target = {'user': str(request.user.pk)}
    for name, value in (('diary_key', diary_key), ('entry_key', entry_key), ('template_name', template_name)):
        if value is not None:
            target[name] = str(value)
    return signing.dumps(target, salt=TARGET_SALT)
