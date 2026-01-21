from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)

class TrackingType(models.TextChoices):
    INDIVIDUAL = 'INDIVIDUAL', 'Individual Tracking (Serial/QR)'
    BATCH = 'BATCH', 'Batch Tracking (FIFO/Expiry)'

class CategoryType(models.TextChoices):
    FIXED_ASSET = 'FIXED_ASSET', 'Fixed Asset'
    CONSUMABLE = 'CONSUMABLE', 'Consumable'
    PERISHABLE = 'PERISHABLE', 'Perishable'

class Category(models.Model):
    """
    Refined Category model with inheritance:
    - category_type: Set at parent, can be overridden.
    - tracking_type: Set at subcategory level.
    - default_depreciation_rate: Set at parent, inherited by Fixed Asset subcategories.
    """
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=20, unique=True, blank=True)
    
    parent_category = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True, 
        related_name='subcategories'
    )

    category_type = models.CharField(
        max_length=20, choices=CategoryType.choices, null=True, blank=True,
        help_text="Financial nature. Set at parent level, can be overridden."
    )
    
    tracking_type = models.CharField(
        max_length=20, choices=TrackingType.choices, null=True, blank=True,
        help_text="Operational nature. Assigned at subcategory level."
    )

    default_depreciation_rate = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="Assigned at parent level for Fixed Assets. Inherited by subcategories."
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Categories'
        unique_together = [['parent_category', 'name']]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def get_category_type(self):
        if self.category_type:
            return self.category_type
        if self.parent_category:
            return self.parent_category.get_category_type()
        return None

    def get_tracking_type(self):
        # User specified tracking is assigned at subcategory level
        return self.tracking_type

    def get_depreciation_rate(self):
        # Only fixed assets have depreciation
        if self.get_category_type() != CategoryType.FIXED_ASSET:
            return Decimal('0.00')
        
        # Use local rate if provided
        if self.default_depreciation_rate is not None:
            return self.default_depreciation_rate
            
        # Otherwise inherit from parent
        if self.parent_category:
            return self.parent_category.get_depreciation_rate()
            
        return Decimal('0.00')

    def get_rate_at_date(self, target_date):
        """
        Resolves the depreciation rate active at a specific point in time.
        1. Checks local history records.
        2. If none, recurses to parent history.
        """
        # 1. Local History Check
        history = self.rate_history.filter(changed_at__lte=target_date).order_by('-changed_at').first()
        if history:
            return history.rate
            
        # 2. Inheritance Check
        if self.parent_category:
            return self.parent_category.get_rate_at_date(target_date)
            
        # 3. Fallback to current rate (or 0)
        return self.get_depreciation_rate()

    def is_fixed_asset(self):
        return self.get_category_type() == CategoryType.FIXED_ASSET

    def clean(self):
        super().clean()
        if self.parent_category and self.parent_category.parent_category:
            raise ValidationError("Only 2-level category hierarchy is allowed")
        
        # Case 1: Top-level Parent
        if not self.parent_category:
            if not self.category_type:
                raise ValidationError("Top-level categories must define a Category Type (Fixed Asset or Consumable)")
            
        # Case 2: Subcategory
        else:
            if not self.tracking_type:
                raise ValidationError("Subcategories must define a Tracking Type (Individual or Batch)")
            
            # Compatibility Check: No Fixed Asset under Consumable parent
            if self.category_type == CategoryType.FIXED_ASSET and self.parent_category.get_category_type() == CategoryType.CONSUMABLE:
                raise ValidationError("A Fixed Asset subcategory cannot be created under a Consumable parent category.")

        # Generic depreciation rule
        if self.default_depreciation_rate and not self.is_fixed_asset():
            raise ValidationError("Depreciation rate can only be assigned to Fixed Assets")

    def save(self, *args, **kwargs):
        request_user = kwargs.pop('request_user', None)
        audit_notes = kwargs.pop('audit_notes', None)
        
        is_new = self.pk is None
        old_rate = None
        
        if not is_new:
            try:
                # Use a fresh query to avoid cached instance issues
                old_instance = Category.objects.get(pk=self.pk)
                old_rate = old_instance.default_depreciation_rate
            except Category.DoesNotExist:
                pass

        if not self.code:
            prefix = "CAT" if not self.parent_category else "SUB"
            last = Category.objects.order_by('-id').first()
            seq = (last.id + 1) if last else 1
            self.code = f"{prefix}-{seq:04d}"
            
        super().save(*args, **kwargs)

        # Logic: If rate changed, log it.
        # If new item and rate is set, log it as initial rate.
        rate_changed = is_new or (old_rate != self.default_depreciation_rate)
        
        if rate_changed and self.default_depreciation_rate is not None:
            final_notes = audit_notes
            if not final_notes:
                final_notes = "Initial rate set" if is_new else f"Rate updated from {old_rate} to {self.default_depreciation_rate}"
                
            CategoryRateHistory.objects.create(
                category=self,
                rate=self.default_depreciation_rate,
                changed_by=request_user,
                notes=final_notes
            )

class CategoryRateHistory(models.Model):
    """
    Audit table to track how depreciation rates changed over time.
    Ensures that if anyone asks 'What was the rate in 2023?', we have the answer.
    """
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='rate_history')
    rate = models.DecimalField(max_digits=5, decimal_places=2)
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-changed_at']