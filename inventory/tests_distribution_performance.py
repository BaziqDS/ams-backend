from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from inventory.models import Category, Item, Location, LocationType, StockRecord


class DistributionQueryTests(TestCase):
    def test_distribution_query_count_stays_bounded_as_rows_grow(self):
        user = User.objects.create_superuser(username='distribution-admin')
        root = Location.objects.create(name='Distribution root', location_type=LocationType.DEPARTMENT)
        child = Location.objects.create(name='Distribution unit', parent_location=root, location_type=LocationType.DEPARTMENT, is_standalone=True)
        parent = Category.objects.create(name='Distribution parent', code='DP', category_type='CONSUMABLE')
        category = Category.objects.create(name='Distribution leaf', code='DL', parent_category=parent, tracking_type='QUANTITY')
        client = APIClient()
        client.force_authenticate(user)
        counts = []
        for target in (1, 25):
            for number in range(Item.objects.count(), target):
                item = Item.objects.create(name=f'Item {number}', code=f'DIST-{number}', category=category, acct_unit='Each')
                StockRecord.objects.create(item=item, location=child.auto_created_store, quantity=10)
            with CaptureQueriesContext(connection) as queries:
                response = client.get('/api/inventory/distribution/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.data['results']), target)
            for row in response.data['results']:
                self.assertEqual(row['category_type'], 'CONSUMABLE')
                self.assertEqual(row['quantity'], 10)
                self.assertEqual(row['source_inspection_contracts'], [])
            counts.append(len(queries))
        self.assertLessEqual(counts[1], counts[0] + 3, counts)
