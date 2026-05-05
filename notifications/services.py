from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Iterable
from urllib.parse import urlencode

from django.contrib.auth.models import User
from django.db.models import F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from inventory.models import (
    CategoryType,
    CorrectionResolutionType,
    CorrectionStatus,
    InspectionCertificate,
    InspectionStage,
    Item,
    ItemBatch,
    ItemInstance,
    Location,
    StockCorrectionRequest,
    StockEntry,
    StockRegister,
    TrackingType,
)
from notifications.models import NotificationEvent, NotificationSeverity, UserNotification


@dataclass(frozen=True)
class AlertRecord:
    key: str
    module: str
    severity: str
    title: str
    message: str
    href: str
    count: int
    meta: dict[str, object] | None = None


SEVERITY_SORT_ORDER = {
    NotificationSeverity.CRITICAL: 0,
    NotificationSeverity.WARNING: 1,
    NotificationSeverity.INFO: 2,
}

INSPECTION_STAGE_PERM_MAP = {
    InspectionStage.STOCK_DETAILS: "inventory.fill_stock_details",
    InspectionStage.CENTRAL_REGISTER: "inventory.fill_central_register",
    InspectionStage.FINANCE_REVIEW: "inventory.review_finance",
}


def _items_alert_href(*, stock: str | None = None, tracking: str | None = None, focus: str | None = None) -> str:
    params: dict[str, str] = {}
    if stock:
        params["stock"] = stock
    if tracking:
        params["tracking"] = tracking
    if focus:
        params["focus"] = focus
    query = urlencode(params)
    return f"/items?{query}" if query else "/items"


def _clear_permission_caches(user: User) -> None:
    for cache_name in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        if hasattr(user, cache_name):
            delattr(user, cache_name)


def user_has_perm(user: User, perm: str) -> bool:
    _clear_permission_caches(user)
    return user.has_perm(perm)


def _active_users_queryset():
    return (
        User.objects.filter(is_active=True)
        .select_related("profile")
        .prefetch_related("groups", "user_permissions", "profile__assigned_locations")
        .distinct()
    )


def _dedupe_users(users: Iterable[User | None]) -> list[User]:
    seen: set[int] = set()
    unique_users: list[User] = []
    for user in users:
        if not user or not getattr(user, "is_active", False):
            continue
        if user.pk in seen:
            continue
        seen.add(user.pk)
        unique_users.append(user)
    return unique_users


def create_notification_event(
    *,
    module: str,
    kind: str,
    severity: str,
    title: str,
    message: str,
    users: Iterable[User | None],
    href: str = "",
    entity_type: str = "",
    entity_id: int | None = None,
    actor: User | None = None,
    metadata: dict[str, object] | None = None,
) -> NotificationEvent | None:
    recipients = _dedupe_users(users)
    if not recipients and actor and getattr(actor, "is_authenticated", False):
        recipients = [actor]
    if not recipients:
        return None

    event = NotificationEvent.objects.create(
        module=module,
        kind=kind,
        severity=severity,
        title=title,
        message=message,
        href=href,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        metadata=metadata or {},
    )
    UserNotification.objects.bulk_create(
        [UserNotification(user=user, event=event) for user in recipients],
        ignore_conflicts=True,
    )
    return event


def _location_access_scope(user: User):
    if user.is_superuser:
        return Location.objects.filter(is_active=True)
    if not hasattr(user, "profile"):
        return Location.objects.none()

    location_ids: set[int] = set()
    for location in user.profile.assigned_locations.filter(is_active=True):
        location_ids.update(location.get_descendants(include_self=True).values_list("id", flat=True))
    return Location.objects.filter(id__in=location_ids, is_active=True)


def _inspection_scope_for_user(user: User):
    if user.is_superuser:
        return InspectionCertificate.objects.all()
    if user_has_perm(user, "inventory.review_finance"):
        return InspectionCertificate.objects.all()
    if not hasattr(user, "profile"):
        return InspectionCertificate.objects.none()
    return InspectionCertificate.objects.filter(
        department__in=user.profile.get_user_management_locations()
    ).distinct()


