from dataclasses import dataclass

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from ..models.allocation_model import AllocationStatus, StockAllocation
from ..models.correction_model import (
    CorrectionResolutionType,
    CorrectionStatus,
    StockCorrectionLine,
    StockCorrectionRequest,
)
from ..models.history_model import MovementAction, MovementHistory
from ..models.instance_model import ItemInstance
from ..models.category_model import TrackingType
from ..models.stock_record_model import StockRecord
from ..models.stockentry_model import StockEntry, StockEntryItem


@dataclass
class CorrectionLineInput:
    entry_item: StockEntryItem
    original_quantity: int
    corrected_quantity: int
    delta: int
    affected_instance_ids: list[int]
    resolution_type: str
    message: str


def _is_store_transfer(entry: StockEntry) -> bool:
    return bool(
        entry.entry_type == 'ISSUE'
        and entry.from_location
        and entry.to_location
        and entry.to_location.is_store
    )


def _is_allocation_issue(entry: StockEntry) -> bool:
    return bool(
        entry.entry_type == 'ISSUE'
        and entry.from_location
        and (entry.issued_to or (entry.to_location and not entry.to_location.is_store))
    )


def _is_allocation_return(entry: StockEntry) -> bool:
    return bool(
        entry.entry_type == 'RECEIPT'
        and entry.to_location
        and (entry.issued_to or (entry.from_location and not entry.from_location.is_store))
    )


def _effective_original_quantity(entry_item: StockEntryItem) -> int:
    entry = entry_item.stock_entry
    if _is_store_transfer(entry):
        receipt_item = StockEntryItem.objects.filter(
            stock_entry__reference_entry=entry,
            stock_entry__entry_type='RECEIPT',
            item=entry_item.item,
            batch=entry_item.batch,
        ).order_by('id').first()
        if receipt_item and receipt_item.accepted_quantity is not None:
            return receipt_item.accepted_quantity
    if entry_item.accepted_quantity is not None:
        return entry_item.accepted_quantity
    return entry_item.quantity


def _available_quantity(item, batch, location) -> int:
    try:
        return StockRecord.objects.get(item=item, batch=batch, location=location).available_quantity
    except StockRecord.DoesNotExist:
        return 0


def _active_allocation_quantity(entry: StockEntry, entry_item: StockEntryItem) -> int:
    filters = {
        'item': entry_item.item,
        'batch': entry_item.batch,
        'source_location': entry.from_location,
        'status': AllocationStatus.ALLOCATED,
    }
    if entry.issued_to:
        filters['allocated_to_person'] = entry.issued_to
    else:
        filters['allocated_to_location'] = entry.to_location
    return StockAllocation.objects.filter(**filters).aggregate(total=Sum('quantity'))['total'] or 0


def _active_return_allocation_quantity(entry: StockEntry, entry_item: StockEntryItem) -> int:
    filters = {
        'item': entry_item.item,
        'batch': entry_item.batch,
        'source_location': entry.to_location,
        'status': AllocationStatus.ALLOCATED,
    }
    if entry.issued_to:
        filters['allocated_to_person'] = entry.issued_to
    else:
        filters['allocated_to_location'] = entry.from_location
    return StockAllocation.objects.filter(**filters).aggregate(total=Sum('quantity'))['total'] or 0


