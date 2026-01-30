from django.db import models
from django.contrib.auth.models import User
from .item_model import Item
from .instance_model import ItemInstance
from .batch_model import ItemBatch
from .location_model import Location
from .stockentry_model import StockEntry
from .allocation_model import StockAllocation

class MovementAction(models.TextChoices):
    RECEIVE = 'RECEIVE', 'Received into Store'
    ISSUE = 'ISSUE', 'Issued/Transferred'
    ALLOCATE = 'ALLOCATE', 'Allocated to Person/Unit'
    RETURN = 'RETURN', 'Returned to Store'
    CONSUME = 'CONSUME', 'Consumed'
    JUNK = 'JUNK', 'Junked/Disposed'
    LOST = 'LOST', 'Lost'

class MovementHistory(models.Model):
    """
    Detailed audit log for every physical movement or assignment change 
    for both tracked individual units (instances) and batches.
    """
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='movements')
    instance = models.ForeignKey(ItemInstance, on_delete=models.CASCADE, null=True, blank=True, related_name='movements')
    batch = models.ForeignKey(ItemBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name='movements')
    
    action = models.CharField(max_length=20, choices=MovementAction.choices)
    
    from_location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name='outgoing_movements')
    to_location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name='incoming_movements')
    
    # Optional links to the source triggers
    stock_entry = models.ForeignKey(StockEntry, on_delete=models.SET_NULL, null=True, blank=True, related_name='movements')
    allocation = models.ForeignKey(StockAllocation, on_delete=models.SET_NULL, null=True, blank=True, related_name='movements')
    
    quantity = models.PositiveIntegerField(default=1, help_text="Number of units moved (usually 1 for instances)")
    
    performed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    remarks = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name_plural = 'Movement Histories'

    def __str__(self):
        target = self.instance.serial_number if self.instance else f"Batch {self.batch.batch_number if self.batch else 'N/A'}"
        return f"{self.action} - {self.item.name} ({target}) at {self.timestamp}"
