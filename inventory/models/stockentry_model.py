from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.contrib.auth.models import User
from django.utils import timezone

from .inspection import InspectionCertificate
from .item_instance import ItemInstance
from .category import TrackingType
from .location import Location
from .item import Item, ItemBatch, ConsumableInventory, StockAllocation

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
        # Note: Removed limit_choices_to={'is_store': True} to support RETURN from non-store locations
    )
    to_location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='incoming_entries',
        help_text="Destination location. Must be a store for RETURN, can be non-store for ISSUE"
    )
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    
    
    reference_entry = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='correction_entries'
    )

    inspection_certificate = models.ForeignKey(
        InspectionCertificate, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='stock_entries'
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