def _line_from_payload(entry: StockEntry, raw_line) -> CorrectionLineInput:
    try:
        entry_item_id = int(raw_line.get('id'))
    except (TypeError, ValueError):
        raise serializers.ValidationError({'lines': 'Each correction line must include a valid stock entry item id.'})

    try:
        corrected_quantity = int(raw_line.get('corrected_quantity'))
    except (TypeError, ValueError):
        raise serializers.ValidationError({'lines': 'Each correction line must include a valid corrected quantity.'})

    if corrected_quantity < 0:
        raise serializers.ValidationError({'lines': 'Corrected quantity cannot be negative.'})

    try:
        entry_item = entry.items.select_related('item', 'batch').get(id=entry_item_id)
    except StockEntryItem.DoesNotExist:
        raise serializers.ValidationError({'lines': f'Line {entry_item_id} does not belong to this stock entry.'})

    raw_instances = raw_line.get('instances') or []
    try:
        affected_instance_ids = [int(value) for value in raw_instances]
    except (TypeError, ValueError):
        raise serializers.ValidationError({'lines': 'Affected instances must be valid ids.'})

    original_quantity = _effective_original_quantity(entry_item)
    delta = corrected_quantity - original_quantity
    resolution_type = CorrectionResolutionType.NO_CHANGE
    message = 'No stock movement is required for this line.'

    if delta == 0:
        return CorrectionLineInput(
            entry_item=entry_item,
            original_quantity=original_quantity,
            corrected_quantity=corrected_quantity,
            delta=delta,
            affected_instance_ids=affected_instance_ids,
            resolution_type=resolution_type,
            message=message,
        )

    if _is_store_transfer(entry):
        if delta > 0:
            resolution_type = CorrectionResolutionType.ADDITIONAL_MOVEMENT
            message = f'Send additional quantity {delta}.'
        else:
            reversal_qty = abs(delta)
            available = _available_quantity(entry_item.item, entry_item.batch, entry.to_location)
            if available < reversal_qty:
                resolution_type = CorrectionResolutionType.BLOCKED
                message = 'Cannot reverse because stock appears to have moved onward or is no longer available.'
            else:
                resolution_type = CorrectionResolutionType.REVERSAL
                message = f'Return excess quantity {reversal_qty}.'
    elif _is_allocation_issue(entry):
        if delta > 0:
            resolution_type = CorrectionResolutionType.ALLOCATION_INCREASE
            message = f'Allocate additional quantity {delta}.'
        else:
            reduction_qty = abs(delta)
            active_quantity = _active_allocation_quantity(entry, entry_item)
            if active_quantity < reduction_qty:
                resolution_type = CorrectionResolutionType.BLOCKED
                message = 'Cannot reduce allocation because the allocated stock is no longer fully active.'
            else:
                resolution_type = CorrectionResolutionType.ALLOCATION_REDUCTION
                message = f'Reduce allocation by {reduction_qty}.'
    elif _is_allocation_return(entry):
        if delta > 0:
            active_quantity = _active_return_allocation_quantity(entry, entry_item)
            if active_quantity < delta:
                resolution_type = CorrectionResolutionType.BLOCKED
                message = 'Cannot record additional return because active allocation quantity is insufficient.'
            else:
                resolution_type = CorrectionResolutionType.RETURN_INCREASE
                message = f'Record additional returned quantity {delta}.'
        else:
            reduction_qty = abs(delta)
            available = _available_quantity(entry_item.item, entry_item.batch, entry.to_location)
            if available < reduction_qty:
                resolution_type = CorrectionResolutionType.BLOCKED
                message = 'Cannot reduce return because stock is no longer available at the receiving store.'
            else:
                resolution_type = CorrectionResolutionType.RETURN_REDUCTION
                message = f'Reduce returned quantity by {reduction_qty}.'
    else:
        resolution_type = CorrectionResolutionType.ADJUSTMENT_REQUIRED
        message = 'This entry type requires approved stock adjustment.'

    category = getattr(entry_item.item, 'category', None)
    if delta != 0 and category and category.get_tracking_type() == TrackingType.INDIVIDUAL:
        required_count = abs(delta)
        if len(affected_instance_ids) != required_count:
            resolution_type = CorrectionResolutionType.BLOCKED
            message = f'Select exactly {required_count} affected instance(s) for this individual-tracked correction.'
        else:
            selected_instances = ItemInstance.objects.filter(id__in=affected_instance_ids, item=entry_item.item)
            if selected_instances.count() != required_count:
                resolution_type = CorrectionResolutionType.BLOCKED
                message = 'Affected instances must belong to the corrected item.'
            elif resolution_type in {CorrectionResolutionType.ADDITIONAL_MOVEMENT, CorrectionResolutionType.ALLOCATION_INCREASE}:
                invalid = selected_instances.exclude(current_location=entry.from_location, status='AVAILABLE').exists()
                if invalid:
                    resolution_type = CorrectionResolutionType.BLOCKED
                    message = 'Additional individual instances must be available at the source store.'
            elif resolution_type == CorrectionResolutionType.REVERSAL:
                invalid = selected_instances.exclude(current_location=entry.to_location, status='AVAILABLE').exists()
                if invalid:
                    resolution_type = CorrectionResolutionType.BLOCKED
                    message = 'Reversed individual instances must still be available at the destination store.'
            elif resolution_type == CorrectionResolutionType.ALLOCATION_REDUCTION:
                invalid = selected_instances.exclude(status='ALLOCATED').exists()
                if invalid:
                    resolution_type = CorrectionResolutionType.BLOCKED
                    message = 'Reduced allocation instances must still be allocated.'
            elif resolution_type == CorrectionResolutionType.RETURN_INCREASE:
                invalid = selected_instances.exclude(status='ALLOCATED').exists()
                if invalid:
                    resolution_type = CorrectionResolutionType.BLOCKED
                    message = 'Additional returned instances must still be allocated.'
            elif resolution_type == CorrectionResolutionType.RETURN_REDUCTION:
                invalid = selected_instances.exclude(current_location=entry.to_location, status='AVAILABLE').exists()
                if invalid:
                    resolution_type = CorrectionResolutionType.BLOCKED
                    message = 'Reduced return instances must still be available at the receiving store.'

    return CorrectionLineInput(
        entry_item=entry_item,
        original_quantity=original_quantity,
        corrected_quantity=corrected_quantity,
        delta=delta,
        affected_instance_ids=affected_instance_ids,
        resolution_type=resolution_type,
        message=message,
    )


