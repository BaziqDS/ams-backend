from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from inventory.models import (
    Category,
    CategoryType,
    DepreciationAssetClass,
    DepreciationEntry,
    DepreciationRateVersion,
    DepreciationRun,
    FixedAssetRegisterEntry,
    InspectionCertificate,
    InspectionItem,
    InspectionStage,
    Item,
    ItemBatch,
    Location,
    LocationType,
    StockRegister,
    TrackingType,
)
from inventory.services.depreciation_service import post_depreciation_run, preview_depreciation_run


class DepreciationTestDataMixin:
    def setUp(self):
        self.user = User.objects.create_user(username="dep.finance", password="pass")
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
        self.central_register = StockRegister.objects.create(
            register_number="DSR-CENTRAL",
            register_type="DSR",
            store=self.root.auto_created_store,
            created_by=self.user,
        )
        self.department_register = StockRegister.objects.create(
            register_number="DSR-CSIT",
            register_type="DSR",
            store=self.department.auto_created_store,
            created_by=self.user,
        )
        self.fixed_parent = Category.objects.create(
            name="Fixed Assets",
            code="FIX",
            category_type=CategoryType.FIXED_ASSET,
            default_depreciation_rate=Decimal("20.00"),
        )
        self.asset_individual_category = Category.objects.create(
            name="Computers",
            code="COMP",
            parent_category=self.fixed_parent,
            tracking_type=TrackingType.INDIVIDUAL,
        )
        self.asset_lot_category = Category.objects.create(
            name="Furniture",
            code="FURN",
            parent_category=self.fixed_parent,
            tracking_type=TrackingType.QUANTITY,
        )
        self.consumable_parent = Category.objects.create(
            name="Consumables",
            code="CON",
            category_type=CategoryType.CONSUMABLE,
        )
        self.consumable_category = Category.objects.create(
            name="Stationery",
            code="STAT",
            parent_category=self.consumable_parent,
            tracking_type=TrackingType.QUANTITY,
        )
        self.laptop = Item.objects.create(
            name="Laptop",
            category=self.asset_individual_category,
            acct_unit="unit",
            created_by=self.user,
        )
        self.chair = Item.objects.create(
            name="Classroom Chair",
            category=self.asset_lot_category,
            acct_unit="unit",
            created_by=self.user,
        )
        self.marker = Item.objects.create(
            name="Whiteboard Marker",
            category=self.consumable_category,
            acct_unit="box",
            created_by=self.user,
        )

    def make_certificate(self, contract_no="DEP-IC-001"):
        return InspectionCertificate.objects.create(
            date=date(2026, 1, 15),
            contract_no=contract_no,
            contract_date=date(2026, 1, 10),
            contractor_name="Asset Supplier",
            indenter="CSIT",
            indent_no=f"IND-{contract_no}",
            department=self.department,
            date_of_delivery=date(2026, 1, 14),
            delivery_type="FULL",
            inspected_by="Inspector",
            date_of_inspection=date(2026, 1, 15),
            consignee_name="Consignee",
            consignee_designation="Manager",
            stage=InspectionStage.FINANCE_REVIEW,
            status="IN_PROGRESS",
            initiated_by=self.user,
            stock_filled_by=self.user,
            central_store_filled_by=self.user,
        )

    def add_inspection_item(self, certificate, item, quantity, unit_price, *, batch_number=""):
        return InspectionItem.objects.create(
            inspection_certificate=certificate,
            item=item,
            item_description=item.name,
            tendered_quantity=quantity,
            accepted_quantity=quantity,
            rejected_quantity=0,
            unit_price=Decimal(str(unit_price)),
            central_register=self.central_register,
            central_register_page_no="10",
            stock_register=self.department_register,
            stock_register_page_no="12",
            batch_number=batch_number,
        )