def _item_scope_for_user(user: User):
    if not hasattr(user, "profile"):
        return Location.objects.none()

    if (
        user.is_superuser
        or user.groups.filter(name="System Admin").exists()
        or user_has_perm(user, "inventory.view_global_distribution")
        or user_has_perm(user, "inventory.manage_all_locations")
    ):
        return Location.objects.filter(is_active=True)

    location_ids: set[int] = set()
    for location in user.profile.assigned_locations.all():
        descendants = location.get_descendants(include_self=True)
        location_ids.update(descendants.values_list("id", flat=True))

        if location.is_store:
            standalone = location.get_parent_standalone()
            if standalone:
                department_locations = Location.objects.filter(
                    hierarchy_path__startswith=standalone.hierarchy_path,
                    is_active=True,
                )
                location_ids.update(department_locations.values_list("id", flat=True))

    return Location.objects.filter(id__in=location_ids, is_active=True).distinct()


def users_for_inspection_stage(inspection: InspectionCertificate, permission_codename: str) -> list[User]:
    users: list[User] = []
    for user in _active_users_queryset():
        if not user_has_perm(user, permission_codename):
            continue
        if user.is_superuser:
            users.append(user)
            continue
        if not hasattr(user, "profile"):
            continue
        if user.profile.get_user_management_locations().filter(id=inspection.department_id).exists():
            users.append(user)
    return users


def inspection_visible_users(inspection: InspectionCertificate) -> list[User]:
    users: list[User] = []
    for user in _active_users_queryset():
        if user.is_superuser:
            users.append(user)
            continue
        if not user_has_perm(user, "inventory.view_inspectioncertificate"):
            continue
        if not hasattr(user, "profile"):
            continue
        if user.profile.get_user_management_locations().filter(id=inspection.department_id).exists():
            users.append(user)
    return users


def stock_entry_ack_users(entry: StockEntry) -> list[User]:
    users: list[User] = []
    if not entry.to_location_id:
        return users
    for user in _active_users_queryset():
        if user.is_superuser:
            users.append(user)
            continue
        if not user_has_perm(user, "inventory.acknowledge_stockentry"):
            continue
        if not hasattr(user, "profile"):
            continue
        if user.profile.has_location_access(entry.to_location):
            users.append(user)
    return users


def user_can_manage_correction(user: User, correction: StockCorrectionRequest | None = None) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.groups.filter(name="Central Store Manager").exists():
        return True
    if not user_has_perm(user, "inventory.approve_stock_corrections"):
        return False

    if correction and correction.resolution_type in {
        CorrectionResolutionType.ADDITIONAL_MOVEMENT,
        CorrectionResolutionType.REVERSAL,
    }:
        entry = correction.original_entry
        if (
            entry.entry_type == "ISSUE"
            and entry.from_location_id
            and entry.to_location_id
            and getattr(entry.to_location, "is_store", False)
        ):
            approval_location = entry.to_location
            if correction.resolution_type == CorrectionResolutionType.ADDITIONAL_MOVEMENT:
                approval_location = entry.from_location
            return bool(
                hasattr(user, "profile")
                and user.profile.has_location_access(approval_location)
            )

    return True


def correction_action_users(correction: StockCorrectionRequest) -> list[User]:
    users: list[User] = []
    for user in _active_users_queryset():
        if user_can_manage_correction(user, correction):
            users.append(user)
    return users


def stock_register_visible_users(register: StockRegister) -> list[User]:
    users: list[User] = []
    for user in _active_users_queryset():
        if user.is_superuser:
            users.append(user)
            continue
        if not user_has_perm(user, "inventory.view_stock_registers"):
            continue
        if not hasattr(user, "profile"):
            continue
        if user.profile.get_stock_register_scope_locations().filter(id=register.store_id).exists():
            users.append(user)
    return users


def depreciation_visible_users(*, require_action: bool = False) -> list[User]:
    users: list[User] = []
    required_perm = "inventory.manage_depreciation" if require_action else "inventory.view_depreciation"
    fallback_perm = "inventory.post_depreciation" if require_action else None

    for user in _active_users_queryset():
        if user.is_superuser:
            users.append(user)
            continue
        if user_has_perm(user, required_perm) or (fallback_perm and user_has_perm(user, fallback_perm)):
            users.append(user)
    return users


