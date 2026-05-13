from decimal import Decimal

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class MaintenanceTargetType(models.TextChoices):
    INSTANCE = "INSTANCE", "Individual Instance"
    BATCH = "BATCH", "Quantity Batch / Lot"


class MaintenanceType(models.TextChoices):
    PREVENTIVE = "PREVENTIVE", "Preventive"
    CORRECTIVE = "CORRECTIVE", "Corrective"
    PREDICTIVE = "PREDICTIVE", "Predictive"
    INSPECTION = "INSPECTION", "Inspection"
    CALIBRATION = "CALIBRATION", "Calibration"


class MaintenanceTriggerType(models.TextChoices):
    CALENDAR = "CALENDAR", "Calendar"
    METER = "METER", "Meter"
    CONDITION = "CONDITION", "Condition"
    MANUAL = "MANUAL", "Manual"
    FAILURE = "FAILURE", "Failure"


class MaintenancePriority(models.TextChoices):
    LOW = "LOW", "Low"
    MEDIUM = "MEDIUM", "Medium"
    HIGH = "HIGH", "High"
    CRITICAL = "CRITICAL", "Critical"


class MaintenanceStatus(models.TextChoices):
    REQUESTED = "REQUESTED", "Requested"
    APPROVED = "APPROVED", "Approved"
    SCHEDULED = "SCHEDULED", "Scheduled"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    ON_HOLD = "ON_HOLD", "On Hold"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class MaintenancePlanCadence(models.TextChoices):
    CALENDAR = "CALENDAR", "Calendar"
    METER = "METER", "Meter"
    CONDITION = "CONDITION", "Condition"


class MaintenanceLogEvent(models.TextChoices):
    CREATED = "CREATED", "Created"
    UPDATED = "UPDATED", "Updated"
    STATUS_CHANGED = "STATUS_CHANGED", "Status Changed"
    SERVICE_NOTE = "SERVICE_NOTE", "Service Note"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class MaintenancePlan(models.Model):
    plan_code = models.CharField(max_length=50, unique=True, blank=True)
    name = models.CharField(max_length=180)
    target_type = models.CharField(max_length=20, choices=MaintenanceTargetType.choices)
    item = models.ForeignKey("Item", on_delete=models.PROTECT, related_name="maintenance_plans")
    instance = models.ForeignKey(
        "ItemInstance",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="maintenance_plans",
    )
    batch = models.ForeignKey(
        "ItemBatch",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="maintenance_plans",
    )
    maintenance_type = models.CharField(
        max_length=20,
        choices=MaintenanceType.choices,
        default=MaintenanceType.PREVENTIVE,
    )
    cadence = models.CharField(
        max_length=20,
        choices=MaintenancePlanCadence.choices,
        default=MaintenancePlanCadence.CALENDAR,
    )
    interval_days = models.PositiveIntegerField(null=True, blank=True)
    meter_name = models.CharField(max_length=80, blank=True, default="")
    meter_interval = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    condition_basis = models.TextField(blank=True, default="")
    priority = models.CharField(max_length=20, choices=MaintenancePriority.choices, default=MaintenancePriority.MEDIUM)
    criticality = models.CharField(max_length=20, choices=MaintenancePriority.choices, default=MaintenancePriority.MEDIUM)
    checklist = models.TextField(blank=True, default="")
    next_due_date = models.DateField(null=True, blank=True)
    last_generated_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_maintenance_plans")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]

    def save(self, *args, **kwargs):
        if not self.plan_code:
            last = MaintenancePlan.objects.order_by("-id").first()
            next_seq = (last.id + 1) if last else 1
            while True:
                candidate = f"MP-{next_seq:06d}"
                if not MaintenancePlan.objects.filter(plan_code=candidate).exists():
                    self.plan_code = candidate
                    break
                next_seq += 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.plan_code} - {self.name}"


