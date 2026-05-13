from django.contrib.auth.models import User
from django.db import OperationalError
from django.test import TestCase
from rest_framework.test import APIClient
from unittest.mock import Mock, patch

from inventory.models import (
    Category,
    CategoryType,
    Item,
    Location,
    LocationType,
    StockEntry,
    StockEntryItem,
    StockRecord,
    StockRegister,
    TrackingType,
)
from inventory.services.deletion_policy import delete_with_policy


class InventoryDeletionPolicyTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_superuser(
            username="deletion_policy_admin",
            email="deletion_policy_admin@example.com",
            password="pw",
        )
        self.client.force_authenticate(user=self.user)

    def _category(self, name="Equipment", parent=None):
        data = {
            "name": name,
            "parent_category": parent,
            "category_type": CategoryType.FIXED_ASSET if parent is None else None,
            "tracking_type": TrackingType.QUANTITY if parent is not None else None,
        }
        return Category.objects.create(**data)

    def _item(self, name="Projector"):
        parent = self._category("Assets")
        child = self._category("AV Equipment", parent=parent)
        return Item.objects.create(name=name, category=child, acct_unit="pcs")

    def _rows(self, response):
        data = response.data
        if isinstance(data, dict) and "results" in data:
            return data["results"]
        return data

    def _root(self):
        return Location.objects.create(
            name="NED Test Root",
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )

    def test_category_with_subcategories_exposes_and_enforces_delete_blockers(self):
        parent = self._category("Consumables")
        child = self._category("Markers", parent=parent)

        list_resp = self.client.get("/api/inventory/categories/")

        self.assertEqual(list_resp.status_code, 200)
        rows = self._rows(list_resp)
        parent_row = next(row for row in rows if row["id"] == parent.id)
        child_row = next(row for row in rows if row["id"] == child.id)
        self.assertFalse(parent_row["can_delete"])
        self.assertIn("subcategories", " ".join(parent_row["delete_blockers"]).lower())
        self.assertTrue(child_row["can_delete"])

        delete_resp = self.client.delete(f"/api/inventory/categories/{parent.id}/")

        self.assertEqual(delete_resp.status_code, 400)
        self.assertTrue(Category.objects.filter(pk=parent.id).exists())

    def test_category_with_items_cannot_be_deleted(self):
        item = self._item()
        category = item.category

        resp = self.client.delete(f"/api/inventory/categories/{category.id}/")

        self.assertEqual(resp.status_code, 400)
        self.assertIn("item", str(resp.data).lower())
        self.assertTrue(Category.objects.filter(pk=category.id).exists())

    def test_item_with_inventory_history_cannot_be_deleted(self):
        root = self._root()
        item = self._item()
        StockRecord.objects.create(item=item, location=root.auto_created_store, quantity=1)

        detail_resp = self.client.get(f"/api/inventory/items/{item.id}/")

        self.assertEqual(detail_resp.status_code, 200)
        self.assertFalse(detail_resp.data["can_delete"])
        self.assertIn("inventory", " ".join(detail_resp.data["delete_blockers"]).lower())

        delete_resp = self.client.delete(f"/api/inventory/items/{item.id}/")

        self.assertEqual(delete_resp.status_code, 400)
        self.assertTrue(Item.objects.filter(pk=item.id).exists())

    def test_empty_standalone_location_deletes_its_auto_created_store(self):
        root = self._root()
        store_id = root.auto_created_store_id

        resp = self.client.delete(f"/api/inventory/locations/{root.id}/")

        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Location.objects.filter(pk=root.id).exists())
        self.assertFalse(Location.objects.filter(pk=store_id).exists())

    def test_empty_auto_created_main_store_can_be_deleted_and_unlinked(self):
        root = self._root()
        store_id = root.auto_created_store_id

        resp = self.client.delete(f"/api/inventory/locations/{store_id}/")

        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Location.objects.filter(pk=store_id).exists())
        root.refresh_from_db()
        self.assertIsNone(root.auto_created_store_id)

    def test_delete_retries_once_when_sqlite_reports_database_locked(self):
        instance = Mock()
        instance.delete.side_effect = [OperationalError("database is locked"), None]

        with patch("inventory.services.deletion_policy.time.sleep") as sleep:
            delete_with_policy(instance)

        self.assertEqual(instance.delete.call_count, 2)
        sleep.assert_called_once()

    def test_missing_main_store_can_be_recreated_from_children_endpoint(self):
        root = self._root()
        old_store_id = root.auto_created_store_id
        root.auto_created_store.delete()
        root.refresh_from_db()
        self.assertIsNone(root.auto_created_store_id)

        resp = self.client.post(
            f"/api/inventory/locations/{root.id}/children/",
            {
                "name": "Replacement Main Store",
                "code": "",
                "location_type": LocationType.DEPARTMENT,
                "is_active": True,
                "create_main_store": True,
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 201)
        root.refresh_from_db()
        self.assertIsNotNone(root.auto_created_store_id)
        self.assertNotEqual(root.auto_created_store_id, old_store_id)
        self.assertEqual(root.auto_created_store.name, "Replacement Main Store")
        self.assertTrue(root.auto_created_store.is_store)
        self.assertTrue(root.auto_created_store.is_main_store)
        self.assertTrue(root.auto_created_store.is_auto_created)

    def test_main_store_recreation_is_rejected_when_one_already_exists(self):
        root = self._root()

        resp = self.client.post(
            f"/api/inventory/locations/{root.id}/children/",
            {
                "name": "Duplicate Main Store",
                "code": "",
                "location_type": LocationType.DEPARTMENT,
                "is_active": True,
                "create_main_store": True,
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("main store", str(resp.data).lower())
        root.refresh_from_db()
        self.assertNotEqual(root.auto_created_store.name, "Duplicate Main Store")

    def test_store_location_with_register_cannot_be_deleted(self):
        root = self._root()
        store = root.auto_created_store
        StockRegister.objects.create(register_number="CSR-LOCKED", register_type="CSR", store=store)

        detail_resp = self.client.get(f"/api/inventory/locations/{store.id}/")

        self.assertEqual(detail_resp.status_code, 200)
        self.assertFalse(detail_resp.data["can_delete"])
        self.assertIn("register", " ".join(detail_resp.data["delete_blockers"]).lower())

        delete_resp = self.client.delete(f"/api/inventory/locations/{store.id}/")

        self.assertEqual(delete_resp.status_code, 400)
        self.assertTrue(Location.objects.filter(pk=store.id).exists())

    def test_used_stock_register_cannot_be_deleted(self):
        root = self._root()
        item = self._item()
        register = StockRegister.objects.create(register_number="CSR-USED", register_type="CSR", store=root.auto_created_store)
        entry = StockEntry.objects.create(entry_type="RECEIPT", to_location=root.auto_created_store, status="DRAFT")
        StockEntryItem.objects.create(stock_entry=entry, item=item, quantity=1, stock_register=register)

        detail_resp = self.client.get(f"/api/inventory/stock-registers/{register.id}/")

        self.assertEqual(detail_resp.status_code, 200)
        self.assertFalse(detail_resp.data["can_delete"])
        self.assertIn("stock entry", " ".join(detail_resp.data["delete_blockers"]).lower())

        delete_resp = self.client.delete(f"/api/inventory/stock-registers/{register.id}/")

        self.assertEqual(delete_resp.status_code, 400)
        self.assertTrue(StockRegister.objects.filter(pk=register.id).exists())

    def test_completed_stock_entry_cannot_be_deleted(self):
        root = self._root()
        entry = StockEntry.objects.create(entry_type="RECEIPT", to_location=root.auto_created_store, status="COMPLETED")

        detail_resp = self.client.get(f"/api/inventory/stock-entries/{entry.id}/")

        self.assertEqual(detail_resp.status_code, 200)
        self.assertFalse(detail_resp.data["can_delete"])
        self.assertIn("audit", " ".join(detail_resp.data["delete_blockers"]).lower())

        delete_resp = self.client.delete(f"/api/inventory/stock-entries/{entry.id}/")

        self.assertEqual(delete_resp.status_code, 400)
        self.assertTrue(StockEntry.objects.filter(pk=entry.id).exists())
