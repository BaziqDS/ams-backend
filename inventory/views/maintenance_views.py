from datetime import timedelta

from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from ..models import (
    InstanceStatus,
    MaintenanceLog,
    MaintenanceLogEvent,
    MaintenanceMeterReading,
    MaintenancePlan,
    MaintenancePlanCadence,
    MaintenanceStatus,
    MaintenanceWorkOrder,
    StockRecord,
)
from ..permissions import (
    MaintenanceMeterReadingPermission,
    MaintenancePermission,
    MaintenancePlanPermission,
)
from ..serializers import (
    MaintenanceMeterReadingSerializer,
    MaintenancePlanSerializer,
    MaintenanceWorkOrderSerializer,
)
from .utils import get_item_scope_locations


def _log_work_order(work_order, *, event_type, user, from_status="", to_status="", notes="", **extra):
    return MaintenanceLog.objects.create(
        work_order=work_order,
        event_type=event_type,
        from_status=from_status or "",
        to_status=to_status or "",
        notes=notes or "",
        performed_by=user if user and user.is_authenticated else None,
        **extra,
    )


class MaintenanceWorkOrderViewSet(viewsets.ModelViewSet):
    serializer_class = MaintenanceWorkOrderSerializer
    permission_classes = [permissions.IsAuthenticated, MaintenancePermission]

    def get_queryset(self):
        queryset = (
            MaintenanceWorkOrder.objects.select_related(
                "plan",
                "item",
                "instance",
                "instance__item",
                "instance__current_location",
                "batch",
                "batch__item",
                "location",
                "requested_by",
                "approved_by",
                "assigned_to",
                "started_by",
                "completed_by",
            )
            .prefetch_related(
                Prefetch(
                    "history",
                    queryset=MaintenanceLog.objects.select_related("performed_by"),
                ),
                "batch__stock_records",
            )
            .order_by("-created_at", "-id")
        )

        accessible_locations = get_item_scope_locations(
            self.request.user,
            self.request.query_params.getlist("scope"),
        )
        queryset = queryset.filter(
            Q(location__in=accessible_locations)
            | Q(instance__current_location__in=accessible_locations)
            | Q(batch__stock_records__location__in=accessible_locations)
        ).distinct()

        for key in ("status", "target_type", "priority", "maintenance_type", "trigger_type"):
            value = self.request.query_params.get(key)
            if value:
                queryset = queryset.filter(**{key: value})

        for key in ("instance", "batch", "item", "location", "plan"):
            value = self.request.query_params.get(key)
            if value:
                queryset = queryset.filter(**{f"{key}_id": value})

        open_only = self.request.query_params.get("open")
        if open_only in {"1", "true", "True"}:
            queryset = queryset.exclude(status__in=[MaintenanceStatus.COMPLETED, MaintenanceStatus.CANCELLED])

        overdue = self.request.query_params.get("overdue")
        if overdue in {"1", "true", "True"}:
            queryset = queryset.filter(
                due_date__lt=timezone.localdate(),
            ).exclude(status__in=[MaintenanceStatus.COMPLETED, MaintenanceStatus.CANCELLED])

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(work_order_number__icontains=search)
                | Q(title__icontains=search)
                | Q(item__name__icontains=search)
                | Q(item__code__icontains=search)
                | Q(instance__serial_number__icontains=search)
                | Q(batch__batch_number__icontains=search)
            )

        return queryset

    def perform_create(self, serializer):
        self._ensure_target_in_scope(serializer.validated_data)
        work_order = serializer.save(requested_by=self.request.user)
        _log_work_order(
            work_order,
            event_type=MaintenanceLogEvent.CREATED,
            user=self.request.user,
            to_status=work_order.status,
            notes="Maintenance work order created.",
        )

    def perform_update(self, serializer):
        self._ensure_target_in_scope(serializer.validated_data, current=serializer.instance)
        serializer.save()

    def _ensure_target_in_scope(self, attrs, current=None):
        accessible_locations = get_item_scope_locations(self.request.user, self.request.query_params.getlist("scope"))
        instance = attrs.get("instance") or getattr(current, "instance", None)
        location = attrs.get("location") or getattr(current, "location", None)
        if instance and not accessible_locations.filter(id=instance.current_location_id).exists():
            raise PermissionDenied("Maintenance target is outside your location scope.")
        if location and not accessible_locations.filter(id=location.id).exists():
            raise PermissionDenied("Maintenance location is outside your location scope.")

    @transaction.atomic
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        work_order = self.get_object()
        if work_order.status in {MaintenanceStatus.COMPLETED, MaintenanceStatus.CANCELLED}:
            return Response({"detail": "Completed or cancelled work orders cannot be approved."}, status=status.HTTP_400_BAD_REQUEST)

        previous_status = work_order.status
        work_order.status = MaintenanceStatus.APPROVED
        work_order.approved_by = request.user
        work_order.approved_at = timezone.now()
        work_order.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        _log_work_order(
            work_order,
            event_type=MaintenanceLogEvent.STATUS_CHANGED,
            user=request.user,
            from_status=previous_status,
            to_status=work_order.status,
            notes=request.data.get("notes", "Maintenance work order approved."),
        )
        return Response(self.get_serializer(work_order).data)

    @transaction.atomic
    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        work_order = self.get_object()
        if work_order.status in {MaintenanceStatus.COMPLETED, MaintenanceStatus.CANCELLED}:
            return Response({"detail": "Completed or cancelled work orders cannot be started."}, status=status.HTTP_400_BAD_REQUEST)

        previous_status = work_order.status
        now = timezone.now()
        work_order.status = MaintenanceStatus.IN_PROGRESS
        work_order.started_by = request.user
        work_order.started_at = work_order.started_at or now
        work_order.downtime_start = work_order.downtime_start or now

        if work_order.instance_id and work_order.instance.status != InstanceStatus.MAINTENANCE:
            work_order.previous_instance_status = work_order.instance.status
            work_order.instance.status = InstanceStatus.MAINTENANCE
            work_order.instance.save(update_fields=["status", "updated_at"])

        work_order.save(update_fields=[
            "status",
            "started_by",
            "started_at",
            "downtime_start",
            "previous_instance_status",
            "updated_at",
        ])
        _log_work_order(
            work_order,
            event_type=MaintenanceLogEvent.STATUS_CHANGED,
            user=request.user,
            from_status=previous_status,
            to_status=work_order.status,
            notes=request.data.get("notes", "Maintenance work started."),
        )
        return Response(self.get_serializer(work_order).data)

    @transaction.atomic
    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        work_order = self.get_object()
        if work_order.status in {MaintenanceStatus.COMPLETED, MaintenanceStatus.CANCELLED}:
            return Response({"detail": "Work order is already closed."}, status=status.HTTP_400_BAD_REQUEST)

        action_taken = str(request.data.get("action_taken", "")).strip()
        if not action_taken:
            return Response({"action_taken": "Action taken is required to close maintenance."}, status=status.HTTP_400_BAD_REQUEST)

        previous_status = work_order.status
        now = timezone.now()
        for field in (
            "actual_cost",
            "failure_mode",
            "root_cause",
            "condition_before",
            "condition_after",
            "outcome_notes",
            "next_due_date",
            "follow_up_required",
        ):
            if field in request.data:
                setattr(work_order, field, request.data.get(field))
        work_order.action_taken = action_taken
        work_order.status = MaintenanceStatus.COMPLETED
        work_order.completed_by = request.user
        work_order.completed_at = now
        work_order.downtime_end = work_order.downtime_end or now

        if work_order.instance_id:
            restore_status = work_order.previous_instance_status or InstanceStatus.IN_USE
            work_order.instance.status = restore_status
            work_order.instance.save(update_fields=["status", "updated_at"])

        work_order.save()
        _log_work_order(
            work_order,
            event_type=MaintenanceLogEvent.COMPLETED,
            user=request.user,
            from_status=previous_status,
            to_status=work_order.status,
            notes=work_order.outcome_notes or "Maintenance work completed.",
            condition_before=work_order.condition_before,
            condition_after=work_order.condition_after,
            failure_mode=work_order.failure_mode,
            root_cause=work_order.root_cause,
            action_taken=work_order.action_taken,
            cost=work_order.actual_cost,
            downtime_minutes=work_order.downtime_minutes,
        )
        return Response(self.get_serializer(work_order).data)

    @transaction.atomic
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        work_order = self.get_object()
        if work_order.status == MaintenanceStatus.COMPLETED:
            return Response({"detail": "Completed work orders cannot be cancelled."}, status=status.HTTP_400_BAD_REQUEST)
        if work_order.status == MaintenanceStatus.CANCELLED:
            return Response({"detail": "Work order is already cancelled."}, status=status.HTTP_400_BAD_REQUEST)

        reason = str(request.data.get("cancellation_reason", "") or request.data.get("notes", "")).strip()
        if not reason:
            return Response({"cancellation_reason": "Cancellation reason is required."}, status=status.HTTP_400_BAD_REQUEST)

        previous_status = work_order.status
        work_order.status = MaintenanceStatus.CANCELLED
        work_order.cancellation_reason = reason
        work_order.downtime_end = work_order.downtime_end or timezone.now()
        if work_order.instance_id and work_order.previous_instance_status:
            work_order.instance.status = work_order.previous_instance_status
            work_order.instance.save(update_fields=["status", "updated_at"])
        work_order.save(update_fields=["status", "cancellation_reason", "downtime_end", "updated_at"])
        _log_work_order(
            work_order,
            event_type=MaintenanceLogEvent.CANCELLED,
            user=request.user,
            from_status=previous_status,
            to_status=work_order.status,
            notes=reason,
        )
        return Response(self.get_serializer(work_order).data)

    @action(detail=True, methods=["post"], url_path="notes")
    def add_note(self, request, pk=None):
        work_order = self.get_object()
        notes = str(request.data.get("notes", "")).strip()
        if not notes:
            return Response({"notes": "Note is required."}, status=status.HTTP_400_BAD_REQUEST)
        _log_work_order(
            work_order,
            event_type=MaintenanceLogEvent.SERVICE_NOTE,
            user=request.user,
            from_status=work_order.status,
            to_status=work_order.status,
            notes=notes,
        )
        return Response(self.get_serializer(work_order).data)


