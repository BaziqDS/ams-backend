from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase
from rest_framework.test import APIClient

from ams.permissions_manifest import MODULES, READ_PERMS
from inventory.models import Location, LocationType
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


class CapabilityManifestItemsTests(TestCase):
    def _perm(self, dotted):
        app_label, codename = dotted.split('.', 1)
        return Permission.objects.get(content_type__app_label=app_label, codename=codename)

    def test_resolve_items_manage_includes_domain_perms_and_category_read(self):
        resolved = resolve_selections_to_codenames({'items': 'manage'})
        self.assertIn('inventory.view_items', resolved)
        self.assertIn('inventory.create_items', resolved)
        self.assertIn('inventory.edit_items', resolved)
        self.assertIn('inventory.view_categories', resolved)
        self.assertNotIn('inventory.delete_items', resolved)

    def test_items_module_declared_with_view_manage_full(self):
        self.assertIn('items', MODULES)
        self.assertIn('view', MODULES['items'])
        self.assertIn('manage', MODULES['items'])
        self.assertIn('full', MODULES['items'])

    def test_items_read_perm_declared(self):
        self.assertEqual(
            READ_PERMS.get('items'),
            ['inventory.view_items'],
        )

    def test_compute_capabilities_reports_items_level(self):
        user = User.objects.create_user(username='cap_items', password='x')
        group = Group.objects.create(name='Items Full')
        for dotted in MODULES['items']['full']['perms']:
            group.permissions.add(self._perm(dotted))
        user.groups.add(group)

        caps = compute_capabilities_for_user(user)
        self.assertEqual(caps['items'], 'full')

    def test_dependency_only_read_modules_resolve_to_read_perms(self):
        resolved = resolve_selections_to_codenames({
            'persons': 'view',
            'stock-registers': 'view',
        })

        self.assertIn('inventory.view_person', resolved)
        self.assertIn('inventory.view_stock_registers', resolved)
        self.assertNotIn('inventory.view_stockregister', resolved)


class CapabilityManifestStockRegistersTests(TestCase):
    def _perm(self, dotted):
        app_label, codename = dotted.split('.', 1)
        return Permission.objects.get(content_type__app_label=app_label, codename=codename)

    def test_resolve_stock_registers_manage_includes_domain_perms_and_locations_read(self):
        resolved = resolve_selections_to_codenames({'stock-registers': 'manage'})

        self.assertIn('inventory.view_stock_registers', resolved)
        self.assertIn('inventory.create_stock_registers', resolved)
        self.assertIn('inventory.edit_stock_registers', resolved)
        self.assertIn('inventory.view_locations', resolved)
        self.assertIn('inventory.view_location', resolved)
        self.assertNotIn('inventory.delete_stock_registers', resolved)

    def test_stock_registers_module_declared_with_view_manage_full(self):
        self.assertIn('stock-registers', MODULES)
        self.assertIn('view', MODULES['stock-registers'])
        self.assertIn('manage', MODULES['stock-registers'])
        self.assertIn('full', MODULES['stock-registers'])

    def test_stock_registers_read_perms_declared(self):
        self.assertEqual(
            READ_PERMS.get('stock-registers'),
            ['inventory.view_stock_registers', 'inventory.view_stockregister'],
        )

    def test_compute_capabilities_reports_stock_registers_level(self):
        user = User.objects.create_user(username='cap_stock_registers', password='x')
        group = Group.objects.create(name='Stock Registers Manage')
        for dotted in MODULES['stock-registers']['manage']['perms']:
            group.permissions.add(self._perm(dotted))
        user.groups.add(group)

        caps = compute_capabilities_for_user(user)
        self.assertEqual(caps['stock-registers'], 'manage')


class CapabilityManifestStockRegistersImplicationTests(TestCase):
    def _perm(self, dotted):
        app_label, codename = dotted.split('.', 1)
        return Permission.objects.get(content_type__app_label=app_label, codename=codename)

    def test_create_stock_registers_implies_view_stock_registers(self):
        group = Group.objects.create(name='Stock Register Managers Create')
        create_perm = self._perm('inventory.create_stock_registers')
        view_perm = self._perm('inventory.view_stock_registers')

        group.permissions.add(create_perm)

        self.assertTrue(group.permissions.filter(pk=view_perm.pk).exists())

    def test_edit_stock_registers_implies_view_stock_registers(self):
        group = Group.objects.create(name='Stock Register Managers Edit')
        edit_perm = self._perm('inventory.edit_stock_registers')
        view_perm = self._perm('inventory.view_stock_registers')

        group.permissions.add(edit_perm)

        self.assertTrue(group.permissions.filter(pk=view_perm.pk).exists())

    def test_delete_stock_registers_implies_view_stock_registers(self):
        group = Group.objects.create(name='Stock Register Managers Delete')
        delete_perm = self._perm('inventory.delete_stock_registers')
        view_perm = self._perm('inventory.view_stock_registers')

        group.permissions.add(delete_perm)

        self.assertTrue(group.permissions.filter(pk=view_perm.pk).exists())


