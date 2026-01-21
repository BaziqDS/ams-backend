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
    
    quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['item', 'batch', 'location']]

    def __str__(self):
        batch_str = f" - Batch {self.batch.batch_number}" if self.batch else ""
        return f"{self.item.name}{batch_str} @ {self.location.name}: {self.quantity}"

    @classmethod
    def update_balance(cls, item, location, quantity_change, batch=None):
        """
        Helper method to increment/decrement stock.
        """
        record, created = cls.objects.get_or_create(
            item=item,
            location=location,
            batch=batch,
            defaults={'quantity': 0}
        )
        
        new_quantity = record.quantity + quantity_change
        if new_quantity < 0:
            logger.warning(f"Attempted to set negative quantity for {item.name} at {location.name}")
            new_quantity = 0
            
        record.quantity = new_quantity
        record.save()
        return record

import logging
logger = logging.getLogger(__name__)

