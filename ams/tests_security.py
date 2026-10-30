from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken


@override_settings(CSRF_TRUSTED_ORIGINS=['http://localhost:3000'])
class CookieSecurityTests(TestCase):
    def tearDown(self):
        cache.clear()

    def setUp(self):
        self.user = User.objects.create_superuser(username='cookie-admin', password='secret')
        self.refresh = str(RefreshToken.for_user(self.user))
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.cookies['ams_access'] = str(RefreshToken(self.refresh).access_token)
        self.client.cookies['ams_refresh'] = self.refresh

    def csrf(self, client=None):
        client = client or self.client
        response = client.get('/auth/cookie/csrf/')
        self.assertEqual(response.status_code, 200)
        return {'HTTP_X_CSRFTOKEN': response.data['csrfToken'], 'HTTP_ORIGIN': 'http://localhost:3000'}

    def test_cookie_authenticated_write_rejects_missing_csrf_token(self):
        response = self.client.post('/api/users/groups/', {'name': 'Blocked'}, format='multipart')
        self.assertEqual(response.status_code, 403)

    def test_valid_csrf_allows_write_and_rejects_untrusted_origin(self):
        headers = self.csrf()
        response = self.client.post('/api/users/groups/', {'name': 'Allowed'}, **headers)
        self.assertEqual(response.status_code, 201)
        headers['HTTP_ORIGIN'] = 'http://evil.example.test'
        self.assertEqual(self.client.post('/api/users/groups/', {'name': 'Blocked'}, **headers).status_code, 403)

    def test_login_and_refresh_also_require_csrf(self):
        anonymous = APIClient(enforce_csrf_checks=True)
        self.assertEqual(anonymous.post('/auth/cookie/login/', {'username': 'cookie-admin', 'password': 'secret'}).status_code, 403)
        self.assertEqual(self.client.post('/auth/cookie/refresh/', {}).status_code, 403)
        response = anonymous.post('/auth/cookie/login/', {'username': 'cookie-admin', 'password': 'secret'}, **self.csrf(anonymous))
        self.assertEqual(response.status_code, 200)

    def test_logout_revokes_refresh_but_valid_refresh_rotates(self):
        headers = self.csrf()
        self.assertEqual(self.client.post('/auth/cookie/logout/', {}, **headers).status_code, 200)
        self.client.cookies['ams_refresh'] = self.refresh
        self.assertEqual(self.client.post('/auth/cookie/refresh/', {}, **headers).status_code, 401)
        self.client.cookies['ams_refresh'] = str(RefreshToken.for_user(self.user))
        self.assertEqual(self.client.post('/auth/cookie/refresh/', {}, **headers).status_code, 200)

    def test_bearer_client_does_not_need_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken(self.refresh).access_token}')
        self.assertEqual(client.post('/api/users/groups/', {'name': 'Bearer'}).status_code, 201)

    @override_settings(COOKIE_DOMAIN='.example.com')
    def test_login_rotates_csrf_and_logout_clears_the_configured_cookie_domain(self):
        client = APIClient(enforce_csrf_checks=True)
        headers = self.csrf(client)
        original = client.cookies['csrftoken'].value
        response = client.post('/auth/cookie/login/', {'username': self.user.username, 'password': 'secret'}, **headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(client.cookies['csrftoken'].value, original)
        self.assertEqual(response.cookies['ams_access']['domain'], '.example.com')
        self.assertEqual(response.cookies['ams_refresh']['domain'], '.example.com')
        response = client.post('/auth/cookie/logout/', {}, **self.csrf(client))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.cookies['ams_access']['domain'], '.example.com')
        self.assertEqual(response.cookies['ams_access']['max-age'], 0)
