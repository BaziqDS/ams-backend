from django.db import models
from django.contrib.auth.models import User
from django.contrib.postgres.search import SearchVectorField


class Item(models.Model):
    """
    Items must be linked to sub-categories (leaf nodes).
    Tracking type (Individual vs Quantity) is inherited from the category hierarchy.
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
    is_provisional = models.BooleanField(
        default=False,
        help_text="Hidden from the catalog until the owning inspection certificate is completed.",
    )
    provisional_inspection = models.ForeignKey(
        'InspectionCertificate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='provisional_items',
        help_text="Inspection workflow that owns this provisional item until completion.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_items'
    )

    # ---- Hybrid copilot search (agent-only Central Register linking) ----
    # Populated by inventory.signals on Item save and consumed by
    # inventory.services.item_search.hybrid_search_items. Only used for the
    # agent's copilot-search endpoint; the human-facing dropdown still uses
    # the standard keyword search_fields filter.
    #
    # The `embedding` column is Postgres-only (pgvector). It is NOT declared
    # as a Django field because that would force every INSERT to bind a value
    # for it, breaking on SQLite where the column doesn't exist. The signal
    # writes to it via raw SQL after gating on connection.vendor.
    search_text = SearchVectorField(
        null=True,
        blank=True,
        help_text=(
            "Weighted Postgres tsvector for BM25-style ranking. Maintained "
            "by the post_save signal. Unused on SQLite."
        ),
    )
    embedded_text_hash = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text=(
            "SHA-256 of the text that produced the current embedding. Used "
            "to skip redundant re-embeds on no-op saves."
        ),
    )

    class Meta:
        permissions = [
            ("view_items", "Can view items module"),
            ("create_items", "Can create items module records"),
            ("edit_items", "Can edit items module records"),
            ("delete_items", "Can delete items module records"),
        ]
        # The hybrid-search indexes (GIN on search_text, HNSW on embedding) are
        # Postgres-only and created manually inside migration 0057 via raw SQL
        # that's gated on connection.vendor == 'postgresql'. Declaring them
        # here would make Django emit Postgres-specific DDL on SQLite migrate.

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
