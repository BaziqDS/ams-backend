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
        ('TRANSFER', 'Transfer'),
        ('CORRECTION', 'Correction'),
        ('RETURN', 'Return'),
    ]

    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PENDING_ACK', 'Pending Acknowledgment'),
        ('COMPLETED', 'Completed'),
        ('PARTIALLY_ACCEPTED', 'Partially Accepted'),
        ('REJECTED', 'Rejected'),
        ('CANCELLED', 'Cancelled'),
    ]
    
    entry_type = models.CharField(max_length=20, choices=ENTRY_TYPE_CHOICES)
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

    # Transfer tracking
    requires_acknowledgment = models.BooleanField(default=False)
    is_cross_location = models.BooleanField(default=False)
    is_upward_transfer = models.BooleanField(
        default=False,
        help_text="True if this is a main store issuing UP to parent standalone location"
    )
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
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
    
    # NEW: Acknowledgment details for bulk items
    acknowledgment_details = models.JSONField(
        default=dict,
        blank=True,
        help_text="Details of what was accepted/rejected for bulk items"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        # Validation for Stock Availability
        if self.entry_type in ['ISSUE', 'TRANSFER'] and self.from_location:
            from .stock_record_model import StockRecord
            # Note: Since StockEntry has multiple items now, we can't easily validate 
            # the whole entry in the main clean() if the items aren't saved yet.
            # However, for single-item legacy logic or validation during save, 
            # we should move this to the StockEntryItem or Serializer.
            pass

    def generate_entry_number(self):
        """
        Generates a unique entry number: SE-YYYYMMDD-XXXX
        """
        prefix = 'SE'
        date_str = timezone.now().strftime('%Y%m%d')
        
        # Get the highest ID to ensure uniqueness in the sequence
        last_entry = StockEntry.objects.all().order_by('-id').first()
        next_id = (last_entry.id + 1) if last_entry else 1
        
        return f"{prefix}-{date_str}-{next_id:04d}"

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
                if record.quantity < self.quantity:
                    raise ValidationError(
                        f"Insufficient stock for {self.item.name}. "
                        f"Available: {record.quantity}, Requested: {self.quantity}"
                    )
            except StockRecord.DoesNotExist:
                raise ValidationError(f"No stock record found for {self.item.name} at the source location.")

        if self.item.tracking_type == 'INDIVIDUAL' and self.instances.count() != self.quantity:
            # This is still hard to enforce in clean() before M2M is saved
            pass

    def __str__(self):

        return f"{self.item.name} x {self.quantity}"

