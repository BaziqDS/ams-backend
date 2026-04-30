from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class DepreciationMethod(models.TextChoices):
    WDV = "WDV", "Written Down Value"


class DepreciationRunStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    POSTED = "POSTED", "Posted"
    REVERSED = "REVERSED", "Reversed"


class FixedAssetTargetType(models.TextChoices):
    INSTANCE = "INSTANCE", "Individual Instance"
    LOT = "LOT", "Quantity Lot"


class FixedAssetStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    DISPOSED = "DISPOSED", "Disposed"
    LOST = "LOST", "Lost"
    JUNK = "JUNK", "Junked"
    INACTIVE = "INACTIVE", "Inactive"


class AssetAdjustmentType(models.TextChoices):
    ADDITION = "ADDITION", "Capital Addition"
    COST_CORRECTION = "COST_CORRECTION", "Cost Correction"
    DISPOSAL = "DISPOSAL", "Disposal"
    LOSS = "LOSS", "Loss"
    WRITE_OFF = "WRITE_OFF", "Write-off"
    QUANTITY_REDUCTION = "QUANTITY_REDUCTION", "Quantity Reduction"


class DepreciationPolicy(models.Model):
    name = models.CharField(max_length=150, unique=True, default="FBR WDV")
    method = models.CharField(max_length=20, choices=DepreciationMethod.choices, default=DepreciationMethod.WDV)
    fiscal_year_start_month = models.PositiveSmallIntegerField(default=7)
    fiscal_year_start_day = models.PositiveSmallIntegerField(default=1)
    is_default = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_depreciation_policies")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            DepreciationPolicy.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)


class DepreciationAssetClass(models.Model):
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50, unique=True)
    category = models.ForeignKey("Category", on_delete=models.SET_NULL, null=True, blank=True, related_name="depreciation_asset_classes")
    policy = models.ForeignKey(DepreciationPolicy, on_delete=models.PROTECT, null=True, blank=True, related_name="asset_classes")
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_depreciation_asset_classes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class DepreciationRateVersion(models.Model):
    asset_class = models.ForeignKey(DepreciationAssetClass, on_delete=models.CASCADE, related_name="rate_versions")
    rate = models.DecimalField(max_digits=5, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    source_reference = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_depreciation_rates")
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_depreciation_rates")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["asset_class", "-effective_from", "-created_at"]
        unique_together = [["asset_class", "effective_from"]]

    def clean(self):
        super().clean()
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValidationError({"effective_to": "Effective-to date cannot be before effective-from date."})

    def __str__(self):
        return f"{self.asset_class.code}: {self.rate}% from {self.effective_from}"


class FixedAssetRegisterEntry(models.Model):
    asset_number = models.CharField(max_length=50, unique=True, blank=True)
    item = models.ForeignKey("Item", on_delete=models.PROTECT, related_name="fixed_asset_entries")
    instance = models.OneToOneField("ItemInstance", on_delete=models.PROTECT, null=True, blank=True, related_name="fixed_asset_entry")
    batch = models.OneToOneField("ItemBatch", on_delete=models.PROTECT, null=True, blank=True, related_name="fixed_asset_entry")
    target_type = models.CharField(max_length=20, choices=FixedAssetTargetType.choices)
    asset_class = models.ForeignKey(DepreciationAssetClass, on_delete=models.PROTECT, related_name="assets")
    policy = models.ForeignKey(DepreciationPolicy, on_delete=models.PROTECT, null=True, blank=True, related_name="assets")
    source_inspection = models.ForeignKey("InspectionCertificate", on_delete=models.SET_NULL, null=True, blank=True, related_name="fixed_asset_entries")
    inspection_item = models.ForeignKey("InspectionItem", on_delete=models.SET_NULL, null=True, blank=True, related_name="fixed_asset_entries")
    original_quantity = models.PositiveIntegerField(default=1)
    remaining_quantity = models.PositiveIntegerField(default=1)
    original_cost = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    capitalization_date = models.DateField()
    depreciation_start_date = models.DateField()
    status = models.CharField(max_length=20, choices=FixedAssetStatus.choices, default=FixedAssetStatus.ACTIVE, db_index=True)
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_fixed_asset_entries")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["asset_number", "id"]
        permissions = [
            ("view_depreciation", "Can view depreciation module"),
            ("manage_depreciation", "Can create and edit depreciation profiles and adjustments"),
            ("post_depreciation", "Can configure rates and post depreciation runs"),
        ]

    def clean(self):
        super().clean()
        if self.target_type == FixedAssetTargetType.INSTANCE and not self.instance_id:
            raise ValidationError({"instance": "Individual fixed assets must link to an item instance."})
        if self.target_type == FixedAssetTargetType.LOT and not self.batch_id:
            raise ValidationError({"batch": "Lot fixed assets must link to an item batch/lot."})
        if self.instance_id and self.batch_id:
            raise ValidationError("A fixed asset register entry cannot link to both an instance and a lot.")
        if self.remaining_quantity > self.original_quantity:
            raise ValidationError({"remaining_quantity": "Remaining quantity cannot exceed original quantity."})

    def save(self, *args, **kwargs):
        if self.policy_id is None:
            policy = self.asset_class.policy if self.asset_class_id and self.asset_class.policy_id else None
            if policy is None:
                policy = DepreciationPolicy.objects.filter(is_default=True, is_active=True).first()
            if policy is None:
                policy = DepreciationPolicy.objects.create(name="FBR WDV", is_default=True, is_active=True)
            self.policy = policy

        if not self.asset_number:
            last = FixedAssetRegisterEntry.objects.order_by("-id").first()
            next_seq = (last.id + 1) if last else 1
            while True:
                candidate = f"FA-{next_seq:06d}"
                if not FixedAssetRegisterEntry.objects.filter(asset_number=candidate).exists():
                    self.asset_number = candidate
                    break
                next_seq += 1
        if not self.depreciation_start_date:
            self.depreciation_start_date = self.capitalization_date
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.asset_number} - {self.item.name}"


