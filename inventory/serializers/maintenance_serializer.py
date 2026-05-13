from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from ..models import (
    Item,
    ItemBatch,
    ItemInstance,
    Location,
    MaintenanceLog,
    MaintenanceMeterReading,
    MaintenancePlan,
    MaintenancePlanCadence,
    MaintenanceTargetType,
    MaintenanceWorkOrder,
    StockRecord,
)


class MaintenanceLogSerializer(serializers.ModelSerializer):
    performed_by_name = serializers.CharField(source="performed_by.username", read_only=True)

    class Meta:
        model = MaintenanceLog
        fields = [
            "id",
            "event_type",
            "from_status",
            "to_status",
            "notes",
            "condition_before",
            "condition_after",
            "failure_mode",
            "root_cause",
            "action_taken",
            "cost",
            "downtime_minutes",
            "performed_by",
            "performed_by_name",
            "created_at",
        ]
        read_only_fields = fields


class MaintenanceTargetValidationMixin:
    def _validate_target(self, attrs, *, require_quantity=False):
        instance = attrs.get("instance") or getattr(self.instance, "instance", None)
        batch = attrs.get("batch") or getattr(self.instance, "batch", None)
        location = attrs.get("location") or getattr(self.instance, "location", None)
        target_type = attrs.get("target_type") or getattr(self.instance, "target_type", None)

        if target_type == MaintenanceTargetType.INSTANCE:
            if not instance:
                raise serializers.ValidationError({"instance": "Instance target is required."})
            if attrs.get("batch") is not None:
                raise serializers.ValidationError({"batch": "Batch must be empty for instance maintenance."})
            attrs["item"] = instance.item
            attrs["location"] = instance.current_location
            if "affected_quantity" in self.fields:
                attrs["affected_quantity"] = 1
            return attrs

        if target_type == MaintenanceTargetType.BATCH:
            if not batch:
                raise serializers.ValidationError({"batch": "Batch target is required."})
            if attrs.get("instance") is not None:
                raise serializers.ValidationError({"instance": "Instance must be empty for quantity maintenance."})
            if not location:
                raise serializers.ValidationError({"location": "Location is required for quantity maintenance."})
            quantity = attrs.get("affected_quantity") or getattr(self.instance, "affected_quantity", None)
            if require_quantity and not quantity:
                raise serializers.ValidationError({"affected_quantity": "Affected quantity is required."})
            if quantity:
                available = (
                    StockRecord.objects.filter(item=batch.item, batch=batch, location=location)
                    .aggregate(total=Sum("quantity"))
                    .get("total")
                    or 0
                )
                if quantity > available:
                    raise serializers.ValidationError({
                        "affected_quantity": f"Only {available} units are available at this location."
                    })
            attrs["item"] = batch.item
            attrs["location"] = location
            return attrs

        raise serializers.ValidationError({"target_type": "Target type must be INSTANCE or BATCH."})


