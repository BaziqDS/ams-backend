from django.db import models
from django.contrib.auth.models import User
from .item_model import Item

class ItemBatch(models.Model):
    """
    Groups quantity-tracked perishable items received together.
    """
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='batches')
    batch_number = models.CharField(max_length=100)
    manufactured_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name_plural = 'Item Batches'
        unique_together = [['item', 'batch_number']]

    def __str__(self):
        return f"{self.item.name} - Batch {self.batch_number}"