class MaintenancePlanViewSet(viewsets.ModelViewSet):
    serializer_class = MaintenancePlanSerializer
    permission_classes = [permissions.IsAuthenticated, MaintenancePlanPermission]

    def get_queryset(self):
        queryset = MaintenancePlan.objects.select_related(
            "item",
            "instance",
            "instance__item",
            "batch",
            "batch__item",
            "created_by",
        ).order_by("name", "id")
        accessible_locations = get_item_scope_locations(
            self.request.user,
            self.request.query_params.getlist("scope"),
        )
        queryset = queryset.filter(
            Q(instance__current_location__in=accessible_locations)
            | Q(batch__stock_records__location__in=accessible_locations)
            | Q(item__instances__current_location__in=accessible_locations)
            | Q(item__stock_records__location__in=accessible_locations)
        ).distinct()

        if self.request.query_params.get("active") in {"1", "true", "True"}:
            queryset = queryset.filter(is_active=True)
        for key in ("target_type", "item", "instance", "batch", "maintenance_type", "cadence"):
            value = self.request.query_params.get(key)
            if value:
                queryset = queryset.filter(**{f"{key}_id" if key in {"item", "instance", "batch"} else key: value})
        return queryset

    def perform_create(self, serializer):
        self._ensure_plan_target_in_scope(serializer.validated_data)
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        self._ensure_plan_target_in_scope(serializer.validated_data, current=serializer.instance)
        serializer.save()

    def _ensure_plan_target_in_scope(self, attrs, current=None):
        accessible_locations = get_item_scope_locations(self.request.user, self.request.query_params.getlist("scope"))
        instance = attrs.get("instance") or getattr(current, "instance", None)
        batch = attrs.get("batch") or getattr(current, "batch", None)
        item = attrs.get("item") or getattr(current, "item", None)

        if instance and not accessible_locations.filter(id=instance.current_location_id).exists():
            raise PermissionDenied("Maintenance plan target is outside your location scope.")
        if batch and not batch.stock_records.filter(location__in=accessible_locations, quantity__gt=0).exists():
            raise PermissionDenied("Maintenance plan batch is outside your location scope.")
        if item and not (
            item.instances.filter(current_location__in=accessible_locations).exists()
            or item.stock_records.filter(location__in=accessible_locations, quantity__gt=0).exists()
        ):
            raise PermissionDenied("Maintenance plan item is outside your location scope.")

    @transaction.atomic
    @action(detail=True, methods=["post"], url_path="generate-work-order")
    def generate_work_order(self, request, pk=None):
        plan = self.get_object()
        if not plan.is_active:
            return Response({"detail": "Inactive plans cannot generate work orders."}, status=status.HTTP_400_BAD_REQUEST)
        if not plan.instance_id and not plan.batch_id:
            return Response(
                {"detail": "Select a specific instance or batch before generating a work order from this plan."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = {
            "plan": plan.id,
            "target_type": plan.target_type,
            "instance": plan.instance_id,
            "batch": plan.batch_id,
            "location": request.data.get("location"),
            "affected_quantity": request.data.get("affected_quantity") or 1,
            "title": request.data.get("title") or plan.name,
            "description": request.data.get("description") or plan.checklist,
            "maintenance_type": plan.maintenance_type,
            "trigger_type": request.data.get("trigger_type") or "CALENDAR",
            "priority": plan.priority,
            "criticality": plan.criticality,
            "due_date": request.data.get("due_date") or plan.next_due_date,
        }
        if plan.batch_id and not payload["location"]:
            accessible_locations = get_item_scope_locations(request.user, request.query_params.getlist("scope"))
            stock_record = (
                StockRecord.objects.filter(
                    item=plan.item,
                    batch=plan.batch,
                    location__in=accessible_locations,
                    quantity__gt=0,
                )
                .select_related("location")
                .order_by("location__name", "id")
                .first()
            )
            if stock_record:
                payload["location"] = stock_record.location_id
        serializer = MaintenanceWorkOrderSerializer(data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        work_order = serializer.save(requested_by=request.user, status=MaintenanceStatus.SCHEDULED)
        _log_work_order(
            work_order,
            event_type=MaintenanceLogEvent.CREATED,
            user=request.user,
            to_status=work_order.status,
            notes=f"Generated from maintenance plan {plan.plan_code}.",
        )

        plan.last_generated_at = timezone.now()
        if plan.cadence == MaintenancePlanCadence.CALENDAR and plan.interval_days:
            base_date = plan.next_due_date or timezone.localdate()
            plan.next_due_date = base_date + timedelta(days=plan.interval_days)
        plan.save(update_fields=["last_generated_at", "next_due_date", "updated_at"])
        return Response(MaintenanceWorkOrderSerializer(work_order, context={"request": request}).data, status=status.HTTP_201_CREATED)


class MaintenanceMeterReadingViewSet(viewsets.ModelViewSet):
    serializer_class = MaintenanceMeterReadingSerializer
    permission_classes = [permissions.IsAuthenticated, MaintenanceMeterReadingPermission]

    def get_queryset(self):
        queryset = MaintenanceMeterReading.objects.select_related(
            "item",
            "instance",
            "instance__item",
            "batch",
            "batch__item",
            "location",
            "recorded_by",
        ).order_by("-recorded_at", "-id")
        accessible_locations = get_item_scope_locations(
            self.request.user,
            self.request.query_params.getlist("scope"),
        )
        queryset = queryset.filter(
            Q(location__in=accessible_locations)
            | Q(instance__current_location__in=accessible_locations)
            | Q(batch__stock_records__location__in=accessible_locations)
        ).distinct()

        for key in ("target_type", "item", "instance", "batch", "location", "reading_name"):
            value = self.request.query_params.get(key)
            if value:
                queryset = queryset.filter(**{f"{key}_id" if key in {"item", "instance", "batch", "location"} else key: value})
        return queryset

    def perform_create(self, serializer):
        self._ensure_reading_target_in_scope(serializer.validated_data)
        serializer.save(recorded_by=self.request.user)

    def perform_update(self, serializer):
        self._ensure_reading_target_in_scope(serializer.validated_data, current=serializer.instance)
        serializer.save()

    def _ensure_reading_target_in_scope(self, attrs, current=None):
        accessible_locations = get_item_scope_locations(self.request.user, self.request.query_params.getlist("scope"))
        instance = attrs.get("instance") or getattr(current, "instance", None)
        location = attrs.get("location") or getattr(current, "location", None)
        if instance and not accessible_locations.filter(id=instance.current_location_id).exists():
            raise PermissionDenied("Maintenance reading target is outside your location scope.")
        if location and not accessible_locations.filter(id=location.id).exists():
            raise PermissionDenied("Maintenance reading location is outside your location scope.")