class MaintenanceWorkOrderSerializer(MaintenanceTargetValidationMixin, serializers.ModelSerializer):
    target_label = serializers.CharField(read_only=True)
    item = serializers.PrimaryKeyRelatedField(read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    item_code = serializers.CharField(source="item.code", read_only=True)
    instance_serial_number = serializers.CharField(source="instance.serial_number", read_only=True, allow_null=True)
    batch_number = serializers.CharField(source="batch.batch_number", read_only=True, allow_null=True)
    location_name = serializers.CharField(source="location.name", read_only=True, allow_null=True)
    location_code = serializers.CharField(source="location.code", read_only=True, allow_null=True)
    requested_by_name = serializers.CharField(source="requested_by.username", read_only=True, allow_null=True)
    approved_by_name = serializers.CharField(source="approved_by.username", read_only=True, allow_null=True)
    assigned_to_name = serializers.CharField(source="assigned_to.username", read_only=True, allow_null=True)
    started_by_name = serializers.CharField(source="started_by.username", read_only=True, allow_null=True)
    completed_by_name = serializers.CharField(source="completed_by.username", read_only=True, allow_null=True)
    downtime_minutes = serializers.IntegerField(read_only=True, allow_null=True)
    history = MaintenanceLogSerializer(many=True, read_only=True)

    class Meta:
        model = MaintenanceWorkOrder
        fields = [
            "id",
            "work_order_number",
            "plan",
            "target_type",
            "target_label",
            "item",
            "item_name",
            "item_code",
            "instance",
            "instance_serial_number",
            "batch",
            "batch_number",
            "location",
            "location_name",
            "location_code",
            "affected_quantity",
            "title",
            "description",
            "maintenance_type",
            "trigger_type",
            "priority",
            "criticality",
            "status",
            "due_date",
            "scheduled_start",
            "scheduled_end",
            "started_at",
            "completed_at",
            "approved_at",
            "downtime_start",
            "downtime_end",
            "requested_by",
            "requested_by_name",
            "approved_by",
            "approved_by_name",
            "assigned_to",
            "assigned_to_name",
            "started_by",
            "started_by_name",
            "completed_by",
            "completed_by_name",
            "vendor_name",
            "estimated_cost",
            "actual_cost",
            "failure_mode",
            "root_cause",
            "condition_before",
            "condition_after",
            "action_taken",
            "outcome_notes",
            "follow_up_required",
            "next_due_date",
            "cancellation_reason",
            "previous_instance_status",
            "downtime_minutes",
            "history",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "work_order_number",
            "status",
            "approved_at",
            "started_at",
            "completed_at",
            "downtime_start",
            "downtime_end",
            "requested_by",
            "approved_by",
            "started_by",
            "completed_by",
            "previous_instance_status",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        if self.instance and any(key in attrs for key in ("target_type", "instance", "batch")):
            raise serializers.ValidationError("Maintenance target cannot be changed after creation.")
        return self._validate_target(attrs, require_quantity=True)

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user and request.user.is_authenticated:
            validated_data["requested_by"] = request.user
        return super().create(validated_data)


class MaintenancePlanSerializer(MaintenanceTargetValidationMixin, serializers.ModelSerializer):
    item = serializers.PrimaryKeyRelatedField(queryset=Item.objects.all(), required=False)
    item_name = serializers.CharField(source="item.name", read_only=True)
    item_code = serializers.CharField(source="item.code", read_only=True)
    instance_serial_number = serializers.CharField(source="instance.serial_number", read_only=True, allow_null=True)
    batch_number = serializers.CharField(source="batch.batch_number", read_only=True, allow_null=True)
    target_label = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source="created_by.username", read_only=True, allow_null=True)

    class Meta:
        model = MaintenancePlan
        fields = [
            "id",
            "plan_code",
            "name",
            "target_type",
            "target_label",
            "item",
            "item_name",
            "item_code",
            "instance",
            "instance_serial_number",
            "batch",
            "batch_number",
            "maintenance_type",
            "cadence",
            "interval_days",
            "meter_name",
            "meter_interval",
            "condition_basis",
            "priority",
            "criticality",
            "checklist",
            "next_due_date",
            "last_generated_at",
            "is_active",
            "created_by",
            "created_by_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["plan_code", "last_generated_at", "created_by", "created_at", "updated_at"]

    def get_target_label(self, obj):
        if obj.instance_id:
            return obj.instance.item.name
        if obj.batch_id:
            return f"{obj.batch.item.name} / Batch {obj.batch.batch_number}"
        return obj.item.name

    def validate(self, attrs):
        if self.instance and any(key in attrs for key in ("target_type", "instance", "batch", "item")):
            raise serializers.ValidationError("Maintenance plan target cannot be changed after creation.")

        target_type = attrs.get("target_type") or getattr(self.instance, "target_type", None)
        instance = attrs.get("instance") or getattr(self.instance, "instance", None)
        batch = attrs.get("batch") or getattr(self.instance, "batch", None)
        item = attrs.get("item") or getattr(self.instance, "item", None)

        if target_type == MaintenanceTargetType.INSTANCE:
            if instance:
                attrs["item"] = instance.item
            elif not item:
                raise serializers.ValidationError({"item": "Item is required when planning for all instances."})
            if attrs.get("batch") is not None:
                raise serializers.ValidationError({"batch": "Batch must be empty for instance plans."})
        elif target_type == MaintenanceTargetType.BATCH:
            if batch:
                attrs["item"] = batch.item
            elif not item:
                raise serializers.ValidationError({"item": "Item is required when planning for quantity assets."})
            if attrs.get("instance") is not None:
                raise serializers.ValidationError({"instance": "Instance must be empty for quantity plans."})
        else:
            raise serializers.ValidationError({"target_type": "Target type must be INSTANCE or BATCH."})

        cadence = attrs.get("cadence") or getattr(self.instance, "cadence", None)
        if cadence == MaintenancePlanCadence.CALENDAR and not (attrs.get("interval_days") or getattr(self.instance, "interval_days", None)):
            raise serializers.ValidationError({"interval_days": "Interval days are required for calendar maintenance plans."})
        if cadence == MaintenancePlanCadence.METER:
            meter_name = attrs.get("meter_name") or getattr(self.instance, "meter_name", "")
            meter_interval = attrs.get("meter_interval") or getattr(self.instance, "meter_interval", None)
            if not meter_name or meter_interval is None:
                raise serializers.ValidationError({"meter_name": "Meter name and interval are required for meter plans."})
        if cadence == MaintenancePlanCadence.CONDITION and not (attrs.get("condition_basis") or getattr(self.instance, "condition_basis", "")):
            raise serializers.ValidationError({"condition_basis": "Condition basis is required for condition plans."})
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user and request.user.is_authenticated:
            validated_data["created_by"] = request.user
        return super().create(validated_data)


class MaintenanceMeterReadingSerializer(MaintenanceTargetValidationMixin, serializers.ModelSerializer):
    item = serializers.PrimaryKeyRelatedField(read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    item_code = serializers.CharField(source="item.code", read_only=True)
    instance_serial_number = serializers.CharField(source="instance.serial_number", read_only=True, allow_null=True)
    batch_number = serializers.CharField(source="batch.batch_number", read_only=True, allow_null=True)
    location_name = serializers.CharField(source="location.name", read_only=True, allow_null=True)
    recorded_by_name = serializers.CharField(source="recorded_by.username", read_only=True, allow_null=True)
    target_label = serializers.SerializerMethodField()

    class Meta:
        model = MaintenanceMeterReading
        fields = [
            "id",
            "target_type",
            "target_label",
            "item",
            "item_name",
            "item_code",
            "instance",
            "instance_serial_number",
            "batch",
            "batch_number",
            "location",
            "location_name",
            "reading_name",
            "value",
            "unit",
            "recorded_at",
            "recorded_by",
            "recorded_by_name",
            "notes",
            "created_at",
        ]
        read_only_fields = ["recorded_by", "created_at"]

    def get_target_label(self, obj):
        if obj.instance_id:
            return obj.instance.item.name
        if obj.batch_id:
            return f"{obj.batch.item.name} / Batch {obj.batch.batch_number}"
        return obj.item.name

    def validate(self, attrs):
        if self.instance and any(key in attrs for key in ("target_type", "instance", "batch")):
            raise serializers.ValidationError("Meter reading target cannot be changed after creation.")
        return self._validate_target(attrs, require_quantity=False)

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user and request.user.is_authenticated:
            validated_data["recorded_by"] = request.user
        return super().create(validated_data)