class DepreciationRun(models.Model):
    policy = models.ForeignKey(DepreciationPolicy, on_delete=models.PROTECT, related_name="runs")
    fiscal_year_start = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=DepreciationRunStatus.choices, default=DepreciationRunStatus.DRAFT, db_index=True)
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_depreciation_runs")
    posted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="posted_depreciation_runs")
    reversed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="reversed_depreciation_runs")
    posted_at = models.DateTimeField(null=True, blank=True)
    reversed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fiscal_year_start", "-created_at"]
        unique_together = [["policy", "fiscal_year_start"]]

    @property
    def fiscal_year_label(self):
        return f"{self.fiscal_year_start}-{str(self.fiscal_year_start + 1)[-2:]}"

    def mark_posted(self, user):
        self.status = DepreciationRunStatus.POSTED
        self.posted_by = user
        self.posted_at = timezone.now()
        self.save(update_fields=["status", "posted_by", "posted_at", "updated_at"])

    def mark_reversed(self, user):
        self.status = DepreciationRunStatus.REVERSED
        self.reversed_by = user
        self.reversed_at = timezone.now()
        self.save(update_fields=["status", "reversed_by", "reversed_at", "updated_at"])

    def __str__(self):
        return f"{self.policy.name} FY {self.fiscal_year_label}"


class DepreciationEntry(models.Model):
    run = models.ForeignKey(DepreciationRun, on_delete=models.PROTECT, related_name="entries")
    asset = models.ForeignKey(FixedAssetRegisterEntry, on_delete=models.PROTECT, related_name="depreciation_entries")
    fiscal_year_start = models.PositiveIntegerField()
    rate_version = models.ForeignKey(DepreciationRateVersion, on_delete=models.PROTECT, related_name="depreciation_entries")
    rate = models.DecimalField(max_digits=5, decimal_places=2)
    opening_value = models.DecimalField(max_digits=14, decimal_places=2)
    depreciation_amount = models.DecimalField(max_digits=14, decimal_places=2)
    accumulated_depreciation = models.DecimalField(max_digits=14, decimal_places=2)
    closing_value = models.DecimalField(max_digits=14, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fiscal_year_start", "asset__asset_number"]
        unique_together = [["asset", "fiscal_year_start", "run"]]

    def __str__(self):
        return f"{self.asset.asset_number} FY {self.fiscal_year_start}: {self.depreciation_amount}"


class AssetValueAdjustment(models.Model):
    asset = models.ForeignKey(FixedAssetRegisterEntry, on_delete=models.PROTECT, related_name="adjustments")
    adjustment_type = models.CharField(max_length=30, choices=AssetAdjustmentType.choices)
    effective_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    quantity_delta = models.IntegerField(default=0)
    reason = models.TextField()
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_asset_value_adjustments")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_date", "-created_at"]

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and self.quantity_delta:
            next_qty = max(0, self.asset.remaining_quantity + self.quantity_delta)
            next_status = self.asset.status
            if next_qty == 0 and self.adjustment_type in {
                AssetAdjustmentType.DISPOSAL,
                AssetAdjustmentType.LOSS,
                AssetAdjustmentType.WRITE_OFF,
                AssetAdjustmentType.QUANTITY_REDUCTION,
            }:
                next_status = FixedAssetStatus.DISPOSED
            self.asset.remaining_quantity = next_qty
            self.asset.status = next_status
            self.asset.save(update_fields=["remaining_quantity", "status", "updated_at"])

    def __str__(self):
        return f"{self.asset.asset_number} {self.adjustment_type} {self.amount}"