def notify_inspection_initiated(inspection: InspectionCertificate, actor: User | None) -> NotificationEvent | None:
    stage_perm = INSPECTION_STAGE_PERM_MAP.get(inspection.stage)
    recipients = users_for_inspection_stage(inspection, stage_perm) if stage_perm else inspection_visible_users(inspection)
    stage_label = inspection.get_stage_display()
    return create_notification_event(
        module="inspections",
        kind="inspection.initiated",
        severity=NotificationSeverity.WARNING,
        title=f"Inspection {inspection.contract_no} is ready for {stage_label}",
        message=f"{inspection.contract_no} now needs {stage_label.lower()} input for {inspection.department.name}.",
        users=recipients,
        href=f"/inspections/{inspection.id}",
        entity_type="inspection",
        entity_id=inspection.id,
        actor=actor,
        metadata={"stage": inspection.stage, "department_id": inspection.department_id},
    )


def notify_inspection_submitted_to_central_register(inspection: InspectionCertificate, actor: User | None) -> NotificationEvent | None:
    return create_notification_event(
        module="inspections",
        kind="inspection.submitted_to_central_register",
        severity=NotificationSeverity.WARNING,
        title=f"Inspection {inspection.contract_no} needs Central Register review",
        message=f"{inspection.contract_no} was submitted from departmental stock details and is waiting for Central Register input.",
        users=users_for_inspection_stage(inspection, "inventory.fill_central_register"),
        href=f"/inspections/{inspection.id}",
        entity_type="inspection",
        entity_id=inspection.id,
        actor=actor,
        metadata={"stage": inspection.stage, "department_id": inspection.department_id},
    )


def notify_inspection_submitted_to_finance_review(inspection: InspectionCertificate, actor: User | None) -> NotificationEvent | None:
    return create_notification_event(
        module="inspections",
        kind="inspection.submitted_to_finance_review",
        severity=NotificationSeverity.WARNING,
        title=f"Inspection {inspection.contract_no} is waiting for Finance Review",
        message=f"{inspection.contract_no} has cleared Central Register and is ready for Finance Review.",
        users=users_for_inspection_stage(inspection, "inventory.review_finance"),
        href=f"/inspections/{inspection.id}",
        entity_type="inspection",
        entity_id=inspection.id,
        actor=actor,
        metadata={"stage": inspection.stage, "department_id": inspection.department_id},
    )


def notify_inspection_completed(inspection: InspectionCertificate, actor: User | None) -> NotificationEvent | None:
    return create_notification_event(
        module="inspections",
        kind="inspection.completed",
        severity=NotificationSeverity.INFO,
        title=f"Inspection {inspection.contract_no} completed",
        message=f"{inspection.contract_no} was completed and pushed into downstream stock movement.",
        users=inspection_visible_users(inspection),
        href=f"/inspections/{inspection.id}",
        entity_type="inspection",
        entity_id=inspection.id,
        actor=actor,
        metadata={"stage": inspection.stage, "department_id": inspection.department_id},
    )


def notify_inspection_rejected(inspection: InspectionCertificate, actor: User | None) -> NotificationEvent | None:
    stage_label = inspection.get_rejection_stage_display() if inspection.rejection_stage else "the current stage"
    was_cancelled = inspection.status == "CANCELLED"
    outcome_label = "cancelled" if was_cancelled else "rejected"
    follow_up = (
        "Review the cancellation reason."
        if was_cancelled
        else "Review the rejection reason and resume the certificate when ready."
    )
    return create_notification_event(
        module="inspections",
        kind="inspection.rejected",
        severity=NotificationSeverity.CRITICAL,
        title=f"Inspection {inspection.contract_no} was {outcome_label}",
        message=f"{inspection.contract_no} was {outcome_label} at {stage_label}. {follow_up}",
        users=inspection_visible_users(inspection),
        href=f"/inspections/{inspection.id}",
        entity_type="inspection",
        entity_id=inspection.id,
        actor=actor,
        metadata={"stage": inspection.stage, "rejection_stage": inspection.rejection_stage, "department_id": inspection.department_id},
    )


