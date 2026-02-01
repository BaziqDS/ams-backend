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
    ]

    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PENDING_ACK', 'Pending Acknowledgment'),
        ('COMPLETED', 'Completed'),
        ('PARTIALLY_ACCEPTED', 'Partially Accepted'),
        ('REJECTED', 'Rejected'),
        ('CANCELLED', 'Cancelled'),
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
            level_from = self.from_location.hierarchy_level
            level_to = self.to_location.hierarchy_level
            
            # L1 Rules
            if level_from == 1:
                if level_to != 2:
                    raise ValidationError("L1 Store (Central) can only issue to L2 Stores (Department Stores).")
            
            # L2 Rules
            elif level_from == 2:
                is_return_to_l1 = (level_to == 1)
                is_issue_to_l3_child = (level_to == 3 and self.to_location.parent_location == self.from_location)
                if not (is_return_to_l1 or is_issue_to_l3_child):
                    raise ValidationError("L2 Store can only return to L1 or issue to its direct L3 Sub-Stores.")
            
            # L3 Rules
            elif level_from == 3:
                is_return_to_l2_parent = (level_to == 2 and self.from_location.parent_location == self.to_location)
                if not is_return_to_l2_parent:
                    raise ValidationError("L3 Store can only return to its parent L2 Store.")

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
            ("acknowledge_stockentry", "Can acknowledge stock receipt entries"),
        ]

    def save(self, *args, **kwargs):
        if not self.entry_number:
            self.entry_number = self.generate_entry_number()
        super().save(*args, **kwargs)

class StockEntryItem(models.Model):
    stock_entry = models.ForeignKey(StockEntry, on_delete=models.CASCADE, related_name='items')
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    batch = models.ForeignKey(ItemBatch, on_delete=models.PROTECT, null=True, blank=True)
    instances = models.ManyToManyField(ItemInstance, blank=True, related_name='stock_entry_items')
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    
    # Tracking flags for signals
    is_in_transit_recorded = models.BooleanField(default=False)
    is_stock_recorded = models.BooleanField(default=False)

    def clean(self):
        super().clean()
        from .stock_record_model import StockRecord
        # Check stock availability for movements out of a location
        if self.stock_entry.entry_type in ['ISSUE', 'TRANSFER', 'RETURN'] and self.stock_entry.from_location:
            try:
                record = StockRecord.objects.get(
                    item=self.item,
                    location=self.stock_entry.from_location,
                    batch=self.batch
                )
                if record.available_quantity < self.quantity:
                    raise ValidationError(
                        f"Insufficient available stock for {self.item.name}. "
                        f"Physical Total: {record.quantity}, In Transit: {record.in_transit_quantity}, "
                        f"Available: {record.available_quantity}, Requested: {self.quantity}"
                    )
            except StockRecord.DoesNotExist:
                raise ValidationError(f"No stock record found for {self.item.name} at the source location.")

    def __str__(self):
        return f"{self.item.name} x {self.quantity}"
