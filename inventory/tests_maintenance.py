# pyright: reportAttributeAccessIssue=false
from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from ams.permissions_manifest import MODULES, READ_PERMS
from inventory.models import (
    Category,
    CategoryType,
    InstanceStatus,
    Item,
    ItemBatch,
    ItemInstance,
    Location,
    LocationType,
    MaintenanceLog,
    MaintenanceStatus,
    MaintenanceTargetType,
    StockRecord,
    TrackingType,
)
from user_management.services.capability_service import resolve_selections_to_codenames
from user_management.signals import EXPLICIT_PERMISSION_IMPLICATIONS


class MaintenanceTestMixin:
    def _perm(self, dotted):
        app_label, codename = dotted.split(".", 1)
        return Permission.objects.get(content_type__app_label=app_label, codename=codename)

    def _user_with_perms(self, username, dotted_perms):
        user = User.objects.create_user(username=username, password="pw")
        role = Group.objects.create(name=f"{username} role")
        for dotted in dotted_perms:
            role.permissions.add(self._perm(dotted))
        user.groups.add(role)
        return user

    def _setup_inventory(self):
        root = Location.objects.create(
            name="Maintenance Root",
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        store = Location.objects.create(
            name="Maintenance Store",
            location_type=LocationType.STORE,
            parent_location=root,
            is_store=True,
            is_main_store=True,
        )
        parent = Category.objects.create(
            name="Maintenance Fixed Assets",
            category_type=CategoryType.FIXED_ASSET,
        )
        instance_category = Category.objects.create(
            name="Maintainable Equipment",
            parent_category=parent,
            tracking_type=TrackingType.INDIVIDUAL,
        )
        batch_category = Category.objects.create(
            name="Maintainable Lot Equipment",
            parent_category=parent,
            tracking_type=TrackingType.QUANTITY,
        )
        instance_item = Item.objects.create(
            name="Oscilloscope",
            category=instance_category,
            acct_unit="unit",
            low_stock_threshold=0,
        )
        batch_item = Item.objects.create(
            name="Lab Chair Lot",
            category=batch_category,
            acct_unit="unit",
            low_stock_threshold=0,
        )
        instance = ItemInstance.objects.create(
            item=instance_item,
            current_location=store,
            status=InstanceStatus.IN_USE,
        )
        batch = ItemBatch.objects.create(
            item=batch_item,
            batch_number="LOT-2026-A",
        )
        StockRecord.objects.create(
            item=batch_item,
            batch=batch,
            location=store,
            quantity=12,
        )
        return root, store, instance_item, batch_item, instance, batch


class MaintenanceManifestTests(TestCase):
    def test_maintenance_manifest_declares_permissions_and_dependencies(self):
        resolved = resolve_selections_to_codenames({"maintenance": "manage"})

        self.assertIn("maintenance", MODULES)
        self.assertIn("inventory.view_maintenance", resolved)
        self.assertIn("inventory.create_maintenance", resolved)
        self.assertIn("inventory.edit_maintenance", resolved)
        self.assertIn("inventory.close_maintenance", resolved)
        self.assertIn("inventory.view_items", resolved)
        self.assertIn("inventory.view_locations", resolved)
        self.assertNotIn("inventory.delete_maintenance", resolved)
        self.assertEqual(READ_PERMS["maintenance"], ["inventory.view_maintenance"])

    def test_maintenance_permission_implications_declared(self):
        self.assertEqual(EXPLICIT_PERMISSION_IMPLICATIONS["create_maintenance"], ["view_maintenance"])
        self.assertEqual(EXPLICIT_PERMISSION_IMPLICATIONS["edit_maintenance"], ["view_maintenance"])
        self.assertEqual(EXPLICIT_PERMISSION_IMPLICATIONS["close_maintenance"], ["view_maintenance"])
        self.assertEqual(EXPLICIT_PERMISSION_IMPLICATIONS["approve_maintenance"], ["view_maintenance"])
        self.assertEqual(EXPLICIT_PERMISSION_IMPLICATIONS["delete_maintenance"], ["view_maintenance"])


class MaintenanceWorkOrderApiTests(MaintenanceTestMixin, TestCase):
    def setUp(self):
        self.root, self.store, self.instance_item, self.batch_item, self.instance, self.batch = self._setup_inventory()
        self.user = self._user_with_perms(
            "maintenance.manager",
            MODULES["maintenance"]["full"]["perms"] + ["inventory.view_items", "inventory.view_locations"],
        )
        self.user.profile.assigned_locations.add(self.root)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_create_instance_work_order_records_history(self):
        response = self.client.post("/api/inventory/maintenance/work-orders/", {
            "target_type": MaintenanceTargetType.INSTANCE,
            "instance": self.instance.id,
            "title": "Annual preventive maintenance",
            "maintenance_type": "PREVENTIVE",
            "trigger_type": "CALENDAR",
            "priority": "HIGH",
            "criticality": "HIGH",
            "due_date": timezone.localdate().isoformat(),
        }, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["target_label"], "Oscilloscope")
        self.assertEqual(response.data["affected_quantity"], 1)
        self.assertEqual(MaintenanceLog.objects.filter(work_order_id=response.data["id"]).count(), 1)

    def test_create_batch_work_order_requires_location_and_available_quantity(self):
        response = self.client.post("/api/inventory/maintenance/work-orders/", {
            "target_type": MaintenanceTargetType.BATCH,
            "batch": self.batch.id,
            "affected_quantity": 3,
            "location": self.store.id,
            "title": "Lot refurbishment",
            "maintenance_type": "CORRECTIVE",
            "trigger_type": "MANUAL",
            "priority": "MEDIUM",
            "criticality": "MEDIUM",
        }, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["target_label"], "Lab Chair Lot / Batch LOT-2026-A")
        self.assertEqual(response.data["location"], self.store.id)

    def test_batch_work_order_rejects_quantity_above_stock_at_location(self):
        response = self.client.post("/api/inventory/maintenance/work-orders/", {
            "target_type": MaintenanceTargetType.BATCH,
            "batch": self.batch.id,
            "affected_quantity": 13,
            "location": self.store.id,
            "title": "Impossible lot maintenance",
            "maintenance_type": "CORRECTIVE",
            "trigger_type": "MANUAL",
            "priority": "MEDIUM",
            "criticality": "MEDIUM",
        }, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("affected_quantity", response.data)

    def test_start_and_complete_instance_work_order_updates_status_and_history(self):
        create_response = self.client.post("/api/inventory/maintenance/work-orders/", {
            "target_type": MaintenanceTargetType.INSTANCE,
            "instance": self.instance.id,
            "title": "Repair power supply",
            "maintenance_type": "CORRECTIVE",
            "trigger_type": "FAILURE",
            "priority": "CRITICAL",
            "criticality": "HIGH",
        }, format="json")
        work_order_id = create_response.data["id"]

        start_response = self.client.post(f"/api/inventory/maintenance/work-orders/{work_order_id}/start/", {}, format="json")
        self.instance.refresh_from_db()
        self.assertEqual(start_response.status_code, 200)
        self.assertEqual(start_response.data["status"], MaintenanceStatus.IN_PROGRESS)
        self.assertEqual(self.instance.status, InstanceStatus.MAINTENANCE)

        complete_response = self.client.post(f"/api/inventory/maintenance/work-orders/{work_order_id}/complete/", {
            "action_taken": "Replaced power module and validated calibration.",
            "outcome_notes": "Returned to service.",
            "condition_after": "Operational",
            "actual_cost": "1250.00",
        }, format="json")
        self.instance.refresh_from_db()

        self.assertEqual(complete_response.status_code, 200)
        self.assertEqual(complete_response.data["status"], MaintenanceStatus.COMPLETED)
        self.assertEqual(self.instance.status, InstanceStatus.IN_USE)
        self.assertEqual(MaintenanceLog.objects.filter(work_order_id=work_order_id).count(), 3)

    def test_user_without_maintenance_permission_cannot_list_work_orders(self):
        viewer = self._user_with_perms("items.viewer", ["inventory.view_items"])
        viewer.profile.assigned_locations.add(self.root)
        client = APIClient()
        client.force_authenticate(user=viewer)

        response = client.get("/api/inventory/maintenance/work-orders/")

        self.assertEqual(response.status_code, 403)

    def test_create_work_order_rejects_target_outside_location_scope(self):
        limited_user = self._user_with_perms(
            "maintenance.limited",
            MODULES["maintenance"]["full"]["perms"] + ["inventory.view_items", "inventory.view_locations"],
        )
        limited_user.profile.assigned_locations.add(self.store)
        limited_client = APIClient()
        limited_client.force_authenticate(user=limited_user)

        outside_unit = Location.objects.create(
            name="Outside Unit",
            location_type=LocationType.DEPARTMENT,
            parent_location=self.root,
            is_standalone=True,
        )
        outside_store = Location.objects.create(
            name="Outside Store",
            location_type=LocationType.STORE,
            parent_location=outside_unit,
            is_store=True,
            is_main_store=True,
        )
        outside_instance = ItemInstance.objects.create(
            item=self.instance_item,
            current_location=outside_store,
            status=InstanceStatus.IN_USE,
        )

        response = limited_client.post("/api/inventory/maintenance/work-orders/", {
            "target_type": MaintenanceTargetType.INSTANCE,
            "instance": outside_instance.id,
            "title": "Out-of-scope maintenance",
            "maintenance_type": "CORRECTIVE",
            "trigger_type": "MANUAL",
            "priority": "MEDIUM",
            "criticality": "MEDIUM",
        }, format="json")

        self.assertEqual(response.status_code, 403)