def notify_stock_entry_pending_ack(entry: StockEntry, actor: User | None = None) -> NotificationEvent | None:
    if entry.status != "PENDING_ACK" or entry.entry_type not in {"RECEIPT", "RETURN"}:
        return None

    target_name = entry.to_location.name if entry.to_location else "the receiving store"
    if entry.entry_type == "RETURN":
        title = f"Return {entry.entry_number} needs acknowledgement"
        message = f"{entry.entry_number} has reached {target_name} and is waiting for return acknowledgement."
    else:
        title = f"Receipt {entry.entry_number} needs acknowledgement"
        message = f"{entry.entry_number} has reached {target_name} and is waiting for acknowledgement."

    return create_notification_event(
        module="stock-entries",
        kind="stock_entry.pending_ack",
        severity=NotificationSeverity.WARNING,
        title=title,
        message=message,
        users=stock_entry_ack_users(entry),
        href=f"/stock-entries/{entry.id}",
        entity_type="stock_entry",
        entity_id=entry.id,
        actor=actor or entry.created_by,
        metadata={"entry_type": entry.entry_type, "status": entry.status},
    )


def notify_stock_entry_acknowledged(entry: StockEntry, actor: User | None) -> NotificationEvent | None:
    recipients = []
    if entry.created_by_id and (not actor or entry.created_by_id != actor.id):
        recipients.append(entry.created_by)
    return create_notification_event(
        module="stock-entries",
        kind="stock_entry.acknowledged",
        severity=NotificationSeverity.INFO,
        title=f"{entry.entry_number} was acknowledged",
        message=f"{entry.entry_number} has been acknowledged and the stock movement is now complete.",
        users=recipients,
        href=f"/stock-entries/{entry.id}",
        entity_type="stock_entry",
        entity_id=entry.id,
        actor=actor,
        metadata={"entry_type": entry.entry_type, "status": entry.status},
    )


def notify_correction_requested(correction: StockCorrectionRequest, actor: User | None) -> NotificationEvent | None:
    return create_notification_event(
        module="stock-entries",
        kind="stock_correction.requested",
        severity=NotificationSeverity.WARNING,
        title=f"Correction requested for {correction.original_entry.entry_number}",
        message=correction.message or "A stock correction now needs approval or follow-up action.",
        users=correction_action_users(correction),
        href=f"/stock-entries/{correction.original_entry_id}",
        entity_type="stock_correction",
        entity_id=correction.id,
        actor=actor,
        metadata={"status": correction.status, "resolution_type": correction.resolution_type},
    )


def notify_correction_approved(correction: StockCorrectionRequest, actor: User | None) -> NotificationEvent | None:
    recipients = [correction.requested_by, *correction_action_users(correction)]
    return create_notification_event(
        module="stock-entries",
        kind="stock_correction.approved",
        severity=NotificationSeverity.INFO,
        title=f"Correction approved for {correction.original_entry.entry_number}",
        message=correction.message or "A stock correction was approved and may now be applied.",
        users=recipients,
        href=f"/stock-entries/{correction.original_entry_id}",
        entity_type="stock_correction",
        entity_id=correction.id,
        actor=actor,
        metadata={"status": correction.status, "resolution_type": correction.resolution_type},
    )


def notify_correction_rejected(correction: StockCorrectionRequest, actor: User | None) -> NotificationEvent | None:
    return create_notification_event(
        module="stock-entries",
        kind="stock_correction.rejected",
        severity=NotificationSeverity.CRITICAL,
        title=f"Correction rejected for {correction.original_entry.entry_number}",
        message=correction.rejection_reason or correction.message or "A stock correction was rejected.",
        users=[correction.requested_by],
        href=f"/stock-entries/{correction.original_entry_id}",
        entity_type="stock_correction",
        entity_id=correction.id,
        actor=actor,
        metadata={"status": correction.status, "resolution_type": correction.resolution_type},
    )


def notify_correction_applied(correction: StockCorrectionRequest, actor: User | None) -> NotificationEvent | None:
    return create_notification_event(
        module="stock-entries",
        kind="stock_correction.applied",
        severity=NotificationSeverity.INFO,
        title=f"Correction applied for {correction.original_entry.entry_number}",
        message=correction.message or "A stock correction was applied and linked movement entries were generated.",
        users=[correction.requested_by],
        href=f"/stock-entries/{correction.original_entry_id}",
        entity_type="stock_correction",
        entity_id=correction.id,
        actor=actor,
        metadata={"status": correction.status, "resolution_type": correction.resolution_type},
    )


def notify_stock_register_closed(register: StockRegister, actor: User | None) -> NotificationEvent | None:
    return create_notification_event(
        module="stock-registers",
        kind="stock_register.closed",
        severity=NotificationSeverity.INFO,
        title=f"Register {register.register_number} was closed",
        message=f"{register.register_number} for {register.store.name} was closed.",
        users=stock_register_visible_users(register),
        href="/stock-registers",
        entity_type="stock_register",
        entity_id=register.id,
        actor=actor,
        metadata={"store_id": register.store_id, "is_active": register.is_active},
    )


