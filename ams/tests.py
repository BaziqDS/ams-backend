# pyright: reportAttributeAccessIssue=false
import json

from django.contrib.auth.models import Group, Permission, User
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework.response import Response

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


class CapabilitiesEndpointReportsTests(TestCase):
    def _perm(self, dotted):
        app_label, codename = dotted.split('.', 1)
        return Permission.objects.get(content_type__app_label=app_label, codename=codename)

    def test_capabilities_reports_reports_view_level(self):
        user = User.objects.create_user(username='reports_caps', password='pw')
        role = Group.objects.create(name='Reports View Role')
        role.permissions.add(self._perm('inventory.view_reports'))
        user.groups.add(role)

        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get('/auth/capabilities/')

        self.assertEqual(resp.status_code, 200)
        body = resp.json() if hasattr(resp, 'json') else json.loads(resp.content.decode())
        self.assertEqual(body['modules']['reports'], 'view')
        self.assertEqual(body['manifest']['reports'], ['view'])
