from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.contrib.auth.models import User
from django.utils import timezone

from .location_model import Location
from .item_model import Item
from .batch_model import ItemBatch
from .instance_model import ItemInstance
from .person_model import Person

class StockEntry(models.Model):
    ENTRY_TYPE_CHOICES = [
        ('RECEIPT', 'Receipt'),
        ('ISSUE', 'Issue'),
        ('RETURN', 'Return'),
    ]

    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PENDING_ACK', 'Pending Acknowledgment'),
        ('COMPLETED', 'Completed'),
        ('REJECTED', 'Rejected'),
        ('CANCELLED', 'Cancelled'),
    ]

    REFERENCE_PURPOSE_CHOICES = [
        ('AUTO_RECEIPT', 'Auto Receipt'),
        ('REJECTION_RETURN', 'Rejection Return'),
        ('REVERSAL', 'Reversal'),
        ('ADDITIONAL_MOVEMENT', 'Additional Movement'),
        ('REPLACEMENT', 'Replacement'),
        ('ADJUSTMENT', 'Adjustment'),
    ]
    
    entry_type = models.CharField(max_length=20, choices=ENTRY_TYPE_CHOICES, db_index=True)
    entry_number = models.CharField(max_length=50, unique=True, blank=True)
    entry_date = models.DateTimeField(default=timezone.now)
    from_location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='outgoing_entries',
        help_text="Source location. Must be a store for ISSUE/RECEIPT, can be non-store for RETURN"
    )
    to_location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='incoming_entries',
        help_text="Destination location. Must be a store for RETURN, can be non-store for ISSUE"
    )
    
    issued_to = models.ForeignKey(
        Person,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_entries',
        help_text="Person receiving the items if issued to a person."
    )
    
    reference_entry = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='correction_entries'
    )
    reference_purpose = models.CharField(
        max_length=30,
        choices=REFERENCE_PURPOSE_CHOICES,
        null=True,
        blank=True,
        db_index=True,
        help_text="Internal reason this entry references another entry."
    )
    
    inspection_certificate = models.ForeignKey(
        'InspectionCertificate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stock_entries'
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT', db_index=True)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='created_entries'
    )
    acknowledged_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='acknowledged_entries'
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    remarks = models.TextField(blank=True, null=True)
    purpose = models.CharField(max_length=255, blank=True, null=True)
    
    cancellation_reason = models.TextField(blank=True, null=True)
    cancelled_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cancelled_entries'
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def delete(self, *args, **kwargs):
        if self.status != 'DRAFT':
            raise ValidationError("Only DRAFT entries can be deleted. Cancel instead to maintain an audit trail.")
        super().delete(*args, **kwargs)

    def clean(self):
        super().clean()
        
        # 1. Hierarchical Movement Validation (Store-to-Store)
        if self.from_location and self.to_location and self.from_location.is_store and self.to_location.is_store:
            if self.from_location_id == self.to_location_id:
                raise ValidationError("Destination cannot be the same as the source store.")

            if self.from_location.hierarchy_level == 1:
                if self.to_location.hierarchy_level != 2 or not self.to_location.is_main_store:
                    raise ValidationError("Central Store can only issue to standalone main stores.")
            else:
                source_standalone = self.from_location.get_parent_standalone()
                target_standalone = self.to_location.get_parent_standalone()
                source_main_store = source_standalone.get_main_store() if source_standalone else None
                is_source_main_store = bool(source_main_store and source_main_store.id == self.from_location_id)

                if not source_standalone or not target_standalone:
                    raise ValidationError("Store transfers must stay within a valid standalone scope.")

                if is_source_main_store:
                    is_to_central = self.to_location.hierarchy_level == 1
                    is_same_scope_regular_store = target_standalone == source_standalone and not self.to_location.is_main_store
                    if not (is_to_central or is_same_scope_regular_store):
                        raise ValidationError("Main stores can only issue to Central Store or regular stores in their own standalone location.")
                else:
                    is_to_own_main_store = bool(source_main_store and self.to_location_id == source_main_store.id)
                    is_same_scope_regular_store = target_standalone == source_standalone and not self.to_location.is_main_store
                    if not (is_to_own_main_store or is_same_scope_regular_store):
                        raise ValidationError("Regular stores can only issue to their own main store or peer stores in the same standalone location.")

        # 2. Allocation Scope Validation (Issuance to Use)
        if self.entry_type == 'ISSUE' and (self.issued_to or (self.to_location and not self.to_location.is_store)):
            if self.created_by and hasattr(self.created_by, 'profile'):
                profile = self.created_by.profile
                if profile.power_level > 0: # Non-Global (Tier 1/2)
                    source_standalone = self.from_location.get_parent_standalone() if self.from_location else None
                    if not source_standalone:
                        raise ValidationError("Source store must belong to a Department for departmental allocations.")
                        
                    if self.issued_to:
                        # Check person department matches standalone name
                        if self.issued_to.department and self.issued_to.department != source_standalone.name:
                            raise ValidationError(f"Cannot allocate to {self.issued_to.name}. They belong to {self.issued_to.department}, not {source_standalone.name}.")
                    
                    if self.to_location and not self.to_location.is_store:
                        # Check target location is in same standalone unit
                        target_standalone = self.to_location.get_parent_standalone()
                        if target_standalone != source_standalone:
                            raise ValidationError(f"Target location {self.to_location.name} is not in the same department as the source store.")

    def generate_entry_number(self):
        """
        Generates a unique entry number: SE-YYYYMMDD-XXXX
        """
        prefix = 'SE'
        date_str = timezone.now().strftime('%Y%m%d')
        last_entry = StockEntry.objects.all().order_by('-id').first()
        next_id = (last_entry.id + 1) if last_entry else 1
        return f"{prefix}-{date_str}-{next_id:04d}"

    class Meta:
        permissions = [
            ("view_stock_entries", "Can view stock entries module"),
            ("create_stock_entries", "Can create stock entries module records"),
            ("edit_stock_entries", "Can edit stock entries module records"),
            ("delete_stock_entries", "Can delete stock entries module records"),
            ("acknowledge_stockentry", "Can acknowledge stock receipt entries"),
            ("approve_stock_corrections", "Can approve stock entry corrections and reversals"),
        ]

    def save(self, *args, **kwargs):
        if not self.entry_number:
            self.entry_number = self.generate_entry_number()
        super().save(*args, **kwargs)

