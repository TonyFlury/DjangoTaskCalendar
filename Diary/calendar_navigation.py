"""Signed, user-bound return links from task actions to a calendar page."""
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

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


def carry_calendar_return(request, response):
    """Carry package navigation through successful host POST selection and write redirects.
    Host selection remains authoritative; the token only restores a presentation.
    """
    if request.method != 'POST' or response.status_code not in {302, 303}:
        return response
    token, _ = calendar_return_state(request)
    target = response.get('Location', '')
    if not token or not target.startswith('/') or target.startswith('//'):
        return response
    if not url_has_allowed_host_and_scheme(target, allowed_hosts=set()):
        return response
    parts = urlsplit(target)
    query = [(name, value) for name, value in parse_qsl(parts.query, keep_blank_values=True)
             if name != 'calendar_return']
    query.append(('calendar_return', token))
    response['Location'] = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    return response
