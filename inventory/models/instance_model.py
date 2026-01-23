
from django.db import models
from django.contrib.auth.models import User
from .item_model import Item
from .batch_model import ItemBatch
from .location_model import Location

class InstanceStatus(models.TextChoices):
    AVAILABLE = 'AVAILABLE', 'Available'
    ISSUED = 'ISSUED', 'Issued'
    ALLOCATED = 'ALLOCATED', 'Allocated'
    IN_USE = 'IN_USE', 'In Use'
    MAINTENANCE = 'MAINTENANCE', 'In Maintenance'
    JUNK = 'JUNK', 'Junked/Disposed'
    LOST = 'LOST', 'Lost'

class ItemInstance(models.Model):
    """
    Individual tracked unit of an Item.
    """
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='instances')
    batch = models.ForeignKey(ItemBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name='instances')
    
    serial_number = models.CharField(max_length=100, unique=True, null=True, blank=True)
    qr_code = models.CharField(max_length=255, unique=True, null=True, blank=True)
    
    current_location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name='instances')
    status = models.CharField(max_length=20, choices=InstanceStatus.choices, default=InstanceStatus.AVAILABLE)
    
    # Metadata
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.item.name} ({self.serial_number or self.id})"