class StockEntryItem(models.Model):
    stock_entry = models.ForeignKey(StockEntry, on_delete=models.CASCADE, related_name='items')
    item = models.ForeignKey(Item, on_delete=models.PROTECT, db_index=True)
    batch = models.ForeignKey(ItemBatch, on_delete=models.PROTECT, null=True, blank=True, db_index=True)
    instances = models.ManyToManyField(ItemInstance, blank=True, related_name='stock_entry_items')
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    
    # Stock register reference fields
    stock_register = models.ForeignKey(
        'StockRegister', on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='source_items',
        help_text="The register this entry was recorded in (source/sender side)."
    )
    page_number = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Page number in the source stock register."
    )
    ack_stock_register = models.ForeignKey(
        'StockRegister', on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='dest_items',
        help_text="The register this entry was recorded in (destination/receiver side, filled at acknowledgment)."
    )
    ack_page_number = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Page number in the destination stock register (filled at acknowledgment)."
    )
    accepted_quantity = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Quantity accepted by the destination during acknowledgment. Original quantity is preserved for audit."
    )
    accepted_instances = models.ManyToManyField(
        ItemInstance,
        blank=True,
        related_name='accepted_stock_entry_items',
        help_text="Instances accepted by the destination during acknowledgment. Original instances are preserved for audit."
    )

    # Tracking flags for signals
    is_in_transit_recorded = models.BooleanField(default=False)
    is_stock_recorded = models.BooleanField(default=False)

    def clean(self):
        super().clean()
        from .stock_record_model import StockRecord
        # Check stock availability for movements out of a location
        # RELAXED per user request: We no longer block if stock is insufficient.
        # We still log the attempt or check for existence if necessary, 
        # but we don't raise ValidationError that blocks saving.
        
        if self.stock_entry.entry_type in ['ISSUE', 'TRANSFER', 'RETURN'] and self.stock_entry.from_location:
            try:
                record = StockRecord.objects.get(
                    item=self.item,
                    location=self.stock_entry.from_location,
                    batch=self.batch
                )
                # We could warn here, but per requirements we just "handle this properly" and "remove check"
                pass
            except StockRecord.DoesNotExist:
                # If no record exists, StockRecord.update_balance will create one.
                pass

    def __str__(self):
        return f"{self.item.name} x {self.quantity}"
