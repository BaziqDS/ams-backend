from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase

from inventory.models import (
    Category,
    CategoryType,
    InspectionCertificate,
    InspectionItem,
    InspectionStage,
    Item,
    ItemBatch,
    Location,
    LocationType,
    StockEntry,
    StockEntryItem,
    TrackingType,
)
from inventory.serializers.stockentry_serializer import StockEntrySerializer


class StockEntryBatchProvenanceSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="store.user", password="pass")
        self.root = Location.objects.create(
            name="NED",
            code="NED",
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
            created_by=self.user,
        )
        self.department = Location.objects.create(
            name="CSIT",
            code="CSIT",
            parent_location=self.root,
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
            created_by=self.user,
        )
        parent = Category.objects.create(
            name="Consumables",
            code="CON",
            category_type=CategoryType.CONSUMABLE,
        )
        category = Category.objects.create(
            name="Stationery",
            code="STAT",
            parent_category=parent,
            tracking_type=TrackingType.QUANTITY,
        )
        self.item = Item.objects.create(
            name="A4 Paper",
            category=category,
            acct_unit="ream",
            created_by=self.user,
        )

    def test_manual_issue_line_exposes_inspection_source_for_tracking_batch(self):
        certificate = InspectionCertificate.objects.create(
            date=date(2026, 1, 15),
            contract_no="IC-PAPER-001",
            contract_date=date(2026, 1, 10),
            contractor_name="Paper Supplier",
            indenter="CSIT",
            indent_no="IND-PAPER-001",
            department=self.department,
            date_of_delivery=date(2026, 1, 14),
            delivery_type="FULL",
            stage=InspectionStage.COMPLETED,
            status="COMPLETED",
            initiated_by=self.user,
        )
        inspection_item = InspectionItem.objects.create(
            inspection_certificate=certificate,
            item=self.item,
            item_description=self.item.name,
            tendered_quantity=200,
            accepted_quantity=200,
            rejected_quantity=0,
            batch_number="IC-PAPER-001-L1",
        )
        batch = ItemBatch.objects.create(
            item=self.item,
            batch_number=inspection_item.batch_number,
            created_by=self.user,
        )
        issue = StockEntry.objects.create(
            entry_type="ISSUE",
            from_location=self.root.auto_created_store,
            to_location=self.department.auto_created_store,
            status="PENDING_ACK",
            created_by=self.user,
        )
        StockEntryItem.objects.create(
            stock_entry=issue,
            item=self.item,
            batch=batch,
            quantity=120,
        )

        data = StockEntrySerializer(issue).data
        line = data["items"][0]

        self.assertEqual(line["source_inspection"], certificate.id)
        self.assertEqual(line["source_inspection_number"], "IC-PAPER-001")
        self.assertEqual(line["source_inspection_item"], inspection_item.id)
        self.assertEqual(line["source_inspection_department"], "CSIT")
