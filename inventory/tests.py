# pyright: reportAttributeAccessIssue=false
from django.contrib.auth.models import Permission, User
from django.test import TestCase
from rest_framework.test import APIClient

from inventory.models import Category, CategoryType, Location, LocationType


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

    def test_assignable_preserves_existing_delegation_behavior(self):
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
        self.assertNotIn(self.dept_b.id, returned_ids)

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
