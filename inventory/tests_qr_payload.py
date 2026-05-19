from django.test import TestCase

from inventory.models import (
    AllocationStatus,
    Category,
    CategoryType,
    InstanceStatus,
    Item,
    ItemInstance,
    Location,
    LocationType,
    Person,
    StockAllocation,
    StockEntry,
    StockEntryItem,
    TrackingType,
)


class ItemInstanceQrPayloadTests(TestCase):
    def setUp(self):
        self.root = Location.objects.create(
            name="NED University",
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        self.central_store = self.root.auto_created_store
        self.department = Location.objects.create(
            name="CSIT Department",
            location_type=LocationType.DEPARTMENT,
            parent_location=self.root,
            is_standalone=True,
        )
        self.department_store = self.department.auto_created_store
        self.lab = Location.objects.create(
            name="Software Engineering Laboratory",
            location_type=LocationType.LAB,
            parent_location=self.department,
        )
        self.parent_category = Category.objects.create(
            name="Electronics",
            category_type=CategoryType.FIXED_ASSET,
        )
        self.subcategory = Category.objects.create(
            name="Multimedia Equipment",
            parent_category=self.parent_category,
            tracking_type=TrackingType.INDIVIDUAL,
        )
        self.item = Item.objects.create(
            name="Projector",
            category=self.subcategory,
            acct_unit="unit",
        )

    def _instance(self, **overrides):
        defaults = {
            "item": self.item,
            "current_location": self.department_store,
            "status": InstanceStatus.AVAILABLE,
            "qr_code": "AMS-INST-TEST0001",
        }
        defaults.update(overrides)
        return ItemInstance.objects.create(**defaults)

    def test_qr_payload_for_store_held_instance(self):
        instance = self._instance()

        self.assertEqual(
            instance.build_qr_payload(),
            "\n".join([
                "NED UNIVERSITY - ASSET IDENTIFICATION",
                "",
                "Asset Instance No.: AMS-INST-TEST0001",
                "Classification: Electronics / Multimedia Equipment",
                "Item Name: Projector",
                "",
                "Operational Status: In Store",
                "Current Placement: CSIT Department - Main Store",
                "Custodian: CSIT Department - Main Store",
                "Owning Store: CSIT Department - Main Store",
            ]),
        )

    def test_qr_payload_for_employee_allocation_keeps_owning_store_separate(self):
        instance = self._instance(status=InstanceStatus.ALLOCATED)
        employee = Person.objects.create(name="Dr. Ahmed Khan", designation="Professor", department="CSIT")
        entry = StockEntry.objects.create(
            entry_type="ISSUE",
            from_location=self.department_store,
            issued_to=employee,
            status="COMPLETED",
        )
        entry_item = StockEntryItem.objects.create(stock_entry=entry, item=self.item, quantity=1)
        entry_item.instances.add(instance)
        StockAllocation.objects.create(
            item=self.item,
            source_location=self.department_store,
            quantity=1,
            allocated_to_person=employee,
            status=AllocationStatus.ALLOCATED,
            stock_entry=entry,
        )

        payload = instance.build_qr_payload()

        self.assertIn("Operational Status: Allocated", payload)
        self.assertIn("Current Placement: CSIT Department - Main Store", payload)
        self.assertIn("Custodian: Dr. Ahmed Khan", payload)
        self.assertIn("Owning Store: CSIT Department - Main Store", payload)

    def test_qr_payload_for_non_store_allocation_uses_location_as_custodian(self):
        instance = self._instance(current_location=self.lab, status=InstanceStatus.ALLOCATED)
        entry = StockEntry.objects.create(
            entry_type="ISSUE",
            from_location=self.department_store,
            to_location=self.lab,
            status="COMPLETED",
        )
        entry_item = StockEntryItem.objects.create(stock_entry=entry, item=self.item, quantity=1)
        entry_item.instances.add(instance)
        StockAllocation.objects.create(
            item=self.item,
            source_location=self.department_store,
            quantity=1,
            allocated_to_location=self.lab,
            status=AllocationStatus.ALLOCATED,
            stock_entry=entry,
        )

        payload = instance.build_qr_payload()

        self.assertIn("Operational Status: Allocated", payload)
        self.assertIn("Current Placement: Software Engineering Laboratory", payload)
        self.assertIn("Custodian: Software Engineering Laboratory", payload)
        self.assertIn("Owning Store: CSIT Department - Main Store", payload)

    def test_qr_payload_uses_formal_special_status_terms(self):
        maintenance_instance = self._instance(status=InstanceStatus.MAINTENANCE, qr_code="AMS-INST-MAINT")
        disposed_instance = self._instance(status=InstanceStatus.JUNK, qr_code="AMS-INST-DISPOSED")
        transit_instance = self._instance(status=InstanceStatus.IN_TRANSIT, qr_code="AMS-INST-TRANSIT")

        self.assertIn("Operational Status: Under Maintenance", maintenance_instance.build_qr_payload())
        self.assertIn("Operational Status: Disposed", disposed_instance.build_qr_payload())
        self.assertIn("Current Placement: Not Applicable", disposed_instance.build_qr_payload())
        self.assertIn("Operational Status: In Transit", transit_instance.build_qr_payload())
        self.assertIn("Custodian: Pending Receipt", transit_instance.build_qr_payload())