def notify_stock_register_reopened(register: StockRegister, actor: User | None) -> NotificationEvent | None:
    return create_notification_event(
        module="stock-registers",
        kind="stock_register.reopened",
        severity=NotificationSeverity.INFO,
        title=f"Register {register.register_number} was reopened",
        message=f"{register.register_number} for {register.store.name} is active again.",
        users=stock_register_visible_users(register),
        href="/stock-registers",
        entity_type="stock_register",
        entity_id=register.id,
        actor=actor,
        metadata={"store_id": register.store_id, "is_active": register.is_active},
    )


def notify_depreciation_run_created(run, actor: User | None) -> NotificationEvent | None:
    return create_notification_event(
        module="depreciation",
        kind="depreciation.run_created",
        severity=NotificationSeverity.INFO,
        title=f"Depreciation run created for FY {run.fiscal_year_label}",
        message=f"A draft depreciation run was created under {run.policy.name}.",
        users=depreciation_visible_users(),
        href="/depreciation",
        entity_type="depreciation_run",
        entity_id=run.id,
        actor=actor,
        metadata={"status": run.status, "fiscal_year_start": run.fiscal_year_start},
    )


def notify_depreciation_run_posted(run, actor: User | None) -> NotificationEvent | None:
    return create_notification_event(
        module="depreciation",
        kind="depreciation.run_posted",
        severity=NotificationSeverity.INFO,
        title=f"Depreciation run posted for FY {run.fiscal_year_label}",
        message=f"The depreciation run under {run.policy.name} was posted successfully.",
        users=depreciation_visible_users(),
        href="/depreciation",
        entity_type="depreciation_run",
        entity_id=run.id,
        actor=actor,
        metadata={"status": run.status, "fiscal_year_start": run.fiscal_year_start},
    )


def notify_depreciation_run_reversed(run, actor: User | None) -> NotificationEvent | None:
    return create_notification_event(
        module="depreciation",
        kind="depreciation.run_reversed",
        severity=NotificationSeverity.CRITICAL,
        title=f"Depreciation run reversed for FY {run.fiscal_year_label}",
        message=f"The posted depreciation run under {run.policy.name} was reversed.",
        users=depreciation_visible_users(),
        href="/depreciation",
        entity_type="depreciation_run",
        entity_id=run.id,
        actor=actor,
        metadata={"status": run.status, "fiscal_year_start": run.fiscal_year_start},
    )


def notify_fixed_asset_capitalized(asset, actor: User | None) -> NotificationEvent | None:
    return create_notification_event(
        module="depreciation",
        kind="depreciation.asset_capitalized",
        severity=NotificationSeverity.INFO,
        title=f"Fixed asset {asset.asset_number} capitalized",
        message=f"{asset.item.name} was capitalized into the fixed asset register.",
        users=depreciation_visible_users(),
        href="/depreciation",
        entity_type="fixed_asset",
        entity_id=asset.id,
        actor=actor,
        metadata={"target_type": asset.target_type, "asset_number": asset.asset_number},
    )


def notify_asset_adjustment_created(adjustment, actor: User | None) -> NotificationEvent | None:
    return create_notification_event(
        module="depreciation",
        kind="depreciation.adjustment_created",
        severity=NotificationSeverity.INFO,
        title=f"Adjustment recorded for {adjustment.asset.asset_number}",
        message=f"A {adjustment.adjustment_type.lower().replace('_', ' ')} adjustment was recorded for {adjustment.asset.item.name}.",
        users=depreciation_visible_users(),
        href="/depreciation",
        entity_type="asset_adjustment",
        entity_id=adjustment.id,
        actor=actor,
        metadata={"adjustment_type": adjustment.adjustment_type, "asset_id": adjustment.asset_id},
    )