class CapabilityManifestItemsImplicationTests(TestCase):
    def _perm(self, dotted):
        app_label, codename = dotted.split('.', 1)
        return Permission.objects.get(content_type__app_label=app_label, codename=codename)

    def test_create_items_implies_view_items(self):
        group = Group.objects.create(name='Items Managers Create')
        create_perm = self._perm('inventory.create_items')
        view_perm = self._perm('inventory.view_items')

        group.permissions.add(create_perm)

        self.assertTrue(group.permissions.filter(pk=view_perm.pk).exists())

    def test_edit_items_implies_view_items(self):
        group = Group.objects.create(name='Items Managers Edit')
        edit_perm = self._perm('inventory.edit_items')
        view_perm = self._perm('inventory.view_items')

        group.permissions.add(edit_perm)

        self.assertTrue(group.permissions.filter(pk=view_perm.pk).exists())

    def test_delete_items_implies_view_items(self):
        group = Group.objects.create(name='Items Managers Delete')
        delete_perm = self._perm('inventory.delete_items')
        view_perm = self._perm('inventory.view_items')

        group.permissions.add(delete_perm)

        self.assertTrue(group.permissions.filter(pk=view_perm.pk).exists())


class UserManagementLocationAssignmentScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = Location.objects.create(
            name='University Root',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        cls.csit = Location.objects.create(
            name='CSIT',
            location_type=LocationType.DEPARTMENT,
            parent_location=cls.root,
            is_standalone=True,
        )
        cls.csit_lab = Location.objects.create(
            name='CSIT Lab',
            location_type=LocationType.LAB,
            parent_location=cls.csit,
            is_standalone=False,
        )
        cls.mechanical = Location.objects.create(
            name='Mechanical',
            location_type=LocationType.DEPARTMENT,
            parent_location=cls.root,
            is_standalone=True,
        )

    def setUp(self):
        self.client = APIClient()

    def _perm(self, codename):
        return Permission.objects.get(
            content_type__app_label='user_management',
            codename=codename,
        )

    def _make_user_manager(self, username, assigned_location):
        user = User.objects.create_user(username=username, password='pw')
        user.user_permissions.add(self._perm('create_user_accounts'))
        user.profile.assigned_locations.add(assigned_location)
        return user

    def _make_managed_user(self, username, assigned_location):
        user = User.objects.create_user(
            username=username,
            password='pw',
            email=f'{username}@example.com',
        )
        user.profile.assigned_locations.add(assigned_location)
        return user

    def _rows(self, resp):
        if isinstance(resp.data, dict) and 'results' in resp.data:
            return resp.data['results']
        return resp.data

    def test_scoped_user_manager_can_assign_descendant_location(self):
        manager = self._make_user_manager('csit_manager', self.csit)
        manager.user_permissions.add(self._perm('assign_user_locations'))
        self.client.force_authenticate(user=manager)

        resp = self.client.post(
            '/api/users/management/',
            {
                'username': 'csit_child_user',
                'password': 'pw',
                'email': 'csit_child@example.com',
                'first_name': 'CSIT',
                'last_name': 'Child',
                'assigned_locations': [self.csit_lab.id],
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 201)
        created = User.objects.get(username='csit_child_user')
        self.assertTrue(
            created.profile.assigned_locations.filter(pk=self.csit_lab.pk).exists()
        )

    def test_scoped_user_manager_cannot_assign_sibling_department(self):
        manager = self._make_user_manager('csit_manager_blocked', self.csit)
        manager.user_permissions.add(self._perm('assign_user_locations'))
        self.client.force_authenticate(user=manager)

        resp = self.client.post(
            '/api/users/management/',
            {
                'username': 'mechanical_user',
                'password': 'pw',
                'email': 'mechanical@example.com',
                'first_name': 'Mechanical',
                'last_name': 'User',
                'assigned_locations': [self.mechanical.id],
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn('assigned_locations', resp.data)
        self.assertFalse(User.objects.filter(username='mechanical_user').exists())

    def test_view_all_user_accounts_does_not_bypass_location_assignment_scope(self):
        manager = self._make_user_manager('csit_view_all_manager', self.csit)
        manager.user_permissions.add(self._perm('view_all_user_accounts'))
        manager.user_permissions.add(self._perm('assign_user_locations'))
        self.client.force_authenticate(user=manager)

        resp = self.client.post(
            '/api/users/management/',
            {
                'username': 'mechanical_view_all_user',
                'password': 'pw',
                'email': 'mechanical_view_all@example.com',
                'first_name': 'Mechanical',
                'last_name': 'ViewAll',
                'assigned_locations': [self.mechanical.id],
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn('assigned_locations', resp.data)
        self.assertFalse(User.objects.filter(username='mechanical_view_all_user').exists())

    def test_system_admin_role_does_not_bypass_location_assignment_scope(self):
        manager = self._make_user_manager('csit_system_admin_manager', self.csit)
        group = Group.objects.create(name='System Admin')
        manager.groups.add(group)
        manager.user_permissions.add(self._perm('assign_user_locations'))
        self.client.force_authenticate(user=manager)

        resp = self.client.post(
            '/api/users/management/',
            {
                'username': 'mechanical_system_admin_user',
                'password': 'pw',
                'email': 'mechanical_system_admin@example.com',
                'first_name': 'Mechanical',
                'last_name': 'SystemAdmin',
                'assigned_locations': [self.mechanical.id],
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn('assigned_locations', resp.data)
        self.assertFalse(User.objects.filter(username='mechanical_system_admin_user').exists())

    def test_view_all_user_accounts_list_is_location_scoped_for_non_root_user(self):
        manager = self._make_user_manager('csit_view_all_lister', self.csit)
        manager.user_permissions.add(self._perm('view_all_user_accounts'))
        csit_user = self._make_managed_user('csit_listed_user', self.csit_lab)
        mechanical_user = self._make_managed_user('mechanical_hidden_user', self.mechanical)
        self.client.force_authenticate(user=manager)

        resp = self.client.get('/api/users/management/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(manager.id, returned_ids)
        self.assertIn(csit_user.id, returned_ids)
        self.assertNotIn(mechanical_user.id, returned_ids)

    def test_group_based_view_all_user_accounts_list_is_location_scoped_for_non_root_user(self):
        manager = self._make_user_manager('csit_group_view_all_lister', self.csit)
        group = Group.objects.create(name='CSIT User Viewers')
        group.permissions.add(self._perm('view_all_user_accounts'))
        manager.groups.add(group)
        csit_user = self._make_managed_user('csit_group_listed_user', self.csit_lab)
        mechanical_user = self._make_managed_user('mechanical_group_hidden_user', self.mechanical)
        self.client.force_authenticate(user=manager)

        resp = self.client.get('/api/users/management/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(manager.id, returned_ids)
        self.assertIn(csit_user.id, returned_ids)
        self.assertNotIn(mechanical_user.id, returned_ids)

    def test_view_all_user_accounts_detail_rejects_out_of_scope_user_for_non_root_user(self):
        manager = self._make_user_manager('csit_view_all_detail', self.csit)
        manager.user_permissions.add(self._perm('view_all_user_accounts'))
        mechanical_user = self._make_managed_user('mechanical_detail_hidden', self.mechanical)
        self.client.force_authenticate(user=manager)

        resp = self.client.get(f'/api/users/management/{mechanical_user.id}/')

        self.assertEqual(resp.status_code, 404)

    def test_profile_list_is_location_scoped_for_non_root_user(self):
        manager = self._make_user_manager('csit_profile_lister', self.csit)
        manager.user_permissions.add(self._perm('view_all_user_accounts'))
        csit_user = self._make_managed_user('csit_profile_user', self.csit_lab)
        mechanical_user = self._make_managed_user('mechanical_profile_hidden', self.mechanical)
        self.client.force_authenticate(user=manager)

        resp = self.client.get('/api/users/profiles/')

        self.assertEqual(resp.status_code, 200)
        returned_user_ids = {row['user']['id'] for row in self._rows(resp)}
        self.assertIn(manager.id, returned_user_ids)
        self.assertIn(csit_user.id, returned_user_ids)
        self.assertNotIn(mechanical_user.id, returned_user_ids)

    def test_root_assigned_user_with_view_all_user_accounts_can_list_all_users(self):
        manager = self._make_user_manager('root_view_all_lister', self.root)
        manager.user_permissions.add(self._perm('view_all_user_accounts'))
        csit_user = self._make_managed_user('root_scope_csit_user', self.csit_lab)
        mechanical_user = self._make_managed_user('root_scope_mechanical_user', self.mechanical)
        unassigned_user = User.objects.create_user(
            username='root_scope_unassigned_user',
            password='pw',
            email='root_scope_unassigned@example.com',
        )
        self.client.force_authenticate(user=manager)

        resp = self.client.get('/api/users/management/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(csit_user.id, returned_ids)
        self.assertIn(mechanical_user.id, returned_ids)
        self.assertIn(unassigned_user.id, returned_ids)

    def test_root_assigned_user_manager_can_assign_any_location(self):
        manager = self._make_user_manager('root_manager', self.root)
        manager.user_permissions.add(self._perm('assign_user_locations'))
        self.client.force_authenticate(user=manager)

        resp = self.client.post(
            '/api/users/management/',
            {
                'username': 'mechanical_from_root',
                'password': 'pw',
                'email': 'root_mechanical@example.com',
                'first_name': 'Root',
                'last_name': 'Managed',
                'assigned_locations': [self.mechanical.id],
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 201)
        created = User.objects.get(username='mechanical_from_root')
        self.assertTrue(
            created.profile.assigned_locations.filter(pk=self.mechanical.pk).exists()
        )

    def test_scoped_user_manager_cannot_create_user_without_location(self):
        manager = self._make_user_manager('csit_empty_location_creator', self.csit)
        manager.user_permissions.add(self._perm('assign_user_locations'))
        self.client.force_authenticate(user=manager)

        resp = self.client.post(
            '/api/users/management/',
            {
                'username': 'no_location_user',
                'password': 'pw',
                'email': 'no_location@example.com',
                'first_name': 'No',
                'last_name': 'Location',
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn('assigned_locations', resp.data)
        self.assertFalse(User.objects.filter(username='no_location_user').exists())

    def test_root_assigned_user_manager_can_create_user_without_location(self):
        manager = self._make_user_manager('root_empty_location_creator', self.root)
        self.client.force_authenticate(user=manager)

        resp = self.client.post(
            '/api/users/management/',
            {
                'username': 'root_no_location_user',
                'password': 'pw',
                'email': 'root_no_location@example.com',
                'first_name': 'Root',
                'last_name': 'NoLocation',
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 201)
        created = User.objects.get(username='root_no_location_user')
        self.assertFalse(created.profile.assigned_locations.exists())

    def test_create_user_without_assign_roles_cannot_set_groups(self):
        manager = self._make_user_manager('csit_no_role_assign', self.csit)
        manager.user_permissions.add(self._perm('assign_user_locations'))
        group = Group.objects.create(name='Unauthorized Role')
        self.client.force_authenticate(user=manager)

        resp = self.client.post(
            '/api/users/management/',
            {
                'username': 'unauthorized_role_user',
                'password': 'pw',
                'email': 'unauthorized_role@example.com',
                'first_name': 'Unauthorized',
                'last_name': 'Role',
                'assigned_locations': [self.csit_lab.id],
                'groups': [group.id],
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn('groups', resp.data)
        self.assertFalse(User.objects.filter(username='unauthorized_role_user').exists())

    def test_create_user_without_assign_locations_cannot_set_locations(self):
        manager = self._make_user_manager('csit_no_location_assign', self.csit)
        manager.user_permissions.add(self._perm('assign_user_roles'))
        group = Group.objects.create(name='Allowed Role')
        self.client.force_authenticate(user=manager)

        resp = self.client.post(
            '/api/users/management/',
            {
                'username': 'unauthorized_location_user',
                'password': 'pw',
                'email': 'unauthorized_location@example.com',
                'first_name': 'Unauthorized',
                'last_name': 'Location',
                'assigned_locations': [self.csit_lab.id],
                'groups': [group.id],
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn('assigned_locations', resp.data)
        self.assertFalse(User.objects.filter(username='unauthorized_location_user').exists())

    def test_non_superuser_cannot_change_own_location_assignments(self):
        manager = self._make_user_manager('csit_self_location_locked', self.csit)
        manager.user_permissions.add(self._perm('edit_user_accounts'))
        self.client.force_authenticate(user=manager)

        resp = self.client.patch(
            f'/api/users/management/{manager.id}/',
            {
                'assigned_locations': [self.csit.id, self.csit_lab.id],
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn('assigned_locations', resp.data)
        self.assertEqual(
            set(manager.profile.assigned_locations.values_list('id', flat=True)),
            {self.csit.id},
        )

    def test_non_superuser_cannot_change_own_roles(self):
        manager = self._make_user_manager('csit_self_role_locked', self.csit)
        manager.user_permissions.add(self._perm('edit_user_accounts'))
        assigned_group = Group.objects.create(name='Assigned Role')
        replacement_group = Group.objects.create(name='Replacement Role')
        manager.groups.add(assigned_group)
        self.client.force_authenticate(user=manager)

        resp = self.client.patch(
            f'/api/users/management/{manager.id}/',
            {
                'groups': [replacement_group.id],
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn('groups', resp.data)
        self.assertEqual(set(manager.groups.values_list('id', flat=True)), {assigned_group.id})
