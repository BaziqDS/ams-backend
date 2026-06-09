# pyright: reportAttributeAccessIssue=false
from django.contrib.auth.models import Permission, User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from inventory.models import (
    Category,
    CategoryType,
    Item,
    Location,
    LocationTag,
    LocationTagCategory,
    LocationType,
    StockRecord,
    TrackingType,
)


class LocationTagMetadataTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            username='tag.admin',
            email='tag.admin@example.com',
            password='pw',
        )
        self.root = Location.objects.create(
            name='Tag Metadata Root',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )

    def _rows(self, response):
        data = response.data
        if isinstance(data, dict) and 'results' in data:
            return data['results']
        return data

    def test_location_serializer_exposes_structured_tags_without_changing_hierarchy(self):
        white_house = LocationTag.objects.create(
            name='White House',
            category=LocationTagCategory.BUILDING,
            code='WH',
        )
        faculty = LocationTag.objects.create(
            name='Faculty of ECE',
            category=LocationTagCategory.DEAN_FACULTY,
            code='F-ECE',
        )
        registrar = Location.objects.create(
            name='Registrar Office',
            location_type=LocationType.OFFICE,
            parent_location=self.root,
            is_standalone=True,
        )
        registrar.tags.set([white_house, faculty])

        self.client.force_authenticate(user=self.admin)
        response = self.client.get(f'/api/inventory/locations/{registrar.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Registrar Office')
        self.assertEqual(set(response.data['tags']), {white_house.id, faculty.id})
        self.assertEqual(
            {tag['label'] for tag in response.data['tags_display']},
            {'Building: White House', 'Dean Faculty: Faculty of ECE'},
        )
        self.assertEqual(response.data['parent_location'], self.root.id)
        self.assertEqual(registrar.get_parent_standalone(), registrar)

    def test_location_list_omits_delete_policy_fields_without_extra_blocker_queries(self):
        Location.objects.bulk_create(
            [
                Location(
                    name=f'List Option Location {index:02d}',
                    code=f'LIST-OPTION-{index:02d}',
                    location_type=LocationType.OFFICE,
                    parent_location=self.root,
                    is_standalone=True,
                )
                for index in range(25)
            ]
        )
        self.client.force_authenticate(user=self.admin)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/api/inventory/locations/?page_size=500')

        self.assertEqual(response.status_code, 200, response.data)
        rows = self._rows(response)
        self.assertGreaterEqual(len(rows), 25)
        self.assertNotIn('can_delete', rows[0])
        self.assertNotIn('delete_blockers', rows[0])
        self.assertLess(len(queries), 50)

    def test_location_standalone_list_uses_lightweight_serializer(self):
        Location.objects.bulk_create(
            [
                Location(
                    name=f'Standalone Option Location {index:02d}',
                    code=f'STANDALONE-OPTION-{index:02d}',
                    location_type=LocationType.OFFICE,
                    parent_location=self.root,
                    is_standalone=True,
                )
                for index in range(25)
            ]
        )
        self.client.force_authenticate(user=self.admin)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/api/inventory/locations/standalone/')

        self.assertEqual(response.status_code, 200, response.data)
        rows = self._rows(response)
        self.assertGreaterEqual(len(rows), 25)
        self.assertNotIn('can_delete', rows[0])
        self.assertNotIn('delete_blockers', rows[0])
        self.assertLess(len(queries), 50)

    def test_location_children_list_uses_lightweight_serializer(self):
        standalone = Location.objects.create(
            name='Children Lightweight Parent',
            location_type=LocationType.DEPARTMENT,
            parent_location=self.root,
            is_standalone=True,
        )
        for index in range(25):
            Location.objects.create(
                name=f'Child Option Location {index:02d}',
                code=f'CHILD-OPTION-{index:02d}',
                location_type=LocationType.OFFICE,
                parent_location=standalone,
                is_standalone=False,
            )
        self.client.force_authenticate(user=self.admin)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(f'/api/inventory/locations/{standalone.id}/children/')

        self.assertEqual(response.status_code, 200, response.data)
        rows = self._rows(response)
        self.assertGreaterEqual(len(rows), 25)
        self.assertNotIn('can_delete', rows[0])
        self.assertNotIn('delete_blockers', rows[0])
        self.assertLess(len(queries), 50)

    def test_location_detail_keeps_delete_policy_fields(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.get(f'/api/inventory/locations/{self.root.id}/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('can_delete', response.data)
        self.assertIn('delete_blockers', response.data)

    def test_create_location_tag_api(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            '/api/inventory/location-tags/',
            {
                'name': 'Administrative Department',
                'category': LocationTagCategory.DEPARTMENT_NATURE,
                'code': 'ADMIN-DEPT',
                'color': '#64748b',
                'is_active': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        tag = LocationTag.objects.get(name='Administrative Department')
        self.assertEqual(tag.category, LocationTagCategory.DEPARTMENT_NATURE)
        self.assertTrue(tag.color.startswith('#'))

    def test_create_location_tag_rejects_case_insensitive_duplicate_name(self):
        LocationTag.objects.create(
            name='White House',
            category=LocationTagCategory.BUILDING,
            code='WH-DEDUP',
        )
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            '/api/inventory/location-tags/',
            {
                'name': '  white   house  ',
                'category': LocationTagCategory.BUILDING,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('name', response.data)

    def test_create_location_accepts_tag_ids_without_affecting_hierarchy(self):
        white_house = LocationTag.objects.create(
            name='Create White House',
            category=LocationTagCategory.BUILDING,
            code='CWH',
        )
        faculty = LocationTag.objects.create(
            name='Create Faculty',
            category=LocationTagCategory.DEAN_FACULTY,
            code='CFAC',
        )
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            '/api/inventory/locations/standalone/',
            {
                'name': 'Tagged Standalone Location',
                'location_type': LocationType.DEPARTMENT,
                'tags': [white_house.id, faculty.id],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        location = Location.objects.get(name='Tagged Standalone Location')
        self.assertEqual(location.parent_location, self.root)
        self.assertEqual(set(location.tags.values_list('id', flat=True)), {white_house.id, faculty.id})

    def test_update_location_can_clear_tags(self):
        white_house = LocationTag.objects.create(
            name='Clear White House',
            category=LocationTagCategory.BUILDING,
            code='CLWH',
        )
        location = Location.objects.create(
            name='Tagged Location To Clear',
            location_type=LocationType.OFFICE,
            parent_location=self.root,
            is_standalone=True,
        )
        location.tags.add(white_house)
        self.client.force_authenticate(user=self.admin)

        response = self.client.patch(
            f'/api/inventory/locations/{location.id}/',
            {'tags': []},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        location.refresh_from_db()
        self.assertEqual(location.tags.count(), 0)

    def test_tag_assignment_does_not_expand_user_location_access(self):
        white_house = LocationTag.objects.create(
            name='Shared White House',
            category=LocationTagCategory.BUILDING,
            code='SWH',
        )
        registrar = Location.objects.create(
            name='Tagged Registrar Office',
            location_type=LocationType.OFFICE,
            parent_location=self.root,
            is_standalone=True,
        )
        procurement = Location.objects.create(
            name='Tagged Procurement Cell',
            location_type=LocationType.OFFICE,
            parent_location=self.root,
            is_standalone=True,
        )
        registrar.tags.add(white_house)
        procurement.tags.add(white_house)
        user = User.objects.create_user(username='tag.access.user', password='pw')
        user.profile.assigned_locations.add(registrar)

        self.assertTrue(user.profile.has_location_access(registrar))
        self.assertFalse(user.profile.has_location_access(procurement))

    def test_non_admin_can_list_tags_for_location_forms(self):
        tag = LocationTag.objects.create(
            name='Main Campus',
            category=LocationTagCategory.CAMPUS_ZONE,
            code='MAIN',
        )
        user = User.objects.create_user(username='tag.scoped.user', password='pw')
        user.profile.assigned_locations.add(self.root)
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label='inventory', codename='view_locations')
        )

        self.client.force_authenticate(user=user)
        response = self.client.get('/api/inventory/location-tags/')

        self.assertEqual(response.status_code, 200)
        names = {row['name'] for row in self._rows(response)}
        self.assertIn(tag.name, names)

    def test_stock_distribution_exposes_location_tags_for_reports(self):
        tag = LocationTag.objects.create(
            name='Distribution White House',
            category=LocationTagCategory.BUILDING,
            code='DWH',
        )
        self.root.tags.add(tag)
        parent_category = Category.objects.create(
            name='Distribution Assets',
            category_type=CategoryType.FIXED_ASSET,
        )
        category = Category.objects.create(
            name='Distribution Asset Subcategory',
            parent_category=parent_category,
            tracking_type=TrackingType.QUANTITY,
        )
        item = Item.objects.create(
            name='Distribution Test Item',
            category=category,
            acct_unit='pcs',
        )
        StockRecord.objects.create(item=item, location=self.root, quantity=5)
        self.client.force_authenticate(user=self.admin)

        response = self.client.get('/api/inventory/distribution/')

        self.assertEqual(response.status_code, 200)
        rows = self._rows(response)
        row = next(record for record in rows if record['item'] == item.id)
        self.assertEqual(row['location_tags'], [tag.id])
        self.assertEqual(row['location_tags_display'][0]['label'], 'Building: Distribution White House')
