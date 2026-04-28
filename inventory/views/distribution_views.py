from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Sum
from ..models.stock_record_model import StockRecord
from ..models.allocation_model import StockAllocation, AllocationStatus
from ..models.location_model import Location
from ..serializers.distribution_serializer import StockRecordSerializer
from ..permissions import ItemReadPermission

from .utils import ScopedViewSetMixin, get_item_scope_locations


def build_hierarchical_distribution(user, item_id, batch_id=None):
    if not hasattr(user, 'profile'):
        return []

    accessible_locs = get_item_scope_locations(user)

    records = StockRecord.objects.filter(
        item_id=item_id,
        location__in=accessible_locs,
    ).select_related(
        'location',
        'location__parent_location',
        'batch',
    )
    allocations = StockAllocation.objects.filter(
        item_id=item_id,
        status=AllocationStatus.ALLOCATED,
        source_location__in=accessible_locs,
    ).select_related(
        'source_location',
        'source_location__parent_location',
        'allocated_to_person',
        'allocated_to_location',
        'batch',
    )

    include_batch = batch_id is not None
    if include_batch:
        records = records.filter(batch_id=batch_id)
        allocations = allocations.filter(batch_id=batch_id)

    all_location_ids = set()
    for record in records:
        all_location_ids.add(record.location_id)
        if record.location.parent_location_id:
            all_location_ids.add(record.location.parent_location_id)

    for alloc in allocations:
        all_location_ids.add(alloc.source_location_id)
        if alloc.source_location.parent_location_id:
            all_location_ids.add(alloc.source_location.parent_location_id)

    location_map = {loc.id: loc for loc in Location.objects.filter(id__in=all_location_ids)}

    def get_standalone(location):
        if not location:
            return None
        current = location
        while current.parent_location_id:
            parent = location_map.get(current.parent_location_id)
            if not parent:
                break
            if parent.is_standalone:
                return parent
            current = parent
        return location if location.is_standalone else None

    hierarchy = {}

    def get_or_create_unit(unit_loc):
        if unit_loc.id not in hierarchy:
            hierarchy[unit_loc.id] = {
                "id": unit_loc.id,
                "name": unit_loc.name,
                "code": unit_loc.code,
                "totalQuantity": 0,
                "availableQuantity": 0,
                "inTransitQuantity": 0,
                "allocatedQuantity": 0,
                "stores": [],
                "allocations": [],
            }
        return hierarchy[unit_loc.id]

    store_groups = {}
    for record in records:
        standalone = get_standalone(record.location)
        if not standalone:
            continue

        unit = get_or_create_unit(standalone)
        unit["totalQuantity"] += record.quantity
        unit["availableQuantity"] += record.available_quantity
        unit["inTransitQuantity"] += record.in_transit_quantity
        unit["allocatedQuantity"] += record.allocated_quantity

        group_key = (standalone.id, record.location.id)
        if group_key not in store_groups:
            store_groups[group_key] = {
                "unit": unit,
                "id": record.location.id,
                "locationId": record.location.id,
                "locationName": record.location.name,
                "isStore": record.location.is_store,
                "batchNumber": record.batch.batch_number if include_batch and record.batch else None,
                "batchId": record.batch.id if include_batch and record.batch else None,
                "quantity": 0,
                "availableQuantity": 0,
                "inTransitQuantity": 0,
                "allocatedTotal": 0,
                "lastUpdated": record.last_updated,
            }

        group = store_groups[group_key]
        group["quantity"] += record.quantity
        group["availableQuantity"] += record.available_quantity
        group["inTransitQuantity"] += record.in_transit_quantity
        group["allocatedTotal"] += record.allocated_quantity
        if record.last_updated and (not group["lastUpdated"] or record.last_updated > group["lastUpdated"]):
            group["lastUpdated"] = record.last_updated

    allocations_grouped = {}
    for alloc in allocations:
        standalone = get_standalone(alloc.source_location)
        if not standalone:
            continue

        target_id = alloc.allocated_to_person.id if alloc.allocated_to_person else alloc.allocated_to_location.id
        target_name = alloc.allocated_to_person.name if alloc.allocated_to_person else alloc.allocated_to_location.name
        target_type = "PERSON" if alloc.allocated_to_person else "LOCATION"
        source_store_id = alloc.source_location.id
        source_store_name = alloc.source_location.name

        group_key = (standalone.id, target_type, target_id, source_store_id)
        if group_key not in allocations_grouped:
            allocations_grouped[group_key] = {
                "standalone": standalone,
                "id": alloc.id,
                "targetName": target_name,
                "targetType": target_type,
                "targetLocationId": alloc.allocated_to_location.id if alloc.allocated_to_location else None,
                "sourceStoreId": source_store_id,
                "sourceStoreName": source_store_name,
                "batchNumber": alloc.batch.batch_number if include_batch and alloc.batch else None,
                "batchId": alloc.batch.id if include_batch and alloc.batch else None,
                "quantity": 0,
                "allocatedAt": alloc.allocated_at,
                "stockEntryIds": [],
            }

        grp = allocations_grouped[group_key]
        grp["quantity"] += alloc.quantity
        if alloc.allocated_at > grp["allocatedAt"]:
            grp["allocatedAt"] = alloc.allocated_at
        if alloc.stock_entry_id and alloc.stock_entry_id not in grp["stockEntryIds"]:
            grp["stockEntryIds"].append(alloc.stock_entry_id)

    for group in store_groups.values():
        group["unit"]["stores"].append({
            "id": group["id"],
            "locationId": group["locationId"],
            "locationName": group["locationName"],
            "isStore": group["isStore"],
            "batchNumber": group["batchNumber"],
            "batchId": group["batchId"],
            "quantity": group["quantity"],
            "availableQuantity": group["availableQuantity"],
            "inTransitQuantity": group["inTransitQuantity"],
            "allocatedTotal": group["allocatedTotal"],
            "lastUpdated": group["lastUpdated"],
        })

    for grp in allocations_grouped.values():
        unit = get_or_create_unit(grp["standalone"])
        unit["allocations"].append({
            "id": grp["id"],
            "targetName": grp["targetName"],
            "targetType": grp["targetType"],
            "targetLocationId": grp["targetLocationId"],
            "sourceStoreId": grp["sourceStoreId"],
            "sourceStoreName": grp["sourceStoreName"],
            "batchNumber": grp["batchNumber"],
            "batchId": grp["batchId"],
            "quantity": grp["quantity"],
            "allocatedAt": grp["allocatedAt"],
            "stockEntryIds": grp["stockEntryIds"],
        })

    return list(hierarchy.values())

class StockRecordViewSet(ScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing item distribution (stock records).
    Optimized with select_related to avoid N+1 queries.
    """
    serializer_class = StockRecordSerializer
    permission_classes = [permissions.IsAuthenticated, ItemReadPermission]

    def get_queryset(self):
        # Add select_related to avoid N+1 queries
        queryset = StockRecord.objects.select_related(
            'location',
            'location__parent_location',
            'item',
            'batch'
        )
        
        item_id = self.request.query_params.get('item')
        if item_id:
            queryset = queryset.filter(item_id=item_id)
            
        location_id = self.request.query_params.get('location')
        if location_id:
            queryset = queryset.filter(location_id=location_id)
            
        user = self.request.user
        return queryset.filter(location__in=get_item_scope_locations(user)).distinct()

    @action(detail=False, methods=['get'])
    def hierarchical(self, request):
        item_id = request.query_params.get('item')
        if not item_id:
            return Response({"error": "Item ID is required"}, status=400)
        batch_id = request.query_params.get('batch')
        return Response(
            build_hierarchical_distribution(
                request.user,
                item_id,
                batch_id=batch_id,
            )
        )
