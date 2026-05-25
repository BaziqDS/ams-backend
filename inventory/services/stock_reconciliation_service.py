from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from ..models.allocation_model import AllocationStatus, StockAllocation
from ..models.category_model import TrackingType
from ..models.correction_model import StockReconciliationFinding, StockReconciliationRun
from ..models.instance_model import InstanceStatus, ItemInstance
from ..models.stock_record_model import StockRecord
from ..models.stockentry_model import StockEntry, StockEntryItem


@dataclass
class ReconciliationFindingDraft:
    finding_type: str
    severity: str
    repairable: bool
    message: str
    before: dict
    after: dict
    stock_record_id: int | None = None
    stock_entry_id: int | None = None
    stock_entry_item_id: int | None = None
    item_id: int | None = None
    location_id: int | None = None
    item_instance_id: int | None = None
    model_finding: StockReconciliationFinding | None = field(default=None, repr=False)

    @property
    def has_changes(self):
        return self.before != self.after


class StockReconciliationService:
    """
    Rebuilds repairable summary counters from auditable source records and logs
    every dry-run/apply decision. Normal writes should be protected by
    StockMovementService; this service is the historical-data safety net.
    """

    @classmethod
    def run(
        cls,
        *,
        item_id=None,
        location_id=None,
        apply=False,
        requested_by=None,
        reason='',
        void_duplicate_pending_entries=False,
    ):
        mode = 'APPLY' if apply else 'DRY_RUN'
        with transaction.atomic():
            run = StockReconciliationRun.objects.create(
                mode=mode,
                reason=reason or '',
                scope_item_id=item_id,
                scope_location_id=location_id,
                requested_by=requested_by if getattr(requested_by, 'is_authenticated', False) else None,
            )

            applied_count = 0
            if apply:
                drafts = [
                    *cls._duplicate_active_instance_findings(item_id=item_id, location_id=location_id),
                    *cls._quantity_pending_over_issue_findings(item_id=item_id, location_id=location_id),
                    *cls._individual_movement_instance_mismatch_findings(item_id=item_id, location_id=location_id),
                ]
                cls._persist_findings(run, drafts)
                applied_count += cls._apply_duplicate_voids(
                    drafts,
                    requested_by=requested_by,
                    enabled=void_duplicate_pending_entries,
                )
                applied_count += cls._apply_quantity_pending_over_issue_voids(
                    drafts,
                    requested_by=requested_by,
                )
                # Recompute stock summary findings after duplicate voids so
                # counter repairs use the latest entry statuses.
                post_void_summary_drafts = cls._stock_record_summary_findings(
                    item_id=item_id,
                    location_id=location_id,
                )
                cls._persist_findings(run, post_void_summary_drafts)
                applied_count += cls._apply_summary_repairs(post_void_summary_drafts)
                drafts = [*drafts, *post_void_summary_drafts]
            else:
                drafts = cls._collect_findings(item_id=item_id, location_id=location_id)
                cls._persist_findings(run, drafts)

            run.findings_count = run.findings.count()
            run.applied_count = applied_count
            run.completed_at = timezone.now()
            run.save(update_fields=['findings_count', 'applied_count', 'completed_at'])
            return run

    @classmethod
    def reconcile_individual_records(cls, *, item_id=None, location_id=None, apply=False):
        run = cls.run(item_id=item_id, location_id=location_id, apply=apply)
        return list(run.findings.all())

    @classmethod
    def _collect_findings(cls, *, item_id=None, location_id=None):
        return [
            *cls._stock_record_summary_findings(item_id=item_id, location_id=location_id),
            *cls._duplicate_active_instance_findings(item_id=item_id, location_id=location_id),
            *cls._quantity_pending_over_issue_findings(item_id=item_id, location_id=location_id),
            *cls._individual_movement_instance_mismatch_findings(item_id=item_id, location_id=location_id),
        ]

    @classmethod
    def _stock_record_summary_findings(cls, *, item_id=None, location_id=None):
        findings = []
        for record in cls._stock_records(item_id=item_id, location_id=location_id):
            expected = cls._expected_counts(record)
            before = {
                'quantity': record.quantity,
                'in_transit_quantity': record.in_transit_quantity,
                'allocated_quantity': record.allocated_quantity,
            }
            after = {
                'quantity': expected['quantity'],
                'in_transit_quantity': expected['in_transit_quantity'],
                'allocated_quantity': expected['allocated_quantity'],
            }
            if before == after:
                continue
            findings.append(ReconciliationFindingDraft(
                finding_type='STOCK_RECORD_SUMMARY_MISMATCH',
                severity='CRITICAL',
                repairable=True,
                message=f"StockRecord {record.id} summary counters do not match source records.",
                stock_record_id=record.id,
                item_id=record.item_id,
                location_id=record.location_id,
                before=before,
                after=after,
            ))
        return findings

    @staticmethod
    def _stock_records(*, item_id=None, location_id=None):
        queryset = (
            StockRecord.objects
            .select_related('item', 'item__category', 'location')
            .order_by('id')
        )
        if item_id:
            queryset = queryset.filter(item_id=item_id)
        if location_id:
            queryset = queryset.filter(location_id=location_id)
        return queryset

    @classmethod
    def _expected_counts(cls, record):
        if record.item.category.get_tracking_type() == TrackingType.INDIVIDUAL:
            return cls._expected_individual_counts(record)
        return cls._expected_quantity_counts(record)

    @staticmethod
    def _expected_individual_counts(record):
        available_count = ItemInstance.objects.filter(
            item=record.item,
            current_location=record.location,
            status=InstanceStatus.AVAILABLE,
            is_active=True,
        ).count()
        in_transit_instance_ids = (
            StockEntryItem.objects
            .filter(
                item=record.item,
                batch=record.batch,
                stock_entry__entry_type='ISSUE',
                stock_entry__status='PENDING_ACK',
                stock_entry__from_location=record.location,
                instances__isnull=False,
            )
            .values_list('instances', flat=True)
            .distinct()
        )
        in_transit_count = ItemInstance.objects.filter(
            id__in=in_transit_instance_ids,
            item=record.item,
            status=InstanceStatus.IN_TRANSIT,
            is_active=True,
        ).count()
        allocated_quantity = (
            StockAllocation.objects
            .filter(
                item=record.item,
                batch=record.batch,
                source_location=record.location,
                status=AllocationStatus.ALLOCATED,
            )
            .aggregate(total=Sum('quantity'))['total']
            or 0
        )
        return {
            'quantity': available_count + in_transit_count + allocated_quantity,
            'in_transit_quantity': in_transit_count,
            'allocated_quantity': allocated_quantity,
        }

    @staticmethod
    def _expected_quantity_counts(record):
        in_transit_quantity = (
            StockEntryItem.objects
            .filter(
                item=record.item,
                batch=record.batch,
                stock_entry__entry_type='ISSUE',
                stock_entry__status='PENDING_ACK',
                stock_entry__from_location=record.location,
            )
            .aggregate(total=Sum('quantity'))['total']
            or 0
        )
        allocated_quantity = (
            StockAllocation.objects
            .filter(
                item=record.item,
                batch=record.batch,
                source_location=record.location,
                status=AllocationStatus.ALLOCATED,
            )
            .aggregate(total=Sum('quantity'))['total']
            or 0
        )
        # For quantity-tracked items, physical total quantity can include
        # opening balances/imports that are not reconstructable from movement
        # history. Repair only derived counters.
        return {
            'quantity': record.quantity,
            'in_transit_quantity': in_transit_quantity,
            'allocated_quantity': allocated_quantity,
        }

    @classmethod
    def _duplicate_active_instance_findings(cls, *, item_id=None, location_id=None):
        through = StockEntryItem.instances.through
        duplicate_instance_ids = (
            through.objects
            .filter(
                stockentryitem__stock_entry__entry_type='ISSUE',
                stockentryitem__stock_entry__status='PENDING_ACK',
            )
            .values('iteminstance_id')
            .annotate(link_count=Count('stockentryitem_id'))
            .filter(link_count__gt=1)
            .values_list('iteminstance_id', flat=True)
        )
        findings = []
        for instance_id in duplicate_instance_ids:
            links = (
                StockEntryItem.objects
                .filter(
                    instances__id=instance_id,
                    stock_entry__entry_type='ISSUE',
                    stock_entry__status='PENDING_ACK',
                )
                .select_related('stock_entry', 'item', 'stock_entry__from_location')
                .order_by('stock_entry__created_at', 'stock_entry_id', 'id')
            )
            if item_id:
                links = links.filter(item_id=item_id)
            if location_id:
                links = links.filter(stock_entry__from_location_id=location_id)
            links = list(links)
            if len(links) <= 1:
                continue
            keeper = links[0]
            for duplicate in links[1:]:
                findings.append(ReconciliationFindingDraft(
                    finding_type='DUPLICATE_ACTIVE_INSTANCE_RESERVATION',
                    severity='CRITICAL',
                    repairable=True,
                    message=(
                        f"Instance {instance_id} is reserved by multiple pending issue entries; "
                        f"entry {keeper.stock_entry.entry_number} is kept and "
                        f"{duplicate.stock_entry.entry_number} can be voided."
                    ),
                    stock_entry_id=duplicate.stock_entry_id,
                    stock_entry_item_id=duplicate.id,
                    item_id=duplicate.item_id,
                    location_id=duplicate.stock_entry.from_location_id,
                    item_instance_id=instance_id,
                    before={
                        'duplicate_entry_id': duplicate.stock_entry_id,
                        'duplicate_entry_status': duplicate.stock_entry.status,
                        'kept_entry_id': keeper.stock_entry_id,
                    },
                    after={
                        'duplicate_entry_id': duplicate.stock_entry_id,
                        'duplicate_entry_status': 'VOIDED',
                        'kept_entry_id': keeper.stock_entry_id,
                    },
                ))
        return findings

    @classmethod
    def _quantity_pending_over_issue_findings(cls, *, item_id=None, location_id=None):
        findings = []
        for record in cls._stock_records(item_id=item_id, location_id=location_id):
            if record.item.category.get_tracking_type() == TrackingType.INDIVIDUAL:
                continue

            capacity = max(0, record.quantity - record.allocated_quantity)
            pending_entries = (
                StockEntry.objects
                .filter(
                    entry_type='ISSUE',
                    status='PENDING_ACK',
                    from_location=record.location,
                    items__item=record.item,
                    items__batch=record.batch,
                )
                .annotate(
                    pending_quantity=Sum(
                        'items__quantity',
                        filter=Q(items__item=record.item, items__batch=record.batch),
                    )
                )
                .select_related('from_location')
                .order_by('created_at', 'id')
            )

            running_quantity = 0
            for entry in pending_entries:
                entry_quantity = entry.pending_quantity or 0
                before_total = running_quantity + entry_quantity
                if before_total <= capacity:
                    running_quantity = before_total
                    continue

                duplicate_line_count = entry.items.filter(item=record.item, batch=record.batch).count()
                findings.append(ReconciliationFindingDraft(
                    finding_type='QUANTITY_PENDING_OVER_ISSUE',
                    severity='CRITICAL',
                    repairable=True,
                    message=(
                        f"Pending issue {entry.entry_number} reserves {entry_quantity} "
                        f"{record.item.name} from {record.location.name}, causing pending "
                        f"quantity {before_total} to exceed source capacity {capacity}."
                    ),
                    stock_record_id=record.id,
                    stock_entry_id=entry.id,
                    item_id=record.item_id,
                    location_id=record.location_id,
                    before={
                        'entry_id': entry.id,
                        'entry_status': entry.status,
                        'entry_pending_quantity': entry_quantity,
                        'pending_quantity_before_entry': running_quantity,
                        'pending_quantity_with_entry': before_total,
                        'source_quantity': record.quantity,
                        'source_allocated_quantity': record.allocated_quantity,
                        'source_capacity': capacity,
                        'duplicate_line_count': duplicate_line_count,
                    },
                    after={
                        'entry_id': entry.id,
                        'entry_status': 'VOIDED',
                        'remaining_pending_quantity': running_quantity,
                        'source_capacity': capacity,
                    },
                ))
        return findings

    @staticmethod
    def _individual_movement_instance_mismatch_findings(*, item_id=None, location_id=None):
        queryset = (
            StockEntryItem.objects
            .filter(
                item__category__tracking_type=TrackingType.INDIVIDUAL,
                stock_entry__status__in=['PENDING_ACK', 'COMPLETED'],
            )
            .select_related('stock_entry', 'item', 'stock_entry__from_location')
            .annotate(instance_count=Count('instances', distinct=True))
            .exclude(instance_count=F('quantity'))
            .order_by('id')
        )
        if item_id:
            queryset = queryset.filter(item_id=item_id)
        if location_id:
            queryset = queryset.filter(stock_entry__from_location_id=location_id)
        return [
            ReconciliationFindingDraft(
                finding_type='INDIVIDUAL_MOVEMENT_INSTANCE_MISMATCH',
                severity='CRITICAL',
                repairable=False,
                message=(
                    f"Individual-tracked entry item {entry_item.id} has quantity "
                    f"{entry_item.quantity} but {entry_item.instance_count} linked instance(s)."
                ),
                stock_entry_id=entry_item.stock_entry_id,
                stock_entry_item_id=entry_item.id,
                item_id=entry_item.item_id,
                location_id=entry_item.stock_entry.from_location_id,
                before={'quantity': entry_item.quantity, 'instance_count': entry_item.instance_count},
                after={'manual_review_required': True},
            )
            for entry_item in queryset
        ]

    @staticmethod
    def _persist_findings(run, drafts):
        for draft in drafts:
            if draft.model_finding is not None:
                continue
            draft.model_finding = StockReconciliationFinding.objects.create(
                run=run,
                finding_type=draft.finding_type,
                severity=draft.severity,
                repairable=draft.repairable,
                applied=False,
                message=draft.message,
                stock_record_id=draft.stock_record_id,
                stock_entry_id=draft.stock_entry_id,
                stock_entry_item_id=draft.stock_entry_item_id,
                item_id=draft.item_id,
                location_id=draft.location_id,
                item_instance_id=draft.item_instance_id,
                before=draft.before,
                after=draft.after,
            )

    @classmethod
    def _apply_duplicate_voids(cls, drafts, *, requested_by=None, enabled=False):
        if not enabled:
            return 0

        applied_count = 0
        voided_entry_ids = set()
        for draft in drafts:
            if draft.finding_type != 'DUPLICATE_ACTIVE_INSTANCE_RESERVATION':
                continue
            if not draft.stock_entry_id or draft.stock_entry_id in voided_entry_ids:
                continue
            entry = StockEntry.objects.select_for_update().filter(
                id=draft.stock_entry_id,
                status='PENDING_ACK',
            ).first()
            if not entry:
                continue
            entry.status = 'VOIDED'
            entry.void_reason = 'Duplicate active instance reservation detected by stock reconciliation.'
            entry.voided_by = requested_by if getattr(requested_by, 'is_authenticated', False) else None
            entry.voided_at = timezone.now()
            entry.save(update_fields=['status', 'void_reason', 'voided_by', 'voided_at', 'updated_at'])
            voided_entry_ids.add(entry.id)
            if draft.model_finding:
                draft.model_finding.applied = True
                draft.model_finding.save(update_fields=['applied'])
            applied_count += 1
        return applied_count

    @classmethod
    def _apply_quantity_pending_over_issue_voids(cls, drafts, *, requested_by=None):
        applied_count = 0
        voided_entry_ids = set()
        for draft in drafts:
            if draft.finding_type != 'QUANTITY_PENDING_OVER_ISSUE':
                continue
            if not draft.stock_entry_id or draft.stock_entry_id in voided_entry_ids:
                continue
            entry = StockEntry.objects.select_for_update().filter(
                id=draft.stock_entry_id,
                status='PENDING_ACK',
            ).first()
            if not entry:
                continue

            cls._void_pending_entry(
                entry,
                requested_by=requested_by,
                reason='Pending issue exceeds available quantity detected by stock reconciliation.',
            )
            voided_entry_ids.add(entry.id)
            if draft.model_finding:
                draft.model_finding.applied = True
                draft.model_finding.save(update_fields=['applied'])
            applied_count += 1
        return applied_count

    @staticmethod
    def _void_pending_entry(entry, *, requested_by=None, reason=''):
        now = timezone.now()
        voided_by = requested_by if getattr(requested_by, 'is_authenticated', False) else None
        StockEntry.objects.filter(id=entry.id, status='PENDING_ACK').update(
            status='VOIDED',
            void_reason=reason,
            voided_by=voided_by,
            voided_at=now,
            updated_at=now,
        )
        entry.items.update(is_in_transit_recorded=False)
        StockEntry.objects.filter(reference_entry=entry, status='PENDING_ACK').update(
            status='VOIDED',
            void_reason=f"Parent {entry.entry_number} was voided by stock reconciliation.",
            voided_by=voided_by,
            voided_at=now,
            updated_at=now,
        )

    @staticmethod
    def _apply_summary_repairs(drafts):
        applied_count = 0
        for draft in drafts:
            if draft.finding_type != 'STOCK_RECORD_SUMMARY_MISMATCH' or not draft.stock_record_id:
                continue
            StockRecord.objects.filter(id=draft.stock_record_id).update(
                quantity=draft.after['quantity'],
                in_transit_quantity=draft.after['in_transit_quantity'],
                allocated_quantity=draft.after['allocated_quantity'],
            )
            if draft.model_finding:
                draft.model_finding.applied = True
                draft.model_finding.save(update_fields=['applied'])
            applied_count += 1
        return applied_count
