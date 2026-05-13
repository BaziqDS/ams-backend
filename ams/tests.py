# pyright: reportAttributeAccessIssue=false
import json

from django.conf import settings
from django.contrib.auth.models import Group, Permission, User
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from ams.auth_views import ACCESS_COOKIE, REFRESH_COOKIE, _set_token_cookies


class AuthCookieSettingsTests(SimpleTestCase):
    @override_settings(COOKIE_SECURE=False)
    def test_login_cookies_allow_http_when_cookie_secure_disabled(self):
        response = Response()

        _set_token_cookies(response, 'access-token', 'refresh-token')

        self.assertFalse(response.cookies[ACCESS_COOKIE]['secure'])
        self.assertFalse(response.cookies[REFRESH_COOKIE]['secure'])

    @override_settings(COOKIE_SECURE=True)
    def test_login_cookies_are_secure_when_cookie_secure_enabled(self):
        response = Response()

        _set_token_cookies(response, 'access-token', 'refresh-token')

        self.assertTrue(response.cookies[ACCESS_COOKIE]['secure'])
        self.assertTrue(response.cookies[REFRESH_COOKIE]['secure'])


class DiagnosticsSettingsTests(SimpleTestCase):
    def test_silk_requires_authentication_and_authorisation_when_enabled(self):
        if not settings.ENABLE_SILK:
            return

        self.assertTrue(settings.SILKY_AUTHENTICATION)
        self.assertTrue(settings.SILKY_AUTHORISATION)


class CookieRefreshRotationTests(TestCase):
    def test_refresh_cookie_rotates_and_old_refresh_is_rejected(self):
        user = User.objects.create_user(username='refresh_rotation_user', password='pw')
        raw_refresh = str(RefreshToken.for_user(user))
        client = APIClient()
        client.cookies[REFRESH_COOKIE] = raw_refresh

        resp = client.post('/auth/cookie/refresh/', {}, format='json')

        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', None))
        self.assertIn(REFRESH_COOKIE, resp.cookies)
        rotated_refresh = resp.cookies[REFRESH_COOKIE].value
        self.assertNotEqual(rotated_refresh, raw_refresh)

        replay_client = APIClient()
        replay_client.cookies[REFRESH_COOKIE] = raw_refresh
        replay_resp = replay_client.post('/auth/cookie/refresh/', {}, format='json')

        self.assertEqual(replay_resp.status_code, 401)


class DjoserUserCreatePermissionTests(TestCase):
    def test_authenticated_user_cannot_create_account_via_djoser(self):
        user = User.objects.create_user(username='ordinary_creator', password='pw')
        client = APIClient()
        client.force_authenticate(user=user)

        resp = client.post(
            '/auth/users/',
            {
                'username': 'created_via_djoser',
                'password': 'StrongPass123!',
                're_password': 'StrongPass123!',
                'email': 'created_via_djoser@example.com',
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 403)
        self.assertFalse(User.objects.filter(username='created_via_djoser').exists())


class CapabilitiesEndpointLocationsTests(TestCase):
    def _perm(self, dotted):
        app_label, codename = dotted.split('.', 1)
        return Permission.objects.get(content_type__app_label=app_label, codename=codename)

    def test_capabilities_reports_locations_manage_level(self):
        user = User.objects.create_user(username='cap_api_user', password='pw')
        role = Group.objects.create(name='Loc Manage Role')
        role.permissions.add(self._perm('inventory.view_locations'))
        role.permissions.add(self._perm('inventory.create_locations'))
        role.permissions.add(self._perm('inventory.edit_locations'))
        user.groups.add(role)

        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get('/auth/capabilities/')

        self.assertEqual(resp.status_code, 200)
        body = resp.json() if hasattr(resp, 'json') else json.loads(resp.content.decode())
        self.assertEqual(body['modules']['locations'], 'manage')
        self.assertIn('locations', body['manifest'])
        self.assertEqual(body['manifest']['locations'], ['view', 'manage', 'full'])

    def test_capabilities_exposes_module_read_dependencies(self):
        user = User.objects.create_user(username='cap_api_deps', password='pw')

        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get('/auth/capabilities/')

        self.assertEqual(resp.status_code, 200)
        body = resp.json() if hasattr(resp, 'json') else json.loads(resp.content.decode())
        self.assertEqual(
            body['dependencies']['users']['manage'],
            ['roles', 'locations'],
        )
        self.assertEqual(
            body['dependencies']['users']['full'],
            ['roles', 'locations'],
        )

    def test_capabilities_exposes_only_manifest_dependency_keys(self):
        user = User.objects.create_user(username='cap_api_stock_deps', password='pw')

        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get('/auth/capabilities/')

        self.assertEqual(resp.status_code, 200)
        body = resp.json() if hasattr(resp, 'json') else json.loads(resp.content.decode())
        self.assertEqual(
            body['dependencies']['stock-entries']['manage'],
            ['items', 'locations', 'stock-registers'],
        )
        self.assertNotIn('persons', body['dependencies']['stock-entries']['manage'])


class CapabilitiesEndpointCategoriesTests(TestCase):
    def _perm(self, dotted):
        app_label, codename = dotted.split('.', 1)
        return Permission.objects.get(content_type__app_label=app_label, codename=codename)

    def test_capabilities_reports_categories_manage_level(self):
        user = User.objects.create_user(username='cat_caps', password='pw')
        role = Group.objects.create(name='Category Manage Role')
        role.permissions.add(self._perm('inventory.view_categories'))
        role.permissions.add(self._perm('inventory.create_categories'))
        role.permissions.add(self._perm('inventory.edit_categories'))
        user.groups.add(role)

        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get('/auth/capabilities/')

        self.assertEqual(resp.status_code, 200)
        body = resp.json() if hasattr(resp, 'json') else json.loads(resp.content.decode())
        self.assertEqual(body['modules']['categories'], 'manage')
        self.assertEqual(body['manifest']['categories'], ['view', 'manage', 'full'])


class CapabilitiesEndpointStockRegistersTests(TestCase):
    def _perm(self, dotted):
        app_label, codename = dotted.split('.', 1)
        return Permission.objects.get(content_type__app_label=app_label, codename=codename)

    def test_capabilities_reports_stock_registers_manage_level(self):
        user = User.objects.create_user(username='stock_register_caps', password='pw')
        role = Group.objects.create(name='Stock Register Manage Role')
        role.permissions.add(self._perm('inventory.view_stock_registers'))
        role.permissions.add(self._perm('inventory.create_stock_registers'))
        role.permissions.add(self._perm('inventory.edit_stock_registers'))
        user.groups.add(role)

        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get('/auth/capabilities/')

        self.assertEqual(resp.status_code, 200)
        body = resp.json() if hasattr(resp, 'json') else json.loads(resp.content.decode())
        self.assertEqual(body['modules']['stock-registers'], 'manage')
        self.assertIn('stock-registers', body['manifest'])
        self.assertEqual(body['manifest']['stock-registers'], ['view', 'manage', 'full'])

    def test_capabilities_exposes_stock_register_location_dependency(self):
        user = User.objects.create_user(username='stock_register_dep_caps', password='pw')

        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get('/auth/capabilities/')

        self.assertEqual(resp.status_code, 200)
        body = resp.json() if hasattr(resp, 'json') else json.loads(resp.content.decode())
        self.assertEqual(body['dependencies']['stock-registers']['manage'], ['locations'])
        self.assertEqual(body['dependencies']['stock-registers']['full'], ['locations'])