def build_correction_preview(entry: StockEntry, payload) -> dict:
    if entry.status != 'COMPLETED':
        raise serializers.ValidationError({'detail': 'Only completed entries can be corrected. Cancel pending entries instead.'})

    raw_lines = payload.get('lines') or []
    if not raw_lines:
        raise serializers.ValidationError({'lines': 'At least one correction line is required.'})

    lines = [_line_from_payload(entry, raw_line) for raw_line in raw_lines]
    non_zero_lines = [line for line in lines if line.delta != 0]
    resolution_types = {line.resolution_type for line in non_zero_lines}

    if not non_zero_lines:
        resolution_type = CorrectionResolutionType.NO_CHANGE
        message = 'No stock movement is required.'
    elif CorrectionResolutionType.BLOCKED in resolution_types:
        resolution_type = CorrectionResolutionType.BLOCKED
        message = next(line.message for line in non_zero_lines if line.resolution_type == CorrectionResolutionType.BLOCKED)
    elif CorrectionResolutionType.ADJUSTMENT_REQUIRED in resolution_types:
        resolution_type = CorrectionResolutionType.ADJUSTMENT_REQUIRED
        message = next(line.message for line in non_zero_lines if line.resolution_type == CorrectionResolutionType.ADJUSTMENT_REQUIRED)
    elif len(resolution_types) == 1:
        resolution_type = next(iter(resolution_types))
        message = non_zero_lines[0].message
    else:
        resolution_type = CorrectionResolutionType.MIXED
        message = 'Multiple correction actions will be applied.'

    return {
        'entry': entry,
        'resolution_type': resolution_type,
        'message': message,
        'lines': lines,
    }


def _create_issue_from_lines(entry, correction, lines, *, from_location, to_location, issued_to=None, reference_purpose, status):
    generated = StockEntry.objects.create(
        entry_type='ISSUE',
        from_location=from_location,
        to_location=to_location,
        issued_to=issued_to,
        status=status,
        reference_entry=entry,
        reference_purpose=reference_purpose,
        remarks=f"Generated from correction {correction.id}: {correction.reason}",
        purpose=entry.purpose,
        created_by=correction.requested_by,
    )

    for line in lines:
        qty = abs(line.delta)
        if qty <= 0:
            continue
        generated_item = StockEntryItem.objects.create(
            stock_entry=generated,
            item=line.entry_item.item,
            batch=line.entry_item.batch,
            quantity=qty,
            stock_register=line.entry_item.stock_register,
            page_number=line.entry_item.page_number,
        )
        if line.affected_instance_ids:
            generated_item.instances.set(ItemInstance.objects.filter(id__in=line.affected_instance_ids))

    correction.generated_entries.add(generated)
    return generated


