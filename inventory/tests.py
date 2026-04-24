# pyright: reportAttributeAccessIssue=false
from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase
from rest_framework.test import APIClient

from inventory.models import (
    Category,
    CategoryType,
    Item,
    ItemBatch,
    ItemInstance,
    Location,
    LocationType,
    StockRecord,
    TrackingType,
)


class CategoryDomainPermissionBootstrapTests(TestCase):
    def test_category_domain_permissions_exist(self):
        perms = set(
            Permission.objects.filter(content_type__app_label='inventory').values_list('codename', flat=True)
        )

        self.assertTrue(
            {
                'view_categories',
                'create_categories',
                'edit_categories',
                'delete_categories',
            }.issubset(perms)
        )


class ItemDomainPermissionBootstrapTests(TestCase):
    def test_item_domain_permissions_exist(self):
        perms = set(
            Permission.objects.filter(content_type__app_label='inventory').values_list('codename', flat=True)
        )

        self.assertTrue(
            {
                'view_items',
                'create_items',
                'edit_items',
                'delete_items',
            }.issubset(perms)
        )


class LocationApiPermissionAndScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = Location.objects.create(
            name='University Root',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        cls.dept_a = Location.objects.create(
            name='Dept A',
            location_type=LocationType.DEPARTMENT,
            parent_location=cls.root,
            is_standalone=True,
        )
        cls.dept_a_room = Location.objects.create(
            name='Dept A Room',
            location_type=LocationType.ROOM,
            parent_location=cls.dept_a,
            is_standalone=False,
        )
        cls.dept_a_lab = Location.objects.create(
            name='Dept A Lab',
            location_type=LocationType.LAB,
            parent_location=cls.dept_a_room,
            is_standalone=False,
        )
        cls.dept_b = Location.objects.create(
            name='Dept B',
            location_type=LocationType.DEPARTMENT,
            parent_location=cls.root,
            is_standalone=True,
        )

    def setUp(self):
        self.client = APIClient()

    def _perm(self, codename):
        return Permission.objects.get(content_type__app_label='inventory', codename=codename)

    def _user_mgmt_perm(self, codename):
        return Permission.objects.get(content_type__app_label='user_management', codename=codename)

    def _make_user(self, username):
        return User.objects.create_user(username=username, password='pw')

    def _rows(self, response):
        data = response.data
        if isinstance(data, dict) and 'results' in data:
            return data['results']
        return data

    def test_list_requires_domain_view_locations_perm(self):
        user = self._make_user('no_domain_view')
        user.user_permissions.add(self._perm('view_location'))
        user.profile.assigned_locations.add(self.root)

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/locations/')

        self.assertEqual(resp.status_code, 403)

    def test_scoped_list_keeps_get_accessible_locations_semantics(self):
        user = self._make_user('scoped_viewer')
        user.user_permissions.add(self._perm('view_locations'))
        user.user_permissions.add(self._perm('view_location'))
        user.profile.assigned_locations.add(self.dept_a)

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/locations/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(self.dept_a.id, returned_ids)
        self.assertIn(self.dept_a_room.id, returned_ids)
        self.assertNotIn(self.dept_b.id, returned_ids)

    def test_create_requires_domain_create_locations_perm(self):
        user = self._make_user('loc_view_only')
        user.user_permissions.add(self._perm('view_locations'))
        user.user_permissions.add(self._perm('view_location'))
        user.profile.assigned_locations.add(self.root)

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            '/api/inventory/locations/',
            {
                'name': 'Dept C',
                'location_type': LocationType.DEPARTMENT,
                'parent_location': self.root.id,
                'is_standalone': True,
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 403)

    def test_assignable_returns_assigned_location_descendants_only_for_scoped_user(self):
        user = self._make_user('assignable_scoped')
        user.user_permissions.add(self._perm('view_locations'))
        user.user_permissions.add(self._perm('view_location'))
        user.profile.assigned_locations.add(self.dept_a)

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/locations/assignable/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(self.dept_a.id, returned_ids)
        self.assertIn(self.dept_a_room.id, returned_ids)
        self.assertIn(self.dept_a_lab.id, returned_ids)
        self.assertNotIn(self.dept_b.id, returned_ids)

    def test_assignable_ignores_view_all_user_accounts_for_non_root_assigned_user(self):
        user = self._make_user('assignable_view_all_scoped')
        user.user_permissions.add(self._perm('view_locations'))
        user.user_permissions.add(self._perm('view_location'))
        user.user_permissions.add(self._user_mgmt_perm('view_all_user_accounts'))
        user.profile.assigned_locations.add(self.dept_a)

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/locations/assignable/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(self.dept_a.id, returned_ids)
        self.assertIn(self.dept_a_room.id, returned_ids)
        self.assertIn(self.dept_a_lab.id, returned_ids)
        self.assertNotIn(self.dept_b.id, returned_ids)

    def test_assignable_ignores_system_admin_role_for_non_root_assigned_user(self):
        user = self._make_user('assignable_system_admin_scoped')
        group = Group.objects.create(name='System Admin')
        user.groups.add(group)
        user.user_permissions.add(self._perm('view_locations'))
        user.user_permissions.add(self._perm('view_location'))
        user.profile.assigned_locations.add(self.dept_a)

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/locations/assignable/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(self.dept_a.id, returned_ids)
        self.assertIn(self.dept_a_room.id, returned_ids)
        self.assertIn(self.dept_a_lab.id, returned_ids)
        self.assertNotIn(self.dept_b.id, returned_ids)

    def test_assignable_root_assigned_user_can_assign_all_active_locations(self):
        user = self._make_user('assignable_root')
        user.user_permissions.add(self._perm('view_locations'))
        user.user_permissions.add(self._perm('view_location'))
        user.profile.assigned_locations.add(self.root)

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/locations/assignable/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(self.root.id, returned_ids)
        self.assertIn(self.dept_a.id, returned_ids)
        self.assertIn(self.dept_a_room.id, returned_ids)
        self.assertIn(self.dept_a_lab.id, returned_ids)
        self.assertIn(self.dept_b.id, returned_ids)

    def test_serializer_enforces_model_clean_invariant_for_root_creation(self):
        user = self._make_user('loc_creator')
        user.user_permissions.add(self._perm('view_locations'))
        user.user_permissions.add(self._perm('create_locations'))
        user.user_permissions.add(self._perm('view_location'))
        user.profile.assigned_locations.add(self.root)

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            '/api/inventory/locations/',
            {
                'name': 'Invalid Extra Root',
                'location_type': LocationType.DEPARTMENT,
                'parent_location': None,
                'is_standalone': True,
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn('parent_location', resp.data)


class LocationStandaloneWorkflowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_superuser(
            username='location_admin',
            email='location_admin@example.com',
            password='pw',
        )
        self.client.force_authenticate(user=self.user)

    def _rows(self, response):
        data = response.data
        if isinstance(data, dict) and 'results' in data:
            return data['results']
        return data

    def test_standalone_create_endpoint_creates_first_root_and_central_store(self):
        resp = self.client.post(
            '/api/inventory/locations/standalone/',
            {
                'name': 'NED University',
                'location_type': LocationType.DEPARTMENT,
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 201)
        root = Location.objects.get(pk=resp.data['id'])
        self.assertIsNone(root.parent_location)
        self.assertTrue(root.is_standalone)
        self.assertEqual(root.hierarchy_level, 0)
        self.assertIsNotNone(root.auto_created_store)
        self.assertEqual(root.auto_created_store.name, 'Central Store')
        self.assertTrue(root.auto_created_store.is_main_store)
        self.assertEqual(root.auto_created_store.parent_location, root)

    def test_standalone_create_endpoint_locks_child_to_root_and_uses_main_store_name(self):
        root = Location.objects.create(
            name='NED University',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )

        resp = self.client.post(
            '/api/inventory/locations/standalone/',
            {
                'name': 'CSIT',
                'location_type': LocationType.DEPARTMENT,
                'parent_location': None,
                'is_standalone': False,
                'main_store_name': 'CSIT Main Inventory',
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 201)
        csit = Location.objects.get(pk=resp.data['id'])
        self.assertEqual(csit.parent_location, root)
        self.assertTrue(csit.is_standalone)
        self.assertEqual(csit.auto_created_store.name, 'CSIT Main Inventory')
        self.assertEqual(csit.auto_created_store.parent_location, csit)

    def test_standalone_list_endpoint_returns_only_standalone_locations(self):
        root = Location.objects.create(
            name='NED University',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        csit = Location.objects.create(
            name='CSIT',
            location_type=LocationType.DEPARTMENT,
            parent_location=root,
            is_standalone=True,
        )
        room = Location.objects.create(
            name='CSIT Room 101',
            location_type=LocationType.ROOM,
            parent_location=csit,
            is_standalone=False,
        )

        resp = self.client.get('/api/inventory/locations/standalone/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(root.id, returned_ids)
        self.assertIn(csit.id, returned_ids)
        self.assertNotIn(root.auto_created_store.id, returned_ids)
        self.assertNotIn(csit.auto_created_store.id, returned_ids)
        self.assertNotIn(room.id, returned_ids)

    def test_children_endpoint_returns_immediate_children_and_root_excludes_standalones(self):
        root = Location.objects.create(
            name='NED University',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        csit = Location.objects.create(
            name='CSIT',
            location_type=LocationType.DEPARTMENT,
            parent_location=root,
            is_standalone=True,
        )
        root_lab = Location.objects.create(
            name='Root Lab',
            location_type=LocationType.LAB,
            parent_location=root,
            is_standalone=False,
        )
        csit_room = Location.objects.create(
            name='CSIT Room 101',
            location_type=LocationType.ROOM,
            parent_location=csit,
            is_standalone=False,
        )
        nested_room = Location.objects.create(
            name='Nested Room',
            location_type=LocationType.ROOM,
            parent_location=csit_room,
            is_standalone=False,
        )

        root_resp = self.client.get(f'/api/inventory/locations/{root.id}/children/')
        csit_resp = self.client.get(f'/api/inventory/locations/{csit.id}/children/')

        self.assertEqual(root_resp.status_code, 200)
        root_ids = {row['id'] for row in self._rows(root_resp)}
        self.assertIn(root_lab.id, root_ids)
        self.assertIn(root.auto_created_store.id, root_ids)
        self.assertNotIn(csit.id, root_ids)

        self.assertEqual(csit_resp.status_code, 200)
        csit_ids = {row['id'] for row in self._rows(csit_resp)}
        self.assertIn(csit_room.id, csit_ids)
        self.assertIn(csit.auto_created_store.id, csit_ids)
        self.assertNotIn(nested_room.id, csit_ids)

    def test_children_create_endpoint_locks_parent_and_marks_child_non_standalone(self):
        root = Location.objects.create(
            name='NED University',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        csit = Location.objects.create(
            name='CSIT',
            location_type=LocationType.DEPARTMENT,
            parent_location=root,
            is_standalone=True,
        )

        resp = self.client.post(
            f'/api/inventory/locations/{csit.id}/children/',
            {
                'name': 'CSIT Lab 1',
                'location_type': LocationType.LAB,
                'parent_location': root.id,
                'is_standalone': True,
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 201)
        child = Location.objects.get(pk=resp.data['id'])
        self.assertEqual(child.parent_location, csit)
        self.assertFalse(child.is_standalone)


class CategoryApiDomainPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(
            name='Existing Category',
            category_type=CategoryType.FIXED_ASSET,
        )

    def setUp(self):
        self.client = APIClient()

    def _perm(self, codename):
        return Permission.objects.get(content_type__app_label='inventory', codename=codename)

    def _make_user(self, username):
        return User.objects.create_user(username=username, password='pw')

    def test_list_requires_domain_view_categories_perm(self):
        user = self._make_user('category_legacy_view')
        user.user_permissions.add(self._perm('view_category'))

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/categories/')

        self.assertEqual(resp.status_code, 403)

    def test_list_allows_domain_view_categories_perm(self):
        user = self._make_user('category_domain_view')
        user.user_permissions.add(self._perm('view_categories'))

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/categories/')

        self.assertEqual(resp.status_code, 200)

    def test_create_requires_domain_create_categories_perm(self):
        user = self._make_user('category_legacy_add')
        user.user_permissions.add(self._perm('add_category'))

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            '/api/inventory/categories/',
            {
                'name': 'Posted Category',
                'category_type': CategoryType.CONSUMABLE,
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 403)

    def test_create_allows_domain_create_categories_perm(self):
        user = self._make_user('category_domain_create')
        user.user_permissions.add(self._perm('create_categories'))

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            '/api/inventory/categories/',
            {
                'name': 'Domain Created Category',
                'category_type': CategoryType.CONSUMABLE,
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 201)

    def test_patch_requires_domain_edit_categories_perm(self):
        user = self._make_user('category_legacy_change')
        user.user_permissions.add(self._perm('change_category'))

        self.client.force_authenticate(user=user)
        resp = self.client.patch(
            f'/api/inventory/categories/{self.category.id}/',
            {'name': 'Renamed Category'},
            format='json',
        )

        self.assertEqual(resp.status_code, 403)

    def test_patch_allows_domain_edit_categories_perm(self):
        user = self._make_user('category_domain_edit')
        user.user_permissions.add(self._perm('edit_categories'))

        self.client.force_authenticate(user=user)
        resp = self.client.patch(
            f'/api/inventory/categories/{self.category.id}/',
            {'name': 'Domain Edited Category'},
            format='json',
        )

        self.assertEqual(resp.status_code, 200)

    def test_delete_requires_domain_delete_categories_perm(self):
        user = self._make_user('category_legacy_delete')
        user.user_permissions.add(self._perm('delete_category'))

        self.client.force_authenticate(user=user)
        resp = self.client.delete(f'/api/inventory/categories/{self.category.id}/')

        self.assertEqual(resp.status_code, 403)

    def test_delete_allows_domain_delete_categories_perm(self):
        user = self._make_user('category_domain_delete')
        user.user_permissions.add(self._perm('delete_categories'))

        category = Category.objects.create(
            name='Domain Deletable Category',
            category_type=CategoryType.CONSUMABLE,
        )

        self.client.force_authenticate(user=user)
        resp = self.client.delete(f'/api/inventory/categories/{category.id}/')

        self.assertEqual(resp.status_code, 204)

    def test_create_with_notes_succeeds_without_invalid_model_kwargs(self):
        user = self._make_user('category_notes_create')
        user.user_permissions.add(self._perm('create_categories'))

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            '/api/inventory/categories/',
            {
                'name': 'Category With Notes',
                'category_type': CategoryType.CONSUMABLE,
                'notes': 'created from category form',
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 201)
        created = Category.objects.get(id=resp.data['id'])
        self.assertEqual(created.name, 'Category With Notes')
        self.assertEqual(created.category_type, CategoryType.CONSUMABLE)

    def test_patch_with_notes_succeeds_without_invalid_model_kwargs(self):
        user = self._make_user('category_notes_patch')
        user.user_permissions.add(self._perm('edit_categories'))

        self.client.force_authenticate(user=user)
        resp = self.client.patch(
            f'/api/inventory/categories/{self.category.id}/',
            {
                'name': 'Existing Category (Updated With Notes)',
                'notes': 'edited from category form',
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 200)
        self.category.refresh_from_db()
        self.assertEqual(self.category.name, 'Existing Category (Updated With Notes)')

    def test_patch_rejects_subcategory_tracking_type_change(self):
        user = self._make_user('category_tracking_patch')
        user.user_permissions.add(self._perm('edit_categories'))
        parent = Category.objects.create(
            name='Fixed Asset Parent',
            category_type=CategoryType.FIXED_ASSET,
            default_depreciation_rate=12,
        )
        child = Category.objects.create(
            name='Fixed Asset Child',
            parent_category=parent,
            category_type=CategoryType.FIXED_ASSET,
            tracking_type=TrackingType.INDIVIDUAL,
            default_depreciation_rate=12,
        )

        self.client.force_authenticate(user=user)
        resp = self.client.patch(
            f'/api/inventory/categories/{child.id}/',
            {'tracking_type': TrackingType.BATCH},
            format='json',
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn('tracking_type', resp.data)
        child.refresh_from_db()
        self.assertEqual(child.tracking_type, TrackingType.INDIVIDUAL)


class ItemApiDomainPermissionTests(TestCase):
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
        cls.store = Location.objects.create(
            name='CSIT Store',
            location_type=LocationType.STORE,
            parent_location=cls.csit,
            is_store=True,
        )
        cls.parent_category = Category.objects.create(
            name='Computing Hardware',
            category_type=CategoryType.FIXED_ASSET,
        )
        cls.subcategory = Category.objects.create(
            name='Processors',
            parent_category=cls.parent_category,
            category_type=CategoryType.FIXED_ASSET,
            tracking_type=TrackingType.INDIVIDUAL,
        )
        cls.item = Item.objects.create(
            name='Core i5 Processor',
            category=cls.subcategory,
            acct_unit='unit',
            specifications='Intel Core i5',
        )
        cls.batch = ItemBatch.objects.create(
            item=cls.item,
            batch_number='B-001',
        )
        cls.instance = ItemInstance.objects.create(
            item=cls.item,
            batch=cls.batch,
            current_location=cls.store,
            serial_number='CPU-001',
        )
        StockRecord.objects.create(
            item=cls.item,
            batch=cls.batch,
            location=cls.store,
            quantity=5,
            allocated_quantity=2,
        )

    def setUp(self):
        self.client = APIClient()

    def _perm(self, codename):
        return Permission.objects.get(content_type__app_label='inventory', codename=codename)

    def _make_user(self, username):
        user = User.objects.create_user(username=username, password='pw')
        user.profile.assigned_locations.add(self.root)
        return user

    def test_list_requires_domain_view_items_perm(self):
        user = self._make_user('item_legacy_view')
        user.user_permissions.add(self._perm('view_item'))

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/items/')

        self.assertEqual(resp.status_code, 403)

    def test_list_allows_domain_view_items_perm(self):
        user = self._make_user('item_domain_view')
        user.user_permissions.add(self._perm('view_items'))

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/items/')

        self.assertEqual(resp.status_code, 200)

    def test_create_requires_domain_create_items_perm(self):
        user = self._make_user('item_legacy_add')
        user.user_permissions.add(self._perm('add_item'))

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            '/api/inventory/items/',
            {
                'name': 'Blocked Item',
                'category': self.subcategory.id,
                'acct_unit': 'unit',
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 403)

    def test_create_allows_domain_create_items_perm(self):
        user = self._make_user('item_domain_create')
        user.user_permissions.add(self._perm('create_items'))

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            '/api/inventory/items/',
            {
                'name': 'Domain Created Item',
                'category': self.subcategory.id,
                'acct_unit': 'unit',
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 201)

    def test_distribution_hierarchical_allows_domain_view_items_perm(self):
        user = self._make_user('item_distribution_view')
        user.user_permissions.add(self._perm('view_items'))

        self.client.force_authenticate(user=user)
        resp = self.client.get(f'/api/inventory/distribution/hierarchical/?item={self.item.id}')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in resp.data}
        self.assertIn(self.csit.id, returned_ids)

    def test_batches_allow_domain_view_items_perm(self):
        user = self._make_user('item_batch_view')
        user.user_permissions.add(self._perm('view_items'))

        self.client.force_authenticate(user=user)
        resp = self.client.get(f'/api/inventory/item-batches/?item={self.item.id}')

        self.assertEqual(resp.status_code, 200)

    def test_instances_require_domain_view_items_perm(self):
        user = self._make_user('item_instance_no_view')

        self.client.force_authenticate(user=user)
        resp = self.client.get(f'/api/inventory/item-instances/?item={self.item.id}')

        self.assertEqual(resp.status_code, 403)

    def test_instances_allow_domain_view_items_perm(self):
        user = self._make_user('item_instance_view')
        user.user_permissions.add(self._perm('view_items'))

        self.client.force_authenticate(user=user)
        resp = self.client.get(f'/api/inventory/item-instances/?item={self.item.id}')

        self.assertEqual(resp.status_code, 200)
