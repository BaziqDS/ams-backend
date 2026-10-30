from django.contrib.auth.models import User, Permission
from django.test import TestCase
from rest_framework.test import APIClient

from inventory.models import StockEntry, Location


class MovementPaginationTests(TestCase):
    def test_movement_pages_preserve_domain_permissions_and_location_scope(self):
        user = User.objects.create_user(username='scoped-movement-user')
        root = Location.objects.create(name='Movement root', location_type='DEPARTMENT')
        visible = Location.objects.create(name='Visible movement department', parent_location=root, location_type='DEPARTMENT', is_standalone=True)
        hidden = Location.objects.create(name='Hidden movement department', parent_location=root, location_type='DEPARTMENT', is_standalone=True)
        first = StockEntry.objects.create(entry_type='ISSUE', from_location=visible.auto_created_store, status='DRAFT')
        other = StockEntry.objects.create(entry_type='ISSUE', from_location=hidden.auto_created_store, status='DRAFT')
        user.profile.assigned_locations.set([visible.auto_created_store])
        client = APIClient()
        client.force_authenticate(user)
        self.assertEqual(client.get('/api/inventory/stock-entries/movements/').status_code, 403)
        user.user_permissions.add(Permission.objects.get(content_type__app_label='inventory', codename='view_stock_entries'))
        client.force_authenticate(User.objects.get(pk=user.pk))
        canonical = client.get('/api/inventory/stock-entries/').data['results']
        response = client.get('/api/inventory/stock-entries/movements/')
        self.assertEqual(response.status_code, 200)
        ids = {row['id'] for row in response.data['results']}
        self.assertEqual(ids, {row['id'] for row in canonical})
        self.assertIn(first.pk, ids)
        self.assertNotIn(other.pk, ids)

    def test_pages_keep_issue_receipt_pair_together_and_filter_by_effective_status(self):
        user = User.objects.create_superuser(username='movement-admin')
        issue = StockEntry.objects.create(entry_type='ISSUE', status='DRAFT', remarks='needle')
        receipt = StockEntry.objects.create(entry_type='RECEIPT', status='DRAFT', reference_entry=issue, reference_purpose='AUTO_RECEIPT')
        StockEntry.objects.filter(pk=receipt.pk).update(status='COMPLETED')
        StockEntry.objects.bulk_create([StockEntry(entry_number=f'MOVE-{i}', entry_type='ISSUE', status='DRAFT') for i in range(13)])
        client = APIClient()
        client.force_authenticate(user)
        response = client.get('/api/inventory/stock-entries/movements/?page=1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 14)
        self.assertIsNotNone(response.data['next'])
        filtered = client.get('/api/inventory/stock-entries/movements/?search=needle&status=COMPLETED')
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.data['count'], 1)
        self.assertEqual({row['id'] for row in filtered.data['results']}, {issue.pk, receipt.pk})
        self.assertEqual(client.get('/api/inventory/stock-entries/movements/?search=needle&status=DRAFT').data['count'], 0)
