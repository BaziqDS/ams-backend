from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase

from ams.permissions_manifest import MODULES, READ_PERMS
from user_management.services.capability_service import (
    compute_capabilities_for_user,
    resolve_selections_to_codenames,
)
from user_management.signals import EXPLICIT_PERMISSION_IMPLICATIONS


class CapabilityManifestLocationsTests(TestCase):
    def _perm(self, dotted):
        app_label, codename = dotted.split('.', 1)
        return Permission.objects.get(content_type__app_label=app_label, codename=codename)

    def test_resolve_locations_manage_includes_domain_perms(self):
        resolved = resolve_selections_to_codenames({'locations': 'manage'})
        self.assertIn('inventory.view_locations', resolved)
        self.assertIn('inventory.create_locations', resolved)
        self.assertIn('inventory.edit_locations', resolved)
        self.assertNotIn('inventory.delete_locations', resolved)

    def test_users_manage_read_dependency_grants_domain_locations_view(self):
        resolved = resolve_selections_to_codenames({
            'users': 'manage',
            'roles': None,
            'locations': None,
        })

        self.assertIn('user_management.view_roles', resolved)
        self.assertIn('inventory.view_locations', resolved)

    def test_users_manage_back_computes_roles_and_locations_view(self):
        resolved = resolve_selections_to_codenames({
            'users': 'manage',
            'roles': None,
            'locations': None,
        })
        selections = {}
        for module, levels in MODULES.items():
            current = None
            for level_name in ('view', 'manage', 'full'):
                if level_name in levels and set(levels[level_name]['perms']).issubset(resolved):
                    current = level_name
            selections[module] = current

        self.assertEqual(selections['users'], 'manage')
        self.assertEqual(selections['roles'], 'view')
        self.assertEqual(selections['locations'], 'view')

    def test_locations_module_declared_with_view_manage_full(self):
        self.assertIn('locations', MODULES)
        self.assertIn('view', MODULES['locations'])
        self.assertIn('manage', MODULES['locations'])
        self.assertIn('full', MODULES['locations'])

    def test_location_permission_implications_declared(self):
        self.assertEqual(
            EXPLICIT_PERMISSION_IMPLICATIONS.get('create_locations'),
            ['view_locations'],
        )
        self.assertEqual(
            EXPLICIT_PERMISSION_IMPLICATIONS.get('edit_locations'),
            ['view_locations'],
        )
        self.assertEqual(
            EXPLICIT_PERMISSION_IMPLICATIONS.get('delete_locations'),
            ['view_locations'],
        )

    def test_group_signal_adds_implied_view_locations(self):
        group = Group.objects.create(name='Loc Managers')
        create_perm = self._perm('inventory.create_locations')
        view_perm = self._perm('inventory.view_locations')

        group.permissions.add(create_perm)

        self.assertTrue(group.permissions.filter(pk=view_perm.pk).exists())

    def test_compute_capabilities_reports_locations_level(self):
        user = User.objects.create_user(username='cap_locs', password='x')
        group = Group.objects.create(name='Location Full')
        for dotted in MODULES['locations']['full']['perms']:
            group.permissions.add(self._perm(dotted))
        user.groups.add(group)

        caps = compute_capabilities_for_user(user)
        self.assertEqual(caps['locations'], 'full')


class CapabilityManifestCategoriesTests(TestCase):
    def _perm(self, dotted):
        app_label, codename = dotted.split('.', 1)
        return Permission.objects.get(content_type__app_label=app_label, codename=codename)

    def test_resolve_categories_manage_includes_domain_perms(self):
        resolved = resolve_selections_to_codenames({'categories': 'manage'})
        self.assertIn('inventory.view_categories', resolved)
        self.assertIn('inventory.create_categories', resolved)
        self.assertIn('inventory.edit_categories', resolved)
        self.assertNotIn('inventory.delete_categories', resolved)

    def test_categories_module_declared_with_view_manage_full(self):
        self.assertIn('categories', MODULES)
        self.assertIn('view', MODULES['categories'])
        self.assertIn('manage', MODULES['categories'])
        self.assertIn('full', MODULES['categories'])

    def test_categories_read_perm_declared(self):
        self.assertEqual(
            READ_PERMS.get('categories'),
            ['inventory.view_categories'],
        )

    def test_compute_capabilities_reports_categories_level(self):
        user = User.objects.create_user(username='cap_categories', password='x')
        group = Group.objects.create(name='Category Full')
        for dotted in MODULES['categories']['full']['perms']:
            group.permissions.add(self._perm(dotted))
        user.groups.add(group)

        caps = compute_capabilities_for_user(user)
        self.assertEqual(caps['categories'], 'full')


class CapabilityManifestCategoriesImplicationTests(TestCase):
    def _perm(self, dotted):
        app_label, codename = dotted.split('.', 1)
        return Permission.objects.get(content_type__app_label=app_label, codename=codename)

    def test_create_categories_implies_view_categories(self):
        group = Group.objects.create(name='Category Managers Create')
        create_perm = self._perm('inventory.create_categories')
        view_perm = self._perm('inventory.view_categories')

        group.permissions.add(create_perm)

        self.assertTrue(group.permissions.filter(pk=view_perm.pk).exists())

    def test_edit_categories_implies_view_categories(self):
        group = Group.objects.create(name='Category Managers Edit')
        edit_perm = self._perm('inventory.edit_categories')
        view_perm = self._perm('inventory.view_categories')

        group.permissions.add(edit_perm)

        self.assertTrue(group.permissions.filter(pk=view_perm.pk).exists())

    def test_delete_categories_implies_view_categories(self):
        group = Group.objects.create(name='Category Managers Delete')
        delete_perm = self._perm('inventory.delete_categories')
        view_perm = self._perm('inventory.view_categories')

        group.permissions.add(delete_perm)

        self.assertTrue(group.permissions.filter(pk=view_perm.pk).exists())
