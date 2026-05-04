from rest_framework import viewsets, permissions, filters
from collections import defaultdict
from ..models.item_model import Item
from ..models.location_model import Location
from ..models.stock_record_model import StockRecord
from ..models.allocation_model import StockAllocation, AllocationStatus
from ..serializers.item_serializer import ItemSerializer
from ..permissions import ItemPermission
from .utils import get_item_scope_locations, get_scope_tokens_from_request

class ItemViewSet(viewsets.ModelViewSet):
    queryset = Item.objects.all().select_related('category__parent_category', 'created_by').order_by('name', 'id')
    serializer_class = ItemSerializer
    permission_classes = [permissions.IsAuthenticated, ItemPermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'code']

    def _build_standalone_location_counts(self, item_ids):
        if not item_ids:
            return {}

        scope_tokens = get_scope_tokens_from_request(self.request)
        accessible_loc_ids = list(
            get_item_scope_locations(self.request.user, scope_tokens).values_list('id', flat=True)
        )
        if not accessible_loc_ids:
            return {}

        location_map = {
            row['id']: {
                'parent_location_id': row['parent_location_id'],
                'is_standalone': row['is_standalone'],
            }
            for row in Location.objects.values('id', 'parent_location_id', 'is_standalone')
        }

        def resolve_standalone_id(location_id):
            current_id = location_id
            while current_id is not None:
                node = location_map.get(current_id)
                if not node:
                    return None
                if node['is_standalone']:
                    return current_id
                current_id = node['parent_location_id']
            return None

        counts = defaultdict(set)

        record_pairs = StockRecord.objects.filter(
            item_id__in=item_ids,
            location_id__in=accessible_loc_ids,
        ).values_list('item_id', 'location_id')
        for item_id, location_id in record_pairs:
            standalone_id = resolve_standalone_id(location_id)
            if standalone_id is not None:
                counts[item_id].add(standalone_id)

        allocation_pairs = StockAllocation.objects.filter(
            item_id__in=item_ids,
            status=AllocationStatus.ALLOCATED,
            source_location_id__in=accessible_loc_ids,
        ).values_list('item_id', 'source_location_id')
        for item_id, source_location_id in allocation_pairs:
            standalone_id = resolve_standalone_id(source_location_id)
            if standalone_id is not None:
                counts[item_id].add(standalone_id)

        return {
            item_id: len(standalone_ids)
            for item_id, standalone_ids in counts.items()
        }

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if not hasattr(user, 'profile'):
            return queryset.none()
            
        profile = user.profile
        from django.db.models import Sum, Q, Value
        from django.db.models.functions import Coalesce

        # 1. Row-Level Visibility Filtering
        if profile.power_level == 3:
            # Tier 3 (Staff/Faculty) only see items allocated to them
            queryset = queryset.filter(
                allocations__allocated_to_person__user=user, 
                allocations__status='ALLOCATED'
            ).distinct()
        # Tiers 0, 1, 2 can see all items for browsing/requesting

        # 2. Scoped Stock Annotations
        scope_tokens = get_scope_tokens_from_request(self.request)
        accessible_locs = get_item_scope_locations(user, scope_tokens)
        # If level 0 (Central), they see global totals. 
        # But get_descendant_locations for level 0 already returns all active locations.
        
        filter_q = Q(stock_records__location__in=accessible_locs)
        restricted_total = Coalesce(Sum(
            'stock_records__quantity',
            filter=filter_q
        ), Value(0))
        restricted_in_transit = Coalesce(Sum(
            'stock_records__in_transit_quantity',
            filter=filter_q
        ), Value(0))
        restricted_allocated = Coalesce(Sum(
            'stock_records__allocated_quantity',
            filter=filter_q
        ), Value(0))
        
        queryset = queryset.annotate(
            restricted_total=restricted_total,
            restricted_in_transit=restricted_in_transit,
            restricted_available=restricted_total - restricted_in_transit - restricted_allocated,
        )

        category_id = self.request.query_params.get('category')
        if category_id:
            queryset = queryset.filter(category_id=category_id)
        return queryset

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.action in {'list', 'retrieve'}:
            queryset = self.filter_queryset(self.get_queryset())
            if self.action == 'retrieve':
                item_ids = [self.kwargs.get('pk')]
            else:
                item_ids = list(queryset.values_list('id', flat=True))
            context['standalone_location_counts'] = self._build_standalone_location_counts(item_ids)
        return context
