from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from .instance_model import ItemInstance
from .stockentry_model import StockEntry, StockEntryItem


class CorrectionStatus(models.TextChoices):
    REQUESTED = 'REQUESTED', 'Requested'
    APPROVED = 'APPROVED', 'Approved'
    APPLIED = 'APPLIED', 'Applied'
    REJECTED = 'REJECTED', 'Rejected'
    BLOCKED = 'BLOCKED', 'Blocked'


class CorrectionResolutionType(models.TextChoices):
    NO_CHANGE = 'NO_CHANGE', 'No Change'
    ADDITIONAL_MOVEMENT = 'ADDITIONAL_MOVEMENT', 'Additional Movement'
    REVERSAL = 'REVERSAL', 'Reversal'
    ALLOCATION_INCREASE = 'ALLOCATION_INCREASE', 'Allocation Increase'
    ALLOCATION_REDUCTION = 'ALLOCATION_REDUCTION', 'Allocation Reduction'
    RETURN_INCREASE = 'RETURN_INCREASE', 'Return Increase'
    RETURN_REDUCTION = 'RETURN_REDUCTION', 'Return Reduction'
    ADJUSTMENT_REQUIRED = 'ADJUSTMENT_REQUIRED', 'Adjustment Required'
    MIXED = 'MIXED', 'Mixed'
    BLOCKED = 'BLOCKED', 'Blocked'


class StockCorrectionRequest(models.Model):
    """
    Contextual correction request for an existing StockEntry.
    Generated stock effects remain normal StockEntry records.
    """
    original_entry = models.ForeignKey(
        StockEntry,
        on_delete=models.PROTECT,
        related_name='correction_requests',
    )
    status = models.CharField(
        max_length=20,
        choices=CorrectionStatus.choices,
        default=CorrectionStatus.REQUESTED,
        db_index=True,
    )
    resolution_type = models.CharField(
        max_length=40,
        choices=CorrectionResolutionType.choices,
        default=CorrectionResolutionType.NO_CHANGE,
        db_index=True,
    )
    reason = models.TextField()
    message = models.TextField(blank=True, default='')
    requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='requested_stock_corrections',
    )
    requested_at = models.DateTimeField(default=timezone.now)
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_stock_corrections',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rejected_stock_corrections',
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default='')
    generated_entries = models.ManyToManyField(
        StockEntry,
        blank=True,
        related_name='generated_by_correction_requests',
    )

    class Meta:
        ordering = ['-requested_at']

    def __str__(self):
        return f"Correction for {self.original_entry.entry_number} ({self.status})"


class StockCorrectionLine(models.Model):
    correction_request = models.ForeignKey(
        StockCorrectionRequest,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    original_item = models.ForeignKey(
        StockEntryItem,
        on_delete=models.PROTECT,
        related_name='correction_lines',
    )
    original_quantity = models.PositiveIntegerField()
    corrected_quantity = models.PositiveIntegerField()
    delta = models.IntegerField()
    affected_instances = models.ManyToManyField(
        ItemInstance,
        blank=True,
        related_name='correction_lines',
    )

    class Meta:
        ordering = ['id']
