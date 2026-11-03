"""Optional validation of Diary groups before a worker serves requests."""
from threading import Lock

from .roles import validate_access_groups, validate_task_owner_roles


class DiaryConfigurationMiddleware:
    """Validate once per middleware instance, retrying until validation succeeds.

    Django builds one middleware chain per worker. Database work happens only
    when handling requests, never when the chain is constructed. This synchronous
    middleware is also supported by Django's ASGI middleware adaptation.
    """

    sync_capable = True
    async_capable = False

    def __init__(self, get_response):
        self.get_response = get_response
        self._validated = False
        self._validation_lock = Lock()

    def __call__(self, request):
        if not self._validated:
            with self._validation_lock:
                if not self._validated:
                    validate_access_groups()
                    validate_task_owner_roles()
                    self._validated = True
        return self.get_response(request)