def _create_receipt_from_lines(entry, correction, lines, *, from_location, to_location, issued_to=None, reference_purpose, status):
    generated = StockEntry.objects.create(
        entry_type='RECEIPT',
        from_location=from_location,
        to_location=to_location,
        issued_to=issued_to,
        status=status,
        reference_entry=entry,
        reference_purpose=reference_purpose,
        remarks=f"Generated from correction {correction.id}: {correction.reason}",
        purpose=entry.purpose,
        created_by=correction.requested_by,
    )

    for line in lines:
        qty = abs(line.delta)
        if qty <= 0:
            continue
        generated_item = StockEntryItem.objects.create(
            stock_entry=generated,
            item=line.entry_item.item,
            batch=line.entry_item.batch,
            quantity=qty,
            stock_register=line.entry_item.stock_register,
            page_number=line.entry_item.page_number,
        )
        if line.affected_instance_ids:
            generated_item.instances.set(ItemInstance.objects.filter(id__in=line.affected_instance_ids))

    correction.generated_entries.add(generated)
    return generated


def _apply_additional_movement(entry, correction, lines):
    positive_lines = [line for line in lines if line.delta > 0]
    if not positive_lines:
        return
    _create_issue_from_lines(
        entry,
        correction,
        positive_lines,
        from_location=entry.from_location,
        to_location=entry.to_location,
        reference_purpose='ADDITIONAL_MOVEMENT',
        status='PENDING_ACK',
    )


def _apply_reversal(entry, correction, lines):
    negative_lines = [line for line in lines if line.delta < 0]
    if not negative_lines:
        return
    _create_issue_from_lines(
        entry,
        correction,
        negative_lines,
        from_location=entry.to_location,
        to_location=entry.from_location,
        reference_purpose='REVERSAL',
        status='PENDING_ACK',
    )


def _apply_allocation_increase(entry, correction, lines):
    positive_lines = [line for line in lines if line.delta > 0]
    if not positive_lines:
        return
    _create_issue_from_lines(
        entry,
        correction,
        positive_lines,
        from_location=entry.from_location,
        to_location=entry.to_location,
        issued_to=entry.issued_to,
        reference_purpose='ADDITIONAL_MOVEMENT',
        status='COMPLETED',
    )


def _reduce_allocations(entry, line):
    remaining = abs(line.delta)
    filters = {
        'item': line.entry_item.item,
        'batch': line.entry_item.batch,
        'source_location': entry.from_location,
        'status': AllocationStatus.ALLOCATED,
    }
    if entry.issued_to:
        filters['allocated_to_person'] = entry.issued_to
    else:
        filters['allocated_to_location'] = entry.to_location

    for allocation in StockAllocation.objects.filter(**filters).order_by('allocated_at', 'id'):
        if remaining <= 0:
            break
        reduce_qty = min(allocation.quantity, remaining)
        if reduce_qty == allocation.quantity:
            allocation.status = AllocationStatus.RETURNED
            allocation.return_date = timezone.now()
        else:
            allocation.quantity -= reduce_qty
        allocation.save()
        remaining -= reduce_qty

        MovementHistory.objects.create(
            item=line.entry_item.item,
            batch=line.entry_item.batch,
            action=MovementAction.RETURN,
            to_location=entry.from_location,
            quantity=reduce_qty,
            stock_entry=entry,
            allocation=allocation,
            performed_by=entry.created_by,
            remarks=f"Allocation reduced by correction for {entry.entry_number}",
        )

    if remaining > 0:
        raise serializers.ValidationError({'detail': 'Cannot reduce allocation because active allocation quantity is insufficient.'})

    StockRecord.update_balance(
        line.entry_item.item,
        entry.from_location,
        batch=line.entry_item.batch,
        allocated_change=line.delta,
    )

    if line.affected_instance_ids:
        ItemInstance.objects.filter(id__in=line.affected_instance_ids).update(
            current_location=entry.from_location,
            status='AVAILABLE',
        )


