from datetime import timedelta

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from inventory.models import (
    Category,
    CategoryType,
    InspectionCertificate,
    InspectionStage,
    Item,
    ItemBatch,
    ItemInstance,
    Location,
    LocationType,
    StockEntry,
    StockRecord,
    TrackingType,
)
from notifications.models import NotificationEvent, UserNotification


class NotificationsApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.root = Location.objects.create(
            name="Notification Root",
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        self.department = Location.objects.create(
            name="Notification Department",
            location_type=LocationType.DEPARTMENT,
            parent_location=self.root,
            is_standalone=True,
        )
        self.department_store = self.department.auto_created_store

    def _perm(self, dotted: str) -> Permission:
        app_label, codename = dotted.split(".", 1)
        return Permission.objects.get(content_type__app_label=app_label, codename=codename)

    def _grant(self, user: User, *dotted_perms: str) -> User:
        user.user_permissions.add(*[self._perm(dotted) for dotted in dotted_perms])
        return user

    def _make_user(self, username: str, *dotted_perms: str) -> User:
        user = User.objects.create_user(username=username, password="pw")
        user.profile.assigned_locations.add(self.department_store)
        if dotted_perms:
            self._grant(user, *dotted_perms)
        return user

    def _make_leaf_category(self, *, name: str, category_type: str, tracking_type: str) -> Category:
        parent = Category.objects.create(name=f"{name} Parent", category_type=category_type)
        return Category.objects.create(name=name, parent_category=parent, tracking_type=tracking_type)

    def test_summary_and_alerts_endpoint_surface_curated_counts(self):
        user = self._make_user(
            "alerts.user",
            "inventory.fill_stock_details",
            "inventory.acknowledge_stockentry",
            "inventory.view_items",
            "inventory.manage_depreciation",
        )

        inspection = InspectionCertificate.objects.create(
            date=timezone.now().date(),
            contract_no="IC-ALERT-001",
            contract_date=timezone.now().date(),
            contractor_name="Alert Supplier",
            contractor_address="Block A",
            indenter="Alert Indenter",
            indent_no="IND-ALERT-1",
            department=self.department,
            delivery_type="FULL",
            stage=InspectionStage.STOCK_DETAILS,
            status="IN_PROGRESS",
        )

        with self.captureOnCommitCallbacks(execute=True):
            StockEntry.objects.create(
                entry_type="RECEIPT",
                to_location=self.department_store,
                status="PENDING_ACK",
                created_by=user,
                remarks="Receiver acknowledgement pending",
            )

        consumable_category = self._make_leaf_category(
            name="Alert Consumables",
            category_type=CategoryType.CONSUMABLE,
            tracking_type=TrackingType.QUANTITY,
        )
        low_stock_item = Item.objects.create(
            name="Low Stock Item",
            category=consumable_category,
            acct_unit="pcs",
            low_stock_threshold=5,
        )
        StockRecord.objects.create(item=low_stock_item, location=self.department_store, quantity=2)

        out_of_stock_item = Item.objects.create(
            name="Out of Stock Item",
            category=consumable_category,
            acct_unit="pcs",
            low_stock_threshold=4,
        )
        self.assertEqual(out_of_stock_item.stock_records.count(), 0)

        perishable_category = self._make_leaf_category(
            name="Alert Perishables",
            category_type=CategoryType.PERISHABLE,
            tracking_type=TrackingType.QUANTITY,
        )
        expiring_item = Item.objects.create(
            name="Expiring Batch Item",
            category=perishable_category,
            acct_unit="boxes",
            low_stock_threshold=0,
        )
        expiring_batch = ItemBatch.objects.create(
            item=expiring_item,
            batch_number="BATCH-ALERT-1",
            expiry_date=timezone.now().date() + timedelta(days=7),
        )
        StockRecord.objects.create(item=expiring_item, batch=expiring_batch, location=self.department_store, quantity=6)

        fixed_asset_category = self._make_leaf_category(
            name="Alert Fixed Assets",
            category_type=CategoryType.FIXED_ASSET,
            tracking_type=TrackingType.INDIVIDUAL,
        )
        fixed_asset_item = Item.objects.create(
            name="Capitalization Pending Asset",
            category=fixed_asset_category,
            acct_unit="unit",
        )
        ItemInstance.objects.create(
            item=fixed_asset_item,
            current_location=self.department_store,
            status="AVAILABLE",
        )

        self.client.force_authenticate(user=user)

        summary_response = self.client.get("/api/notifications/summary/")
        self.assertEqual(summary_response.status_code, 200)
        self.assertEqual(summary_response.data["open_alerts"], 5)
        self.assertEqual(summary_response.data["modules"]["inspections"]["count"], 1)
        self.assertEqual(summary_response.data["modules"]["stock-entries"]["count"], 1)
        self.assertEqual(summary_response.data["modules"]["items"]["count"], 2)
        self.assertEqual(summary_response.data["modules"]["depreciation"]["count"], 1)
        self.assertGreaterEqual(summary_response.data["unread_notifications"], 1)

        alerts_response = self.client.get("/api/notifications/alerts/")
        self.assertEqual(alerts_response.status_code, 200)
        alert_keys = {row["key"] for row in alerts_response.data}
        self.assertIn("inspections-stock-details", alert_keys)
        self.assertIn("stock-entries-pending-ack", alert_keys)
        self.assertIn("items-low-stock", alert_keys)
        self.assertNotIn("items-out-of-stock", alert_keys)
        self.assertIn("items-expiring-batches", alert_keys)
        self.assertIn("depreciation-uncapitalized", alert_keys)

    def test_items_alert_summary_counts_alert_groups_and_deep_links_into_matching_focus(self):
        user = self._make_user("items.alerts.user", "inventory.view_items")

        consumable_category = self._make_leaf_category(
            name="Items Alert Consumables",
            category_type=CategoryType.CONSUMABLE,
            tracking_type=TrackingType.QUANTITY,
        )
        Item.objects.create(
            name="Out of Stock Item 1",
            category=consumable_category,
            acct_unit="pcs",
            low_stock_threshold=5,
        )
        Item.objects.create(
            name="Out of Stock Item 2",
            category=consumable_category,
            acct_unit="pcs",
            low_stock_threshold=3,
        )

        perishable_category = self._make_leaf_category(
            name="Items Alert Perishables",
            category_type=CategoryType.PERISHABLE,
            tracking_type=TrackingType.QUANTITY,
        )
        batch_item = Item.objects.create(
            name="Expired Batch Item",
            category=perishable_category,
            acct_unit="boxes",
            low_stock_threshold=0,
        )
        first_expired_batch = ItemBatch.objects.create(
            item=batch_item,
            batch_number="EXP-001",
            expiry_date=timezone.now().date() - timedelta(days=2),
        )
        second_expired_batch = ItemBatch.objects.create(
            item=batch_item,
            batch_number="EXP-002",
            expiry_date=timezone.now().date() - timedelta(days=1),
        )
        StockRecord.objects.create(item=batch_item, batch=first_expired_batch, location=self.department_store, quantity=4)
        StockRecord.objects.create(item=batch_item, batch=second_expired_batch, location=self.department_store, quantity=6)

        self.client.force_authenticate(user=user)

        summary_response = self.client.get("/api/notifications/summary/")
        self.assertEqual(summary_response.status_code, 200)
        self.assertEqual(summary_response.data["open_alerts"], 1)
        self.assertEqual(summary_response.data["modules"]["items"]["count"], 1)
        self.assertEqual(summary_response.data["modules"]["items"]["critical"], 1)

        alerts_response = self.client.get("/api/notifications/alerts/")
        self.assertEqual(alerts_response.status_code, 200)
        alerts_by_key = {row["key"]: row for row in alerts_response.data}

        self.assertNotIn("items-out-of-stock", alerts_by_key)
        self.assertEqual(alerts_by_key["items-expired-batches"]["count"], 2)
        self.assertEqual(alerts_by_key["items-expired-batches"]["href"], "/items?tracking=perishable&focus=expired-batches")

    def test_pending_ack_stock_entry_creation_notifies_receiver_scope(self):
        receiver = self._make_user("receiver.user", "inventory.acknowledge_stockentry")

        with self.captureOnCommitCallbacks(execute=True):
            entry = StockEntry.objects.create(
                entry_type="RECEIPT",
                to_location=self.department_store,
                status="PENDING_ACK",
                remarks="Pending receiver acknowledgement",
            )

        notification = UserNotification.objects.get(user=receiver)
        self.assertEqual(notification.event.kind, "stock_entry.pending_ack")
        self.assertEqual(notification.event.entity_id, entry.id)
        self.assertFalse(notification.is_read)

    def test_feed_read_read_all_and_clear_endpoints_update_user_state(self):
        user = self._make_user("feed.user")
        event_one = NotificationEvent.objects.create(
            module="inspections",
            kind="inspection.completed",
            severity="info",
            title="Inspection completed",
            message="Inspection IC-001 was completed.",
            href="/inspections/1",
        )
        event_two = NotificationEvent.objects.create(
            module="stock-entries",
            kind="stock_entry.pending_ack",
            severity="warning",
            title="Receipt pending acknowledgement",
            message="Receipt SE-001 is waiting for acknowledgement.",
            href="/stock-entries/1",
        )
        first = UserNotification.objects.create(user=user, event=event_one)
        second = UserNotification.objects.create(user=user, event=event_two)

        self.client.force_authenticate(user=user)

        feed_response = self.client.get("/api/notifications/feed/")
        self.assertEqual(feed_response.status_code, 200)
        self.assertEqual(feed_response.data["count"], 2)

        read_response = self.client.post(f"/api/notifications/feed/{first.id}/read/", {}, format="json")
        self.assertEqual(read_response.status_code, 200)
        first.refresh_from_db()
        self.assertTrue(first.is_read)
        self.assertIsNotNone(first.read_at)

        read_all_response = self.client.post("/api/notifications/feed/read-all/", {}, format="json")
        self.assertEqual(read_all_response.status_code, 200)
        self.assertEqual(read_all_response.data["updated"], 1)
        second.refresh_from_db()
        self.assertTrue(second.is_read)
        self.assertIsNotNone(second.read_at)

        clear_response = self.client.post("/api/notifications/feed/clear/", {}, format="json")
        self.assertEqual(clear_response.status_code, 200)
        self.assertEqual(clear_response.data["deleted"], 2)
        self.assertFalse(UserNotification.objects.filter(user=user).exists())

    def test_rejecting_inspection_generates_notification_for_visible_watchers(self):
        actor = self._make_user(
            "inspection.actor",
            "inventory.view_inspectioncertificate",
            "inventory.change_inspectioncertificate",
        )
        watcher = self._make_user(
            "inspection.watcher",
            "inventory.view_inspectioncertificate",
        )

        inspection = InspectionCertificate.objects.create(
            date=timezone.now().date(),
            contract_no="IC-REJECT-001",
            contract_date=timezone.now().date(),
            contractor_name="Reject Supplier",
            contractor_address="Block B",
            indenter="Reject Indenter",
            indent_no="IND-REJECT-1",
            department=self.department,
            delivery_type="FULL",
            stage=InspectionStage.STOCK_DETAILS,
            status="IN_PROGRESS",
        )

        self.client.force_authenticate(user=actor)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/inventory/inspections/{inspection.id}/reject/",
                {"reason": "Missing stock register evidence."},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            UserNotification.objects.filter(
                user=watcher,
                event__kind="inspection.rejected",
                event__entity_id=inspection.id,
            ).exists()
        )
