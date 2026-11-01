"""
A POST whose CSRF check fails gets tnnt.views.csrf_failure (2026-11-01)
instead of Django's bare 403: a redirect to /clanmgmt when the login form
is sent again after the login worked, a TNNT page otherwise.
"""
from django.contrib.auth.models import AnonymousUser
from django.middleware.csrf import (
    REASON_BAD_ORIGIN, REASON_NO_CSRF_COOKIE, _get_new_csrf_string
)
from django.test import Client, RequestFactory, TestCase

from scoreboard.models import Clan
from scoreboard.tests.test_views import login_player
from tnnt import views


class CsrfFailureTests(TestCase):

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def stale_token(self):
        """
        A well-formed cookie and a different well-formed form token, so
        the reason is "CSRF token from POST incorrect." (a malformed one
        would be "incorrect length" or "invalid characters").
        """
        self.client.cookies['csrftoken'] = _get_new_csrf_string()
        return {'csrfmiddlewaretoken': _get_new_csrf_string()}

    def post(self, path, data=None, level='WARNING'):
        # Django logs every CSRF failure itself (WARNING for a 403, INFO
        # for our redirect); capture it, which also checks it still does
        with self.assertLogs('django.security.csrf', level) as logs:
            resp = self.client.post(path, data or {})
        self.assertIn('Forbidden', logs.output[0])
        return resp

    def test_no_cookie_gets_the_cookie_advice(self):
        resp = self.post('/login/', {'username': 'bob', 'password': 'x'})
        self.assertTemplateUsed(resp, 'csrf_failure.html')
        self.assertContains(resp, 'allow cookies for tnnt.org',
                            status_code=403)
        self.assertContains(resp, 'href="/login/"', status_code=403)

    def test_stale_token_says_the_form_was_out_of_date(self):
        resp = self.post('/login/', dict(self.stale_token(),
                                         username='bob', password='x'))
        self.assertContains(resp, 'out of date', status_code=403)
        self.assertNotContains(resp, 'allow cookies', status_code=403)

    def test_login_form_sent_again_after_login_goes_to_clanmgmt(self):
        login_player(self.client, 'bob')
        with self.assertLogs(level='INFO') as logs:
            resp = self.post('/login/', dict(self.stale_token(),
                                             username='bob', password='x'),
                             level='INFO')
        self.assertRedirects(resp, '/clanmgmt',
                             fetch_redirect_response=False)
        self.assertIn('bob re-sent the login form after logging in',
                      '\n'.join(logs.output))

    def test_stale_clanmgmt_form_changes_nothing(self):
        login_player(self.client, 'bob')
        resp = self.post('/clanmgmt', dict(self.stale_token(),
                                           create_clan='',
                                           clan_name='Combo Crew'))
        self.assertContains(resp, 'Nothing was changed', status_code=403)
        self.assertContains(resp, 'href="/clanmgmt"', status_code=403)
        self.assertFalse(Clan.objects.exists())

    def test_any_other_path_links_home(self):
        resp = self.post('/')
        self.assertContains(resp, 'Return to Homepage', status_code=403)
        # the request path is never reflected into the page
        request = RequestFactory().post('/x')
        request.path = '//evil.example/x'
        request.user = AnonymousUser()
        resp = views.csrf_failure(request, reason=REASON_BAD_ORIGIN)
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn(b'evil.example', resp.content)
        self.assertIn(b'href="/"', resp.content)

    def test_cookie_reason_is_the_one_django_uses(self):
        # the page's cookie advice keys on this constant
        self.assertEqual(REASON_NO_CSRF_COOKIE, 'CSRF cookie not set.')