def _apply_allocation_reduction(entry, lines):
    for line in lines:
        if line.delta < 0:
            _reduce_allocations(entry, line)


def _apply_return_increase(entry, correction, lines):
    positive_lines = [line for line in lines if line.delta > 0]
    if not positive_lines:
        return
    _create_receipt_from_lines(
        entry,
        correction,
        positive_lines,
        from_location=entry.from_location,
        to_location=entry.to_location,
        issued_to=entry.issued_to,
        reference_purpose='ADDITIONAL_MOVEMENT',
        status='PENDING_ACK',
    )


def _apply_return_reduction(entry, correction, lines):
    negative_lines = [line for line in lines if line.delta < 0]
    if not negative_lines:
        return
    _create_issue_from_lines(
        entry,
        correction,
        negative_lines,
        from_location=entry.to_location,
        to_location=entry.from_location,
        issued_to=entry.issued_to,
        reference_purpose='REVERSAL',
        status='COMPLETED',
    )


def _serialize_correction(correction: StockCorrectionRequest) -> dict:
    return {
        'id': correction.id,
        'original_entry': correction.original_entry_id,
        'status': correction.status,
        'resolution_type': correction.resolution_type,
        'reason': correction.reason,
        'message': correction.message,
        'requested_by': correction.requested_by_id,
        'requested_at': correction.requested_at,
        'approved_by': correction.approved_by_id,
        'approved_at': correction.approved_at,
        'applied_at': correction.applied_at,
        'generated_entries': [
            {
                'id': entry.id,
                'entry_number': entry.entry_number,
                'entry_type': entry.entry_type,
                'status': entry.status,
                'reference_purpose': entry.reference_purpose,
            }
            for entry in correction.generated_entries.order_by('id')
        ],
        'lines': [
            {
                'id': line.id,
                'original_item': line.original_item_id,
                'original_quantity': line.original_quantity,
                'corrected_quantity': line.corrected_quantity,
                'delta': line.delta,
                'affected_instances': list(line.affected_instances.values_list('id', flat=True)),
            }
            for line in correction.lines.select_related('original_item').prefetch_related('affected_instances')
        ],
    }


def serialize_correction(correction: StockCorrectionRequest) -> dict:
    return _serialize_correction(correction)


def create_correction_request(entry: StockEntry, payload, user, *, auto_apply=True) -> StockCorrectionRequest:
    reason = (payload.get('reason') or '').strip()
    if not reason:
        raise serializers.ValidationError({'reason': 'Correction reason is required.'})

    preview = build_correction_preview(entry, payload)
    if preview['resolution_type'] == CorrectionResolutionType.NO_CHANGE:
        raise serializers.ValidationError({'detail': 'Change at least one corrected quantity before submitting a correction.'})

    status = CorrectionStatus.BLOCKED if preview['resolution_type'] == CorrectionResolutionType.BLOCKED else CorrectionStatus.REQUESTED

    with transaction.atomic():
        correction = StockCorrectionRequest.objects.create(
            original_entry=entry,
            status=status,
            resolution_type=preview['resolution_type'],
            reason=reason,
            message=preview['message'],
            requested_by=user,
        )

        for line in preview['lines']:
            correction_line = StockCorrectionLine.objects.create(
                correction_request=correction,
                original_item=line.entry_item,
                original_quantity=line.original_quantity,
                corrected_quantity=line.corrected_quantity,
                delta=line.delta,
            )
            if line.affected_instance_ids:
                correction_line.affected_instances.set(ItemInstance.objects.filter(id__in=line.affected_instance_ids))

        if auto_apply and status != CorrectionStatus.BLOCKED and preview['resolution_type'] in {
            CorrectionResolutionType.ADDITIONAL_MOVEMENT,
            CorrectionResolutionType.ALLOCATION_INCREASE,
            CorrectionResolutionType.ALLOCATION_REDUCTION,
            CorrectionResolutionType.RETURN_INCREASE,
            CorrectionResolutionType.RETURN_REDUCTION,
        }:
            apply_correction(correction, user=user, require_approval=False)

    return correction


