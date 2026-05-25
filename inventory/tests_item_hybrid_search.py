"""
Tests for the agent-only hybrid catalog search (Central Register linking).

These tests are designed to run against either Postgres or SQLite:
  - Most tests stub embed_text/hybrid_search_items so they don't need pgvector.
  - The signal dedupe test runs unconditionally.
  - The end-to-end Postgres SQL is exercised in CI where DATABASE_URL points
    at a Postgres test instance; on SQLite it short-circuits cleanly via
    item_search.is_supported() returning False.
"""

from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from inventory.models import Category, CategoryType, Item, TrackingType
from inventory.services import item_search
from inventory.services.embeddings import (
    build_item_embedding_text,
    build_query_text,
    hash_text,
)


# ---------------------------------------------------------------------------
# Pure unit tests — text construction & hashing
# ---------------------------------------------------------------------------

class EmbeddingTextShapeTests(TestCase):
    """Indexed text and query text must share the same labelled shape."""

    def test_item_text_includes_labelled_fields(self):
        parent = Category.objects.create(
            name="Hardware",
            category_type=CategoryType.FIXED_ASSET,
        )
        leaf = Category.objects.create(
            name="Processors",
            parent_category=parent,
            category_type=CategoryType.FIXED_ASSET,
            tracking_type=TrackingType.INDIVIDUAL,
        )
        item = Item.objects.create(
            name="Intel 10th Gen Dual-Core CPU",
            code="ITM-9001",
            category=leaf,
            description="Desktop processor, 4GHz boost, 4MB cache, LGA1200",
            specifications="65W TDP",
            acct_unit="piece",
        )
        text = build_item_embedding_text(item)
        self.assertIn("NAME: Intel 10th Gen Dual-Core CPU", text)
        self.assertIn("CODE: ITM-9001", text)
        self.assertIn("CATEGORY: Hardware / Processors", text)
        self.assertIn("DESCRIPTION: Desktop processor", text)
        self.assertIn("SPECIFICATIONS: 65W TDP", text)
        self.assertIn("UNIT: piece", text)

    def test_query_text_uses_same_shape_as_item_text(self):
        q = build_query_text(
            name="Pentium G6400",
            description="Desktop dual-core processor, 4 GHz, 4 MB cache, LGA-1200",
            specifications="65 watt",
        )
        self.assertTrue(q.startswith("NAME: Pentium G6400"))
        self.assertIn("DESCRIPTION:", q)
        self.assertIn("SPECIFICATIONS:", q)

    def test_hash_stable_for_identical_text(self):
        self.assertEqual(hash_text("a"), hash_text("a"))
        self.assertNotEqual(hash_text("a"), hash_text("b"))


# ---------------------------------------------------------------------------
# Signal dedupe — re-embed only when input fields change
# ---------------------------------------------------------------------------

@override_settings(ITEM_SEARCH_HYBRID_ENABLED=True)
class ItemPostSaveSignalTests(TestCase):
    def _make_item(self, **kwargs):
        parent = Category.objects.create(
            name="Hardware",
            category_type=CategoryType.FIXED_ASSET,
        )
        leaf = Category.objects.create(
            name="Processors",
            parent_category=parent,
            category_type=CategoryType.FIXED_ASSET,
            tracking_type=TrackingType.INDIVIDUAL,
        )
        defaults = {
            "name": "Test CPU",
            "code": "ITM-T001",
            "category": leaf,
            "description": "desc",
            "acct_unit": "piece",
        }
        defaults.update(kwargs)
        return Item.objects.create(**defaults)

    @patch("inventory.signals._has_embedding", return_value=True)
    @patch("inventory.signals._write_embedding")
    @patch("inventory.signals.embed_item")
    @patch("inventory.signals._refresh_tsvector")
    @patch("inventory.signals.connection")
    def test_no_reembed_when_irrelevant_field_changes(
        self, mock_conn, mock_refresh, mock_embed, mock_write, mock_has,
    ):
        # Force the SQLite test run to look like Postgres so the signal body
        # executes. The actual DB writes are mocked out.
        mock_conn.vendor = "postgresql"

        class _FakeResult:
            text = "T"
            text_hash = "stable-hash"
            vector = [0.0]
            error = None

        mock_embed.return_value = _FakeResult()

        item = self._make_item()
        # Initial save triggered one embed call.
        self.assertEqual(mock_embed.call_count, 1)

        # Simulate that the hash got persisted.
        Item.objects.filter(pk=item.pk).update(embedded_text_hash="stable-hash")
        item.refresh_from_db()

        # Now save again touching nothing that matters.
        with patch(
            "inventory.signals.build_item_embedding_text",
            return_value="T",
        ):
            with patch(
                "inventory.signals.hash_text",
                return_value="stable-hash",
            ):
                item.save()

        # Should not have re-embedded — hash match + _has_embedding=True.
        self.assertEqual(mock_embed.call_count, 1)


# ---------------------------------------------------------------------------
# Endpoint guard — feature flag and DB vendor short-circuit cleanly
# ---------------------------------------------------------------------------

class CopilotSearchEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="copilot_search_user", password="pw",
        )
        self.user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="inventory",
                codename="view_items",
            )
        )
        self.client.force_authenticate(user=self.user)

    @override_settings(ITEM_SEARCH_HYBRID_ENABLED=False)
    def test_returns_disabled_when_flag_off(self):
        resp = self.client.post(
            "/api/inventory/items/copilot-search/",
            {"item_name": "Core i6", "item_description": "HP 6th gen"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["enabled"])
        self.assertEqual(body["hits"], [])
        self.assertEqual(body["reason"], "hybrid_search_not_supported")

    @override_settings(ITEM_SEARCH_HYBRID_ENABLED=True)
    @patch("inventory.services.item_search.connection")
    def test_returns_disabled_on_sqlite_even_when_flag_on(self, mock_conn):
        mock_conn.vendor = "sqlite"
        resp = self.client.post(
            "/api/inventory/items/copilot-search/",
            {"item_name": "Core i6"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["enabled"])

    @override_settings(ITEM_SEARCH_HYBRID_ENABLED=True)
    @patch("inventory.services.item_search.is_supported", return_value=True)
    @patch("inventory.services.item_search.hybrid_search_items")
    def test_returns_hits_with_signals_when_supported(
        self, mock_search, _mock_supported,
    ):
        mock_search.return_value = [
            item_search.ItemHit(
                id=42,
                name="Intel 10th Gen Dual-Core CPU",
                code="ITM-9001",
                category_id=7,
                category_display="Hardware / Processors",
                category_type=CategoryType.FIXED_ASSET,
                tracking_type=TrackingType.INDIVIDUAL,
                description="Desktop processor, 4GHz, 4MB cache, LGA1200",
                specifications="65W TDP",
                acct_unit="piece",
                rrf_score=0.0282,
                signals=["semantic_rank=1", "bm25_rank=25",
                         "tracking_match", "category_match"],
            ),
        ]

        resp = self.client.post(
            "/api/inventory/items/copilot-search/",
            {
                "item_name": "Pentium G6400",
                "item_description": "HP 6th gen processor",
                "item_tracking_type": TrackingType.INDIVIDUAL,
                "item_category_type": CategoryType.FIXED_ASSET,
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["enabled"])
        self.assertEqual(len(body["hits"]), 1)
        hit = body["hits"][0]
        self.assertEqual(hit["id"], 42)
        self.assertIn("semantic_rank=1", hit["signals"])
        self.assertIn("tracking_match", hit["signals"])
        self.assertEqual(hit["score"], 0.0282)
