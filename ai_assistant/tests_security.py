from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from rest_framework.test import APIClient

from inventory.models import Category, Item, Location, LocationType, StockRecord


class AssistantBoundaryTests(TestCase):
    def test_disabled_user_cannot_invoke_chat_or_stream(self):
        user = User.objects.create_user(username='ai-disabled')
        client = APIClient()
        client.force_authenticate(user)
        with patch('ai_assistant.views.InventoryAssistantService') as service:
            for path in ('/api/ai/chat/', '/api/ai/chat/stream/'):
                self.assertEqual(client.post(path, {'message': 'hello'}, format='json').status_code, 403)
            service.assert_not_called()

    def test_assistant_reads_only_permitted_inventory_resources_and_scoped_stock(self):
        from ai_assistant.resources import read_inventory_resource

        root = Location.objects.create(name='AI root', location_type=LocationType.DEPARTMENT)
        child = Location.objects.create(name='AI unit', location_type=LocationType.DEPARTMENT, parent_location=root, is_standalone=True)
        other = Location.objects.create(name='Hidden unit', location_type=LocationType.DEPARTMENT, parent_location=root, is_standalone=True)
        user = User.objects.create_user(username='scoped-ai')
        user.profile.assigned_locations.set([child])
        user.user_permissions.add(Permission.objects.get(content_type__app_label='inventory', codename='view_items'))
        category = Category.objects.create(name='AI category', code='AI', category_type='CONSUMABLE')
        item = Item.objects.create(name='Visible item', code='AI-V', category=category, acct_unit='Each')
        hidden = Item.objects.create(name='Private item', code='AI-H', category=category, acct_unit='Each')
        StockRecord.objects.create(item=item, location=child.auto_created_store, quantity=3)
        StockRecord.objects.create(item=hidden, location=other.auto_created_store, quantity=9)
        data = read_inventory_resource(user, 'distribution')
        self.assertIn('Visible item', str(data))
        self.assertNotIn('Private item', str(data))
        for resource in ('auth_user', '../users', 'SELECT * FROM auth_user', 'inspections'):
            self.assertIn('error', read_inventory_resource(user, resource))
