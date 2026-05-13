from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from inventory.models import (
    Category,
    CategoryType,
    CorrectionStatus,
    StockCorrectionRequest,
    StockEntry,
    TrackingType,
    Item,
)
from inventory.serializers.stockentry_serializer import StockEntrySerializer
from inventory.views.item_views import ItemViewSet


class ItemListPerformanceTests(TestCase):
    def test_standalone_count_context_is_limited_to_paginated_page(self):
        parent = Category.objects.create(
            name="Performance Consumables",
            code="PERF-CONS",
            category_type=CategoryType.CONSUMABLE,
        )
        child = Category.objects.create(
            name="Performance Consumables Leaf",
            code="PERF-CONS-L",
            parent_category=parent,
            tracking_type=TrackingType.QUANTITY,
        )
        Item.objects.bulk_create(
            [
                Item(
                    name=f"Performance Item {idx:03d}",
                    code=f"PERF-ITEM-{idx:03d}",
                    category=child,
                    acct_unit="pcs",
                )
                for idx in range(101)
            ]
        )
        user = User.objects.create_superuser(
            username="item.performance.admin",
            email="item.performance@example.com",
            password="pw",
        )
        client = APIClient()
        client.force_authenticate(user=user)

        captured_item_ids = []

        def capture_counts(_view, item_ids):
            captured_item_ids.append(list(item_ids))
            return {}

        with patch.object(ItemViewSet, "_build_standalone_location_counts", capture_counts):
            response = client.get("/api/inventory/items/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(captured_item_ids), 1)
        self.assertEqual(len(captured_item_ids[0]), 100)


class StockEntrySerializerPrefetchPerformanceTests(TestCase):
    def test_correction_fields_use_prefetched_data_without_extra_queries(self):
        original = StockEntry.objects.create(entry_type="ISSUE", status="COMPLETED")
        generated = StockEntry.objects.create(entry_type="RETURN", status="COMPLETED")
        replacement = StockEntry.objects.create(
            entry_type="ISSUE",
            status="COMPLETED",
            reference_entry=original,
            reference_purpose="REPLACEMENT",
        )
        correction = StockCorrectionRequest.objects.create(
            original_entry=original,
            status=CorrectionStatus.REQUESTED,
            reason="Correct quantity",
        )
        correction.generated_entries.add(generated)

        original._prefetched_correction_requests = [correction]
        original._prefetched_generated_correction_entries = [generated]
        original._prefetched_replacement_entries = [replacement]

        serializer = StockEntrySerializer(context={})
        with self.assertNumQueries(0):
            self.assertEqual(serializer.get_active_correction(original)["id"], correction.id)
            self.assertEqual(serializer.get_correction_status(original), CorrectionStatus.REQUESTED)
            self.assertEqual(
                [entry["id"] for entry in serializer.get_generated_correction_entries(original)],
                [generated.id],
            )
            self.assertEqual(serializer.get_replacement_entry(original)["id"], replacement.id)
