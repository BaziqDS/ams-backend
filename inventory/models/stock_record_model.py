from django.db import models
from django.core.validators import MinValueValidator
from .item_model import Item
from .batch_model import ItemBatch
from .location_model import Location

class StockRecord(models.Model):
    """
    Current balance of an Item (and optionally Batch) at a specific Location.
    Summary table for quick inventory lookups.
    """
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='stock_records')
    batch = models.ForeignKey(ItemBatch, on_delete=models.CASCADE, null=True, blank=True, related_name='stock_records')
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='stock_records')
    
    quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)], help_text="Total physical stock held at this location")
    in_transit_quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)], help_text="Stock in-transit from here to another store")
    allocated_quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)], help_text="Stock allocated to persons or non-store locations")
    
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['item', 'batch', 'location']]

    def __str__(self):
        batch_str = f" - Batch {self.batch.batch_number}" if self.batch else ""
        return f"{self.item.name}{batch_str} @ {self.location.name}: {self.quantity} (Alloc: {self.allocated_quantity}, Transit: {self.in_transit_quantity})"

    @property
    def available_quantity(self):
        """
        Stock available for new issues/transfers.
        """
        return max(0, self.quantity - self.in_transit_quantity - self.allocated_quantity)

    @classmethod
    def update_balance(cls, item, location, quantity_change=0, batch=None, in_transit_change=0, allocated_change=0):
        """
        Helper method to increment/decrement quantities.
        """
        record, created = cls.objects.get_or_create(
            item=item,
            location=location,
            batch=batch,
            defaults={'quantity': 0, 'in_transit_quantity': 0, 'allocated_quantity': 0}
        )
        
        if quantity_change:
            record.quantity = max(0, record.quantity + quantity_change)

        if in_transit_change:
            record.in_transit_quantity = max(0, record.in_transit_quantity + in_transit_change)

        if allocated_change:
            record.allocated_quantity = max(0, record.allocated_quantity + allocated_change)
            
        record.save()
        return record


import logging
logger = logging.getLogger(__name__)

