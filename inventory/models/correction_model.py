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


class StockReconciliationRun(models.Model):
    MODE_CHOICES = [
        ('DRY_RUN', 'Dry Run'),
        ('APPLY', 'Apply'),
    ]
    STATUS_CHOICES = [
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]

    mode = models.CharField(max_length=20, choices=MODE_CHOICES, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='COMPLETED', db_index=True)
    reason = models.TextField(blank=True, default='')
    scope_item = models.ForeignKey('Item', on_delete=models.SET_NULL, null=True, blank=True, related_name='reconciliation_runs')
    scope_location = models.ForeignKey('Location', on_delete=models.SET_NULL, null=True, blank=True, related_name='reconciliation_runs')
    requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stock_reconciliation_runs',
    )
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    findings_count = models.PositiveIntegerField(default=0)
    applied_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"Stock reconciliation {self.id} ({self.mode})"


class StockReconciliationFinding(models.Model):
    FINDING_TYPE_CHOICES = [
        ('STOCK_RECORD_SUMMARY_MISMATCH', 'Stock record summary mismatch'),
        ('DUPLICATE_ACTIVE_INSTANCE_RESERVATION', 'Duplicate active instance reservation'),
        ('INDIVIDUAL_MOVEMENT_INSTANCE_MISMATCH', 'Individual movement instance mismatch'),
        ('QUANTITY_PENDING_OVER_ISSUE', 'Quantity pending issue exceeds source stock'),
    ]
    SEVERITY_CHOICES = [
        ('INFO', 'Info'),
        ('WARNING', 'Warning'),
        ('CRITICAL', 'Critical'),
    ]

    run = models.ForeignKey(
        StockReconciliationRun,
        on_delete=models.CASCADE,
        related_name='findings',
    )
    finding_type = models.CharField(max_length=60, choices=FINDING_TYPE_CHOICES, db_index=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='WARNING', db_index=True)
    repairable = models.BooleanField(default=False)
    applied = models.BooleanField(default=False)
    message = models.TextField()
    stock_record = models.ForeignKey('StockRecord', on_delete=models.SET_NULL, null=True, blank=True, related_name='reconciliation_findings')
    stock_entry = models.ForeignKey(StockEntry, on_delete=models.SET_NULL, null=True, blank=True, related_name='reconciliation_findings')
    stock_entry_item = models.ForeignKey(StockEntryItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='reconciliation_findings')
    item = models.ForeignKey('Item', on_delete=models.SET_NULL, null=True, blank=True, related_name='reconciliation_findings')
    location = models.ForeignKey('Location', on_delete=models.SET_NULL, null=True, blank=True, related_name='reconciliation_findings')
    item_instance = models.ForeignKey(ItemInstance, on_delete=models.SET_NULL, null=True, blank=True, related_name='reconciliation_findings')
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.finding_type} ({self.severity})"
