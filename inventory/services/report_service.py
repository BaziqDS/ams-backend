from inventory.models import (
    AllocationStatus,
    ItemInstance,
    Location,
    StockAllocation,
    StockRecord,
    TrackingType,
)


def _store_payload(store):
    return {
        'id': store.id,
        'name': store.name,
        'code': store.code,
    }


def _allocation_holder(allocation):
    if allocation.allocated_to_person_id:
        return 'PERSON', allocation.allocated_to_person.name
    if allocation.allocated_to_location_id:
        return 'LOCATION', allocation.allocated_to_location.name
    return None, None


def _tracking_type(item):
    return item.category.get_tracking_type() if item.category_id else None


def _summary_row(item):
    return {
        'item_name': item.name,
        'item_code': item.code or None,
        'tracking_type': _tracking_type(item),
        'total': 0,
        'available': 0,
        'allocated': 0,
        'in_transit': 0,
    }


def build_inventory_position_report(store):
    if not isinstance(store, Location):
        raise TypeError('store must be a Location instance')

    summary_rows_by_item_id = {}
    instance_rows = []
    batch_rows = []
    allocated_instance_ids_by_item_id = {}

    def summary_for(item):
        if item.id not in summary_rows_by_item_id:
            summary_rows_by_item_id[item.id] = _summary_row(item)
        return summary_rows_by_item_id[item.id]

    in_store_instances = (
        ItemInstance.objects.filter(current_location=store)
        .exclude(status='ALLOCATED')
        .select_related('item', 'item__category')
    )
    for instance in in_store_instances:
        instance_rows.append({
            'item_name': instance.item.name,
            'status': 'In Store',
            'holder_type': 'Store',
            'holder_name': store.name,
            'instance_id': instance.id,
            'batch_number': None,
            'quantity': 1,
            'stock_entry_number': None,
        })

    individual_allocations = (
        StockAllocation.objects.filter(
            source_location=store,
            status=AllocationStatus.ALLOCATED,
            batch__isnull=True,
        )
        .select_related(
            'allocated_to_person',
            'allocated_to_location',
            'stock_entry',
            'item',
            'item__category',
        )
        .prefetch_related('stock_entry__items__instances')
    )
    for allocation in individual_allocations:
        holder_type, holder_name = _allocation_holder(allocation)
        if not allocation.stock_entry_id:
            continue

        seen_instance_ids = set()
        for entry_item in allocation.stock_entry.items.filter(item=allocation.item, batch__isnull=True):
            for instance in entry_item.instances.all():
                if instance.id in seen_instance_ids:
                    continue

                seen_instance_ids.add(instance.id)
                instance_rows.append({
                    'item_name': instance.item.name,
                    'status': 'Allocated',
                    'holder_type': holder_type,
                    'holder_name': holder_name,
                    'instance_id': instance.id,
                    'batch_number': None,
                    'quantity': 1,
                    'stock_entry_number': allocation.stock_entry.entry_number,
                })
                allocated_instance_ids_by_item_id.setdefault(instance.item_id, set()).add(instance.id)

    all_store_instances = (
        ItemInstance.objects.filter(current_location=store)
        .select_related('item', 'item__category')
    )
    for instance in all_store_instances:
        summary = summary_for(instance.item)
        summary['total'] += 1
        if instance.status != 'ALLOCATED':
            summary['available'] += 1

    for item_id, instance_ids in allocated_instance_ids_by_item_id.items():
        summary_rows_by_item_id[item_id]['allocated'] += len(instance_ids)

    in_store_quantity_records = (
        StockRecord.objects.filter(location=store)
        .select_related('item', 'item__category', 'batch')
    )
    for record in in_store_quantity_records:
        if _tracking_type(record.item) == TrackingType.INDIVIDUAL:
            continue

        summary = summary_for(record.item)
        summary['total'] += record.quantity
        summary['available'] += record.available_quantity
        summary['allocated'] += record.allocated_quantity
        summary['in_transit'] += record.in_transit_quantity

        if record.available_quantity <= 0:
            continue

        batch_rows.append({
            'item_name': record.item.name,
            'status': 'In Store',
            'holder_type': 'Store',
            'holder_name': store.name,
            'instance_id': None,
            'batch_number': record.batch.batch_number if record.batch else None,
            'quantity': record.available_quantity,
            'stock_entry_number': None,
        })

    quantity_allocations = (
        StockAllocation.objects.filter(
            source_location=store,
            status=AllocationStatus.ALLOCATED,
        )
        .exclude(batch__isnull=True, quantity=1)
        .select_related(
            'allocated_to_person',
            'allocated_to_location',
            'stock_entry',
            'batch',
            'item',
        )
    )
    for allocation in quantity_allocations:
        holder_type, holder_name = _allocation_holder(allocation)
        batch_rows.append({
            'item_name': allocation.item.name,
            'status': 'Allocated',
            'holder_type': holder_type,
            'holder_name': holder_name,
            'instance_id': None,
            'batch_number': allocation.batch.batch_number if allocation.batch else None,
            'quantity': allocation.quantity,
            'stock_entry_number': allocation.stock_entry.entry_number if allocation.stock_entry_id else None,
        })

    summary_rows = sorted(summary_rows_by_item_id.values(), key=lambda row: (row['item_name'], row['item_code'] or ''))
    totals = {
        'item_lines': len(summary_rows),
        'available_quantity': sum(row['available'] for row in summary_rows),
        'allocated_quantity': sum(row['allocated'] for row in summary_rows),
        'in_transit_quantity': sum(row['in_transit'] for row in summary_rows),
    }
    rows = [*instance_rows, *batch_rows]

    return {
        'store': _store_payload(store),
        'totals': totals,
        'summary_rows': summary_rows,
        'instance_rows': instance_rows,
        'batch_rows': batch_rows,
        'rows': rows,
    }