class MaintenanceWorkOrder(models.Model):
    work_order_number = models.CharField(max_length=50, unique=True, blank=True)
    plan = models.ForeignKey(
        MaintenancePlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_orders",
    )
    target_type = models.CharField(max_length=20, choices=MaintenanceTargetType.choices)
    item = models.ForeignKey("Item", on_delete=models.PROTECT, related_name="maintenance_work_orders")
    instance = models.ForeignKey(
        "ItemInstance",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="maintenance_work_orders",
    )
    batch = models.ForeignKey(
        "ItemBatch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="maintenance_work_orders",
    )
    location = models.ForeignKey(
        "Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="maintenance_work_orders",
    )
    affected_quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True, default="")
    maintenance_type = models.CharField(max_length=20, choices=MaintenanceType.choices)
    trigger_type = models.CharField(max_length=20, choices=MaintenanceTriggerType.choices, default=MaintenanceTriggerType.MANUAL)
    priority = models.CharField(max_length=20, choices=MaintenancePriority.choices, default=MaintenancePriority.MEDIUM, db_index=True)
    criticality = models.CharField(max_length=20, choices=MaintenancePriority.choices, default=MaintenancePriority.MEDIUM, db_index=True)
    status = models.CharField(max_length=20, choices=MaintenanceStatus.choices, default=MaintenanceStatus.REQUESTED, db_index=True)
    due_date = models.DateField(null=True, blank=True, db_index=True)
    scheduled_start = models.DateTimeField(null=True, blank=True)
    scheduled_end = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    downtime_start = models.DateTimeField(null=True, blank=True)
    downtime_end = models.DateTimeField(null=True, blank=True)
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="requested_maintenance_work_orders")
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_maintenance_work_orders")
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_maintenance_work_orders")
    started_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="started_maintenance_work_orders")
    completed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="completed_maintenance_work_orders")
    vendor_name = models.CharField(max_length=180, blank=True, default="")
    estimated_cost = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    actual_cost = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    failure_mode = models.CharField(max_length=180, blank=True, default="")
    root_cause = models.CharField(max_length=180, blank=True, default="")
    condition_before = models.CharField(max_length=180, blank=True, default="")
    condition_after = models.CharField(max_length=180, blank=True, default="")
    action_taken = models.TextField(blank=True, default="")
    outcome_notes = models.TextField(blank=True, default="")
    follow_up_required = models.BooleanField(default=False)
    next_due_date = models.DateField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True, default="")
    previous_instance_status = models.CharField(max_length=20, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status", "due_date"]),
            models.Index(fields=["target_type", "status"]),
        ]
        permissions = [
            ("view_maintenance", "Can view maintenance module"),
            ("create_maintenance", "Can create maintenance work orders"),
            ("edit_maintenance", "Can edit maintenance work orders"),
            ("delete_maintenance", "Can delete maintenance work orders"),
            ("approve_maintenance", "Can approve maintenance work orders"),
            ("close_maintenance", "Can close maintenance work orders"),
            ("manage_maintenance_plans", "Can manage maintenance plans"),
        ]

    @property
    def target_label(self):
        if self.instance_id:
            return self.instance.item.name
        if self.batch_id:
            return f"{self.batch.item.name} / Batch {self.batch.batch_number}"
        return self.item.name

    @property
    def downtime_minutes(self):
        if not self.downtime_start or not self.downtime_end:
            return None
        return max(0, int((self.downtime_end - self.downtime_start).total_seconds() // 60))

    def save(self, *args, **kwargs):
        if not self.work_order_number:
            last = MaintenanceWorkOrder.objects.order_by("-id").first()
            next_seq = (last.id + 1) if last else 1
            while True:
                candidate = f"MWO-{next_seq:06d}"
                if not MaintenanceWorkOrder.objects.filter(work_order_number=candidate).exists():
                    self.work_order_number = candidate
                    break
                next_seq += 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.work_order_number} - {self.title}"


class MaintenanceLog(models.Model):
    work_order = models.ForeignKey(MaintenanceWorkOrder, on_delete=models.CASCADE, related_name="history")
    event_type = models.CharField(max_length=30, choices=MaintenanceLogEvent.choices)
    from_status = models.CharField(max_length=20, choices=MaintenanceStatus.choices, blank=True, default="")
    to_status = models.CharField(max_length=20, choices=MaintenanceStatus.choices, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    condition_before = models.CharField(max_length=180, blank=True, default="")
    condition_after = models.CharField(max_length=180, blank=True, default="")
    failure_mode = models.CharField(max_length=180, blank=True, default="")
    root_cause = models.CharField(max_length=180, blank=True, default="")
    action_taken = models.TextField(blank=True, default="")
    cost = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    downtime_minutes = models.PositiveIntegerField(null=True, blank=True)
    performed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="maintenance_logs")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.work_order.work_order_number} {self.event_type}"


class MaintenanceMeterReading(models.Model):
    target_type = models.CharField(max_length=20, choices=MaintenanceTargetType.choices)
    item = models.ForeignKey("Item", on_delete=models.PROTECT, related_name="maintenance_meter_readings")
    instance = models.ForeignKey(
        "ItemInstance",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="maintenance_meter_readings",
    )
    batch = models.ForeignKey(
        "ItemBatch",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="maintenance_meter_readings",
    )
    location = models.ForeignKey(
        "Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="maintenance_meter_readings",
    )
    reading_name = models.CharField(max_length=80)
    value = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    unit = models.CharField(max_length=40, blank=True, default="")
    recorded_at = models.DateTimeField(default=timezone.now)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="maintenance_meter_readings")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at", "-id"]

    def __str__(self):
        return f"{self.reading_name}: {self.value} {self.unit}".strip()