def build_user_alerts(user: User) -> list[dict[str, object]]:
    if not user or not user.is_authenticated:
        return []

    alerts: list[AlertRecord] = []

    inspection_scope = _inspection_scope_for_user(user)
    if inspection_scope.exists():
        if user_has_perm(user, "inventory.fill_stock_details"):
            stock_details_count = inspection_scope.filter(stage=InspectionStage.STOCK_DETAILS).count()
            if stock_details_count:
                alerts.append(AlertRecord(
                    key="inspections-stock-details",
                    module="inspections",
                    severity=NotificationSeverity.WARNING,
                    title="Inspection certificates waiting for stock details",
                    message=f"{stock_details_count} inspection certificate{'s' if stock_details_count != 1 else ''} need departmental stock details.",
                    href="/inspections?stage=STOCK_DETAILS",
                    count=stock_details_count,
                    meta={"stage": InspectionStage.STOCK_DETAILS},
                ))

        if user_has_perm(user, "inventory.fill_central_register"):
            central_count = inspection_scope.filter(stage=InspectionStage.CENTRAL_REGISTER).count()
            if central_count:
                alerts.append(AlertRecord(
                    key="inspections-central-register",
                    module="inspections",
                    severity=NotificationSeverity.WARNING,
                    title="Inspection certificates waiting for Central Register",
                    message=f"{central_count} inspection certificate{'s' if central_count != 1 else ''} need Central Register mapping.",
                    href="/inspections?stage=CENTRAL_REGISTER",
                    count=central_count,
                    meta={"stage": InspectionStage.CENTRAL_REGISTER},
                ))

        if user_has_perm(user, "inventory.review_finance"):
            finance_count = inspection_scope.filter(stage=InspectionStage.FINANCE_REVIEW).count()
            if finance_count:
                alerts.append(AlertRecord(
                    key="inspections-finance-review",
                    module="inspections",
                    severity=NotificationSeverity.CRITICAL,
                    title="Inspection certificates waiting for Finance Review",
                    message=f"{finance_count} inspection certificate{'s' if finance_count != 1 else ''} are ready for Finance Review.",
                    href="/inspections?stage=FINANCE_REVIEW",
                    count=finance_count,
                    meta={"stage": InspectionStage.FINANCE_REVIEW},
                ))

    if user_has_perm(user, "inventory.acknowledge_stockentry"):
        ack_scope = _location_access_scope(user)
        pending_ack_count = StockEntry.objects.filter(
            status="PENDING_ACK",
            entry_type__in=["RECEIPT", "RETURN"],
            to_location__in=ack_scope,
        ).count()
        if pending_ack_count:
            alerts.append(AlertRecord(
                key="stock-entries-pending-ack",
                module="stock-entries",
                severity=NotificationSeverity.WARNING,
                title="Stock entries waiting for acknowledgement",
                message=f"{pending_ack_count} stock entr{'ies' if pending_ack_count != 1 else 'y'} need receiver acknowledgement.",
                href="/stock-entries?status=PENDING_ACK",
                count=pending_ack_count,
            ))

    if user_can_manage_correction(user):
        pending_approvals = 0
        approved_to_apply = 0
        corrections = StockCorrectionRequest.objects.select_related(
            "original_entry",
            "original_entry__from_location",
            "original_entry__to_location",
        ).exclude(status__in=[CorrectionStatus.APPLIED, CorrectionStatus.REJECTED, CorrectionStatus.BLOCKED])
        for correction in corrections:
            if not user_can_manage_correction(user, correction):
                continue
            if correction.status == CorrectionStatus.REQUESTED:
                pending_approvals += 1
            elif correction.status == CorrectionStatus.APPROVED:
                approved_to_apply += 1

        if pending_approvals:
            alerts.append(AlertRecord(
                key="stock-entries-correction-approvals",
                module="stock-entries",
                severity=NotificationSeverity.WARNING,
                title="Stock correction approvals pending",
                message=f"{pending_approvals} correction request{'s' if pending_approvals != 1 else ''} need approval.",
                href="/stock-entries",
                count=pending_approvals,
            ))

        if approved_to_apply:
            alerts.append(AlertRecord(
                key="stock-entries-correction-apply",
                module="stock-entries",
                severity=NotificationSeverity.INFO,
                title="Approved stock corrections waiting to be applied",
                message=f"{approved_to_apply} approved correction{'s' if approved_to_apply != 1 else ''} still need the linked movement to be applied.",
                href="/stock-entries",
                count=approved_to_apply,
            ))

    if user_has_perm(user, "inventory.view_items"):
        item_scope = _item_scope_for_user(user)
        item_totals = Item.objects.annotate(
            restricted_total=Coalesce(
                Sum("stock_records__quantity", filter=Q(stock_records__location__in=item_scope)),
                Value(0),
            )
        )
        low_stock_count = item_totals.filter(
            low_stock_threshold__gt=0,
            restricted_total__gt=0,
            restricted_total__lte=F("low_stock_threshold"),
        ).count()
        if low_stock_count:
            alerts.append(AlertRecord(
                key="items-low-stock",
                module="items",
                severity=NotificationSeverity.WARNING,
                title="Items are low on stock",
                message=f"{low_stock_count} catalog item{'s' if low_stock_count != 1 else ''} are at or below the configured low-stock threshold.",
                href=_items_alert_href(stock="low", focus="low-stock"),
                count=low_stock_count,
            ))

        today = timezone.localdate()
        batch_scope = ItemBatch.objects.filter(stock_records__location__in=item_scope).annotate(
            scoped_quantity=Coalesce(
                Sum("stock_records__quantity", filter=Q(stock_records__location__in=item_scope)),
                Value(0),
            )
        ).filter(scoped_quantity__gt=0, expiry_date__isnull=False)
        expired_count = batch_scope.filter(expiry_date__lt=today).count()
        if expired_count:
            alerts.append(AlertRecord(
                key="items-expired-batches",
                module="items",
                severity=NotificationSeverity.CRITICAL,
                title="Batches have expired",
                message=f"{expired_count} tracked batch{'es' if expired_count != 1 else ''} are already expired within your visible stores.",
                href=_items_alert_href(tracking="perishable", focus="expired-batches"),
                count=expired_count,
            ))

        expiring_count = batch_scope.filter(
            expiry_date__gte=today,
            expiry_date__lte=today + timedelta(days=30),
        ).count()
        if expiring_count:
            alerts.append(AlertRecord(
                key="items-expiring-batches",
                module="items",
                severity=NotificationSeverity.WARNING,
                title="Batches are expiring soon",
                message=f"{expiring_count} tracked batch{'es' if expiring_count != 1 else ''} expire within the next 30 days.",
                href=_items_alert_href(tracking="perishable", focus="expiring-batches"),
                count=expiring_count,
            ))

    if user_has_perm(user, "inventory.manage_depreciation") or user_has_perm(user, "inventory.post_depreciation"):
        fixed_asset_category_filter = Q(item__category__category_type=CategoryType.FIXED_ASSET) | Q(
            item__category__parent_category__category_type=CategoryType.FIXED_ASSET
        )
        uncapitalized_instances = ItemInstance.objects.filter(
            fixed_asset_category_filter,
            fixed_asset_entry__isnull=True,
        ).count()
        uncapitalized_batches = ItemBatch.objects.filter(
            fixed_asset_category_filter,
            item__category__tracking_type=TrackingType.QUANTITY,
            fixed_asset_entry__isnull=True,
        ).annotate(quantity=Coalesce(Sum("stock_records__quantity"), Value(0))).filter(quantity__gt=0).count()
        uncapitalized_total = uncapitalized_instances + uncapitalized_batches
        if uncapitalized_total:
            alerts.append(AlertRecord(
                key="depreciation-uncapitalized",
                module="depreciation",
                severity=NotificationSeverity.WARNING,
                title="Fixed assets are waiting for capitalization",
                message=f"{uncapitalized_total} fixed-asset record{'s' if uncapitalized_total != 1 else ''} still need capitalization in the depreciation register.",
                href="/depreciation",
                count=uncapitalized_total,
            ))

    return [asdict(alert) for alert in sorted(
        alerts,
        key=lambda alert: (
            SEVERITY_SORT_ORDER.get(alert.severity, 99),
            alert.module,
            -alert.count,
            alert.title,
        ),
    )]


def build_notification_summary(user: User) -> dict[str, object]:
    alerts = build_user_alerts(user)
    unread_notifications = UserNotification.objects.filter(user=user, is_read=False).count()
    modules: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "critical": 0})
    open_alerts = 0
    for alert in alerts:
        open_alerts += 1
        module_name = str(alert.get("module") or "general")
        modules[module_name]["count"] += 1
        if alert.get("severity") == NotificationSeverity.CRITICAL:
            modules[module_name]["critical"] += 1

    return {
        "unread_notifications": unread_notifications,
        "open_alerts": open_alerts,
        "modules": dict(modules),
    }
