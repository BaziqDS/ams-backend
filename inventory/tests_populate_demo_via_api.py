import shutil
import tempfile
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings

from inventory.demo_population import DEFAULT_DEMO_PASSWORD, PopulateConfig, populate_demo_data
from inventory.models import (
    AssetValueAdjustment,
    DepreciationRun,
    FixedAssetRegisterEntry,
    InspectionCertificate,
    Item,
    Location,
    StockAllocation,
    StockEntry,
    StockRegister,
)
from notifications.models import NotificationEvent, UserNotification


class DemoPopulationApiTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="ams-demo-populate-")
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.admin = User.objects.create_superuser(
            username="seed.admin",
            email="seed.admin@example.com",
            password="pw",
        )

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def test_populate_demo_data_creates_cross_module_records_via_api(self):
        config = PopulateConfig(
            tag="TDD-DEMO",
            role_count=4,
            standalone_units=2,
            child_locations_per_unit=1,
            internal_stores_per_unit=1,
            fixed_asset_parent_count=4,
            consumable_parent_count=2,
            perishable_parent_count=1,
            item_count=12,
            person_count=4,
            user_count=4,
            completed_root_inspections=1,
            completed_department_inspections=1,
            finance_review_inspections=1,
            central_register_inspections=1,
            draft_inspections=1,
            manual_person_allocations=1,
            manual_location_allocations=1,
            manual_returns=1,
            depreciation_run_count=3,
            asset_adjustments=1,
            user_password="SeedPass123!",
        )

        summary = populate_demo_data(self.admin, config)

        self.assertEqual(summary["tag"], "TDD-DEMO")
        self.assertEqual(summary["seeded_user_password"], "SeedPass123!")
        self.assertGreaterEqual(summary["locations_created"], 7)
        self.assertGreaterEqual(summary["categories_created"], 12)
        self.assertGreaterEqual(summary["items_created"], 12)
        self.assertGreaterEqual(summary["users_created"], 4)
        self.assertGreaterEqual(summary["inspections_created"], 5)
        self.assertGreaterEqual(summary["stock_entries_created"], 4)
        self.assertGreaterEqual(summary["fixed_assets_created"], 1)
        self.assertGreaterEqual(summary["depreciation_runs_created"], 2)
        self.assertGreaterEqual(summary["notification_events_created"], 1)

        self.assertTrue(Location.objects.filter(name__icontains="Tdd Demo").exists())
        self.assertTrue(Item.objects.filter(name__icontains="TDD").exists())
        self.assertEqual(InspectionCertificate.objects.filter(contract_no__startswith="TDD-DEMO-").count(), 5)
        self.assertTrue(StockRegister.objects.filter(register_number__icontains="TDDD").exists())
        self.assertTrue(StockEntry.objects.filter(entry_type="ISSUE").exists())
        self.assertTrue(FixedAssetRegisterEntry.objects.filter(source_inspection__contract_no__startswith="TDD-DEMO-").exists())
        self.assertTrue(DepreciationRun.objects.exists())
        self.assertTrue(AssetValueAdjustment.objects.exists())
        self.assertTrue(StockAllocation.objects.exists())
        self.assertTrue(NotificationEvent.objects.exists())
        self.assertTrue(UserNotification.objects.exists())

    def test_management_command_accepts_count_overrides(self):
        out = StringIO()

        call_command(
            "populate_demo_via_api",
            username="seed.admin",
            tag="CMD-DEMO",
            role_count=2,
            standalone_units=1,
            child_locations_per_unit=1,
            internal_stores_per_unit=1,
            fixed_asset_parent_count=2,
            consumable_parent_count=1,
            perishable_parent_count=1,
            item_count=8,
            person_count=2,
            user_count=2,
            completed_root_inspections=1,
            completed_department_inspections=0,
            finance_review_inspections=0,
            central_register_inspections=0,
            draft_inspections=1,
            manual_person_allocations=0,
            manual_location_allocations=0,
            manual_returns=0,
            depreciation_run_count=3,
            asset_adjustments=0,
            user_password=DEFAULT_DEMO_PASSWORD,
            stdout=out,
        )

        output = out.getvalue()
        self.assertIn("CMD-DEMO", output)
        self.assertIn("Seeded user password", output)
        self.assertEqual(InspectionCertificate.objects.filter(contract_no__startswith="CMD-DEMO-").count(), 2)
        self.assertEqual(User.objects.filter(username__startswith="cmddemo.user").count(), 2)
