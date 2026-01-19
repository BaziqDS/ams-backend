from django.db import models
from django.contrib.auth.models import User

class Item(models.Model):
    """
    Items can be linked to either broader categories or sub-categories.
    Tracking type is inherited from the category hierarchy.

    Note: Validation allows items to be created under both broader categories
    and sub-categories for maximum flexibility.
    """
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50, unique=True)
    category = models.ForeignKey(
        'Category',
        on_delete=models.PROTECT,
        related_name='items',
        help_text="Can be either a broader category or sub-category"
    )
    description = models.TextField(blank=True, null=True)
    acct_unit = models.CharField(max_length=255, help_text="Accounting unit/measurement")
    specifications = models.TextField(blank=True, null=True)

    # NEW: Tracking fields based on category
    total_quantity = models.PositiveIntegerField(default=0)

    # NOTE: Expiry/maintenance fields removed from Item model
    # - Expiry date: Now tracked per batch in ItemBatch model
    # - Maintenance: Now tracked per instance in ItemInstance model (vendor-specific)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_items'
    )

