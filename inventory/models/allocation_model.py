from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from .item_model import Item
from .batch_model import ItemBatch
from .location_model import Location
from .person_model import Person
from .stockentry_model import StockEntry

class AllocationStatus(models.TextChoices):
    ALLOCATED = 'ALLOCATED', 'Allocated'
    RETURNED = 'RETURNED', 'Returned'
    CONSUMED = 'CONSUMED', 'Consumed'

class StockAllocation(models.Model):
    """
    Tracks items issued to a person or a non-store location.
    These items are considered 'Allocated' and stay in the source store's total inventory count
    until they are either returned or consumed.
    """
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='allocations')
    batch = models.ForeignKey(ItemBatch, on_delete=models.CASCADE, null=True, blank=True)
    source_location = models.ForeignKey(
        Location, 
        on_delete=models.PROTECT, 
        related_name='outgoing_allocations',
        limit_choices_to={'is_store': True}
    )
    
    quantity = models.PositiveIntegerField()
    
    # Allocation Targets
    allocated_to_person = models.ForeignKey(
        Person, 
        on_delete=models.PROTECT, 
        null=True, 
        blank=True,
        related_name='allocations'
    )
    allocated_to_location = models.ForeignKey(
        Location, 
        on_delete=models.PROTECT, 
        null=True, 
        blank=True,
        related_name='incoming_allocations',
        limit_choices_to={'is_store': False}
    )
    
    status = models.CharField(
        max_length=20, 
        choices=AllocationStatus.choices, 
        default=AllocationStatus.ALLOCATED
    )
    
    stock_entry = models.ForeignKey(
        StockEntry, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='allocations'
    )
    
    allocated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    allocated_at = models.DateTimeField(default=timezone.now)
    
    return_date = models.DateTimeField(null=True, blank=True)
    remarks = models.TextField(blank=True, null=True)

    def __str__(self):
        target = self.allocated_to_person.name if self.allocated_to_person else self.allocated_to_location.name
        return f"{self.item.name} x {self.quantity} allocated to {target}"

    class Meta:
        ordering = ['-allocated_at']
