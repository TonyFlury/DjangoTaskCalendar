"""Signed, user-bound return links from task actions to a calendar page."""
from urllib.parse import urlencode

from django.core import signing
from django.utils.http import url_has_allowed_host_and_scheme

SALT = 'Diary.calendar-return.v1'


def calendar_return_token(request, query):
    """Sign only a server-validated calendar state, without granting diary access."""
    return signing.dumps({'user': str(request.user.pk), 'url': request.path + '?' + urlencode(query)}, salt=SALT, compress=True)


def calendar_return_state(request):
    """Ignore expired, forged, cross-user, duplicate, or external return destinations."""
    values = request.POST if request.method == 'POST' else request.GET
    tokens = values.getlist('calendar_return')
    if len(tokens) != 1:
        return '', ''
    token = tokens[0]
    try:
        data = signing.loads(token, salt=SALT, max_age=7 * 24 * 60 * 60)
        url = data['url']
        if data['user'] != str(request.user.pk) or not isinstance(url, str) or not url.startswith('/') or url.startswith('//'):
            return '', ''
        if not url_has_allowed_host_and_scheme(url, allowed_hosts=set()):
            return '', ''
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        return '', ''
    return token, url