class DepreciationInspectionCapitalizationTests(DepreciationTestDataMixin, TestCase):
    def test_completion_creates_register_entries_for_fixed_asset_instances_and_lots_only(self):
        certificate = self.make_certificate()
        self.add_inspection_item(certificate, self.laptop, 2, "100000")
        self.add_inspection_item(certificate, self.chair, 50, "2500", batch_number="CHAIR-LOT")
        self.add_inspection_item(certificate, self.marker, 20, "100")

        certificate.status = "COMPLETED"
        certificate.stage = InspectionStage.COMPLETED
        certificate.finance_reviewed_by = self.user
        certificate.finance_reviewed_at = timezone.make_aware(datetime(2026, 1, 20))
        certificate.save()

        laptop_entries = FixedAssetRegisterEntry.objects.filter(item=self.laptop)
        chair_entries = FixedAssetRegisterEntry.objects.filter(item=self.chair)
        marker_entries = FixedAssetRegisterEntry.objects.filter(item=self.marker)

        self.assertEqual(laptop_entries.count(), 2)
        self.assertEqual({entry.target_type for entry in laptop_entries}, {"INSTANCE"})
        self.assertEqual({entry.original_cost for entry in laptop_entries}, {Decimal("100000.00")})
        self.assertTrue(all(entry.instance_id for entry in laptop_entries))

        self.assertEqual(chair_entries.count(), 1)
        chair_entry = chair_entries.get()
        self.assertEqual(chair_entry.target_type, "LOT")
        self.assertEqual(chair_entry.original_quantity, 50)
        self.assertEqual(chair_entry.remaining_quantity, 50)
        self.assertEqual(chair_entry.original_cost, Decimal("125000.00"))
        self.assertIsNotNone(chair_entry.batch_id)
        self.assertTrue(ItemBatch.objects.filter(item=self.chair, batch_number="CHAIR-LOT").exists())

        self.assertEqual(marker_entries.count(), 0)

    def test_completion_is_idempotent_for_depreciation_register_entries(self):
        certificate = self.make_certificate("DEP-IC-IDEMPOTENT")
        self.add_inspection_item(certificate, self.chair, 10, "1000", batch_number="CHAIR-IDEMP")

        certificate.status = "COMPLETED"
        certificate.stage = InspectionStage.COMPLETED
        certificate.finance_reviewed_by = self.user
        certificate.save()
        certificate.save()

        self.assertEqual(FixedAssetRegisterEntry.objects.filter(item=self.chair).count(), 1)

    def test_completion_uses_finance_confirmed_depreciation_profile(self):
        certificate = self.make_certificate("DEP-IC-FINANCE-PROFILE")
        asset_class = DepreciationAssetClass.objects.create(
            name="Lab Computers",
            code="LAB-COMP",
            category=self.asset_individual_category,
            created_by=self.user,
        )
        inspection_item = self.add_inspection_item(certificate, self.laptop, 2, "90000")
        inspection_item.depreciation_asset_class = asset_class
        inspection_item.capitalization_cost = Decimal("150000.00")
        inspection_item.capitalization_date = date(2026, 2, 5)
        inspection_item.save()

        certificate.status = "COMPLETED"
        certificate.stage = InspectionStage.COMPLETED
        certificate.finance_reviewed_by = self.user
        certificate.save()

        entries = FixedAssetRegisterEntry.objects.filter(item=self.laptop).order_by("id")
        self.assertEqual(entries.count(), 2)
        self.assertEqual({entry.asset_class_id for entry in entries}, {asset_class.id})
        self.assertEqual({entry.original_cost for entry in entries}, {Decimal("75000.00")})
        self.assertEqual({entry.capitalization_date for entry in entries}, {date(2026, 2, 5)})


