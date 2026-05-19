from django.contrib.auth.models import Permission, User
from django.test import TestCase
from rest_framework.test import APIClient

from inventory.models import Category, CategoryType, TrackingType


class CategoryClassificationContractTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="category_contract_editor", password="pw")
        self.user.user_permissions.add(
            Permission.objects.get(content_type__app_label="inventory", codename="edit_categories")
        )
        self.client.force_authenticate(user=self.user)

    def test_patch_rejects_top_level_category_type_change(self):
        category = Category.objects.create(
            name="Immutable Top Level Category",
            category_type=CategoryType.FIXED_ASSET,
        )

        resp = self.client.patch(
            f"/api/inventory/categories/{category.id}/",
            {"category_type": CategoryType.CONSUMABLE},
            format="json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("category_type", resp.data)
        category.refresh_from_db()
        self.assertEqual(category.category_type, CategoryType.FIXED_ASSET)

    def test_patch_rejects_subcategory_category_type_change(self):
        parent = Category.objects.create(
            name="Immutable Parent Category",
            category_type=CategoryType.FIXED_ASSET,
        )
        child = Category.objects.create(
            name="Immutable Child Category",
            parent_category=parent,
            category_type=CategoryType.FIXED_ASSET,
            tracking_type=TrackingType.INDIVIDUAL,
        )

        resp = self.client.patch(
            f"/api/inventory/categories/{child.id}/",
            {"category_type": CategoryType.PERISHABLE},
            format="json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("category_type", resp.data)
        child.refresh_from_db()
        self.assertEqual(child.category_type, CategoryType.FIXED_ASSET)
