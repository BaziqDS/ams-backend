from django.db import models
from django.contrib.auth.models import User

class Item(models.Model):
    """
    Items must be linked to sub-categories (leaf nodes).
    Tracking type (Individual vs Batch) is inherited from the category hierarchy.
    """
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50, unique=True, blank=True)
    category = models.ForeignKey(
        'Category',
        on_delete=models.PROTECT,
        related_name='items',
        help_text="Must be a sub-category (has a parent category)"
    )
    description = models.TextField(blank=True, null=True)
    acct_unit = models.CharField(max_length=255, help_text="Accounting unit/measurement")
    specifications = models.TextField(blank=True, null=True)
    low_stock_threshold = models.PositiveIntegerField(
        default=0,
        help_text="Raise a low-stock warning when total quantity falls to or below this threshold.",
    )

    def clean(self):
        from django.core.exceptions import ValidationError
        super().clean()
        if self.category and not self.category.parent_category:
            raise ValidationError({
                'category': "Items can only be linked to sub-categories, not top-level categories."
            })

    # NOTE: Tracking fields (Total Quantity) are now dynamically calculated 
    # from StockRecord entries in the ViewSets for accuracy and security.


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

    class Meta:
        permissions = [
            ("view_items", "Can view items module"),
            ("create_items", "Can create items module records"),
            ("edit_items", "Can edit items module records"),
            ("delete_items", "Can delete items module records"),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self.generate_item_code()
        super().save(*args, **kwargs)

    def generate_item_code(self):
        # Generate a unique code if not provided
        # Format: ITM-0001
        last_item = Item.objects.order_by('-id').first()
        next_seq = (last_item.id + 1) if last_item else 1
        
        while True:
            code = f"ITM-{next_seq:04d}"
            if not Item.objects.filter(code=code).exists():
                return code
            next_seq += 1
