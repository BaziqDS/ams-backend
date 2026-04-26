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
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='closed_stock_registers',
    )
    closed_reason = models.TextField(blank=True, default="")
    reopened_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reopened_stock_registers',
    )
    reopened_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = 'Stock Register'
        verbose_name_plural = 'Stock Registers'
        unique_together = [['register_number', 'store']]
        ordering = ['-created_at']
        permissions = [
            ("view_stock_registers", "Can view stock registers module"),
            ("create_stock_registers", "Can create stock registers module records"),
            ("edit_stock_registers", "Can edit stock registers module records"),
            ("delete_stock_registers", "Can delete stock registers module records"),
            ("manage_stock_register", "Can add/edit/delete stock registers"),
        ]

    def __str__(self):
        return f"Register {self.register_number} — {self.store.name}"