def approve_correction(correction: StockCorrectionRequest, user) -> StockCorrectionRequest:
    if correction.status != CorrectionStatus.REQUESTED:
        raise serializers.ValidationError({'detail': 'Only requested corrections can be approved.'})
    correction.status = CorrectionStatus.APPROVED
    correction.approved_by = user
    correction.approved_at = timezone.now()
    correction.save(update_fields=['status', 'approved_by', 'approved_at'])
    return correction


def reject_correction(correction: StockCorrectionRequest, user, reason='') -> StockCorrectionRequest:
    if correction.status not in {CorrectionStatus.REQUESTED, CorrectionStatus.APPROVED}:
        raise serializers.ValidationError({'detail': 'This correction cannot be rejected.'})
    correction.status = CorrectionStatus.REJECTED
    correction.rejected_by = user
    correction.rejected_at = timezone.now()
    correction.rejection_reason = reason or ''
    correction.save(update_fields=['status', 'rejected_by', 'rejected_at', 'rejection_reason'])
    return correction


def apply_correction(correction: StockCorrectionRequest, *, user, require_approval=True) -> StockCorrectionRequest:
    if correction.status == CorrectionStatus.APPLIED:
        return correction
    if correction.status == CorrectionStatus.BLOCKED:
        raise serializers.ValidationError({'detail': 'Blocked corrections cannot be applied.'})
    if require_approval and correction.status != CorrectionStatus.APPROVED:
        raise serializers.ValidationError({'detail': 'This correction must be approved before it can be applied.'})

    entry = correction.original_entry
    lines = list(correction.lines.select_related('original_item__item', 'original_item__batch'))
    line_inputs = [
        CorrectionLineInput(
            entry_item=line.original_item,
            original_quantity=line.original_quantity,
            corrected_quantity=line.corrected_quantity,
            delta=line.delta,
            affected_instance_ids=list(line.affected_instances.values_list('id', flat=True)),
            resolution_type=correction.resolution_type,
            message=correction.message,
        )
        for line in lines
    ]

    with transaction.atomic():
        if correction.resolution_type == CorrectionResolutionType.ADDITIONAL_MOVEMENT:
            _apply_additional_movement(entry, correction, line_inputs)
        elif correction.resolution_type == CorrectionResolutionType.REVERSAL:
            _apply_reversal(entry, correction, line_inputs)
        elif correction.resolution_type == CorrectionResolutionType.ALLOCATION_INCREASE:
            _apply_allocation_increase(entry, correction, line_inputs)
        elif correction.resolution_type == CorrectionResolutionType.ALLOCATION_REDUCTION:
            _apply_allocation_reduction(entry, line_inputs)
        elif correction.resolution_type == CorrectionResolutionType.RETURN_INCREASE:
            _apply_return_increase(entry, correction, line_inputs)
        elif correction.resolution_type == CorrectionResolutionType.RETURN_REDUCTION:
            _apply_return_reduction(entry, correction, line_inputs)
        elif correction.resolution_type == CorrectionResolutionType.NO_CHANGE:
            pass
        else:
            raise serializers.ValidationError({'detail': 'This correction requires manual adjustment approval.'})

        correction.status = CorrectionStatus.APPLIED
        correction.applied_at = timezone.now()
        if correction.approved_by_id is None:
            correction.approved_by = user
            correction.approved_at = correction.applied_at
        correction.save(update_fields=['status', 'applied_at', 'approved_by', 'approved_at'])

    return correction