class DepreciationRunCalculationTests(DepreciationTestDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.asset_class = DepreciationAssetClass.objects.create(
            name="Furniture",
            code="FURN",
            category=self.asset_lot_category,
            created_by=self.user,
        )
        self.rate_20 = DepreciationRateVersion.objects.create(
            asset_class=self.asset_class,
            rate=Decimal("20.00"),
            effective_from=date(2024, 7, 1),
            source_reference="Initial FBR rate",
            created_by=self.user,
            approved_by=self.user,
        )
        self.batch = ItemBatch.objects.create(item=self.chair, batch_number="FURN-LOT-1", created_by=self.user)
        self.asset = FixedAssetRegisterEntry.objects.create(
            item=self.chair,
            batch=self.batch,
            target_type="LOT",
            asset_class=self.asset_class,
            original_quantity=10,
            remaining_quantity=10,
            original_cost=Decimal("100000.00"),
            capitalization_date=date(2024, 7, 1),
            depreciation_start_date=date(2024, 7, 1),
            created_by=self.user,
        )

    def test_annual_wdv_run_uses_effective_rate_versions_without_rewriting_history(self):
        rows_2024 = preview_depreciation_run(2024)
        self.assertEqual(rows_2024[0]["depreciation_amount"], Decimal("20000.00"))

        post_depreciation_run(2024, self.user)
        first_entry = DepreciationEntry.objects.get(asset=self.asset, fiscal_year_start=2024)
        self.assertEqual(first_entry.rate, Decimal("20.00"))
        self.assertEqual(first_entry.closing_value, Decimal("80000.00"))

        DepreciationRateVersion.objects.create(
            asset_class=self.asset_class,
            rate=Decimal("22.00"),
            effective_from=date(2025, 7, 1),
            source_reference="Updated FBR rate",
            created_by=self.user,
            approved_by=self.user,
        )

        post_depreciation_run(2025, self.user)
        first_entry.refresh_from_db()
        second_entry = DepreciationEntry.objects.get(asset=self.asset, fiscal_year_start=2025)

        self.assertEqual(first_entry.rate, Decimal("20.00"))
        self.assertEqual(first_entry.closing_value, Decimal("80000.00"))
        self.assertEqual(second_entry.rate, Decimal("22.00"))
        self.assertEqual(second_entry.opening_value, Decimal("80000.00"))
        self.assertEqual(second_entry.depreciation_amount, Decimal("17600.00"))
        self.assertEqual(second_entry.closing_value, Decimal("62400.00"))

    def test_value_adjustment_changes_future_opening_wdv_without_rewriting_posted_entry(self):
        post_depreciation_run(2024, self.user)
        first_entry = DepreciationEntry.objects.get(asset=self.asset, fiscal_year_start=2024)

        self.asset.adjustments.create(
            adjustment_type="DISPOSAL",
            effective_date=date(2025, 1, 15),
            amount=Decimal("-10000.00"),
            quantity_delta=-1,
            reason="One chair disposed",
            created_by=self.user,
        )

        post_depreciation_run(2025, self.user)
        second_entry = DepreciationEntry.objects.get(asset=self.asset, fiscal_year_start=2025)
        first_entry.refresh_from_db()

        self.assertEqual(first_entry.closing_value, Decimal("80000.00"))
        self.assertEqual(second_entry.opening_value, Decimal("70000.00"))
        self.assertEqual(second_entry.depreciation_amount, Decimal("14000.00"))
        self.assertEqual(second_entry.closing_value, Decimal("56000.00"))


class DepreciationApiPermissionTests(DepreciationTestDataMixin, TestCase):
    def test_depreciation_endpoints_require_depreciation_permission(self):
        client = APIClient()
        client.force_authenticate(user=self.user)

        denied = client.get("/api/inventory/depreciation/assets/")
        self.assertEqual(denied.status_code, 403)

        self.user.user_permissions.add(
            Permission.objects.get(content_type__app_label="inventory", codename="view_depreciation")
        )

        allowed = client.get("/api/inventory/depreciation/assets/")
        self.assertEqual(allowed.status_code, 200)

    def test_rate_configuration_requires_full_depreciation_permission(self):
        asset_class = DepreciationAssetClass.objects.create(
            name="Computers",
            code="COMP",
            category=self.asset_individual_category,
            created_by=self.user,
        )
        client = APIClient()
        client.force_authenticate(user=self.user)
        self.user.user_permissions.add(
            Permission.objects.get(content_type__app_label="inventory", codename="view_depreciation"),
            Permission.objects.get(content_type__app_label="inventory", codename="manage_depreciation"),
        )

        denied = client.post("/api/inventory/depreciation/rates/", {
            "asset_class": asset_class.id,
            "rate": "20.00",
            "effective_from": "2026-07-01",
            "source_reference": "Finance circular",
        }, format="json")
        self.assertEqual(denied.status_code, 403)

        self.user.user_permissions.add(
            Permission.objects.get(content_type__app_label="inventory", codename="post_depreciation")
        )

        allowed = client.post("/api/inventory/depreciation/rates/", {
            "asset_class": asset_class.id,
            "rate": "20.00",
            "effective_from": "2026-07-01",
            "source_reference": "Finance circular",
        }, format="json")
        self.assertEqual(allowed.status_code, 201)

    def test_draft_run_can_use_default_policy_when_policy_is_omitted(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        self.user.user_permissions.add(
            Permission.objects.get(content_type__app_label="inventory", codename="view_depreciation"),
            Permission.objects.get(content_type__app_label="inventory", codename="manage_depreciation"),
        )

        response = client.post("/api/inventory/depreciation/runs/", {
            "fiscal_year_start": 2026,
            "notes": "Annual draft",
        }, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["fiscal_year_start"], 2026)
        self.assertEqual(response.data["status"], "DRAFT")
        self.assertIsNotNone(response.data["policy"])
