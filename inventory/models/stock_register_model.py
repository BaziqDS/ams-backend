from django.db import models
from django.contrib.auth.models import User
from .location_model import Location


class StockRegister(models.Model):
    """
    Represents a physical stock register ledger that belongs to a specific store.
    """
    REGISTER_TYPE_CHOICES = [
        ('CSR', 'Consumable Stock Register'),
        ('DSR', 'Dead Stock Register'),
    ]

    register_number = models.CharField(max_length=100)
    register_type = models.CharField(max_length=3, choices=REGISTER_TYPE_CHOICES, default='CSR')
    store = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name='stock_registers',
        limit_choices_to={'is_store': True},
        help_text="The store this register belongs to."
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = 'Stock Register'
        verbose_name_plural = 'Stock Registers'
        unique_together = [['register_number', 'store']]
        ordering = ['-created_at']
        permissions = [
            ("manage_stock_register", "Can add/edit/delete stock registers"),
        ]

    def __str__(self):
        return f"Register {self.register_number} — {self.store.name}"
