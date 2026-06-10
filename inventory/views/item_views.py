from django.db.models import Prefetch
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from collections import defaultdict
from ..models.depreciation_model import AssetValueAdjustment, DepreciationEntry, FixedAssetRegisterEntry
from ..models.item_model import Item
from ..models.location_model import Location
from ..models.stock_record_model import StockRecord
from ..models.allocation_model import StockAllocation, AllocationStatus
from ..serializers.item_serializer import ItemSerializer
from ..permissions import ItemPermission, ItemCopilotSearchPermission
from ..services.deletion_policy import DeletionBlocked, bulk_item_delete_blockers, delete_with_policy
from ..services import item_search
from .utils import get_item_scope_locations, get_scope_tokens_from_request

class ItemViewSet(viewsets.ModelViewSet):
    queryset = (
        Item.objects.all()
        .select_related('category__parent_category', 'created_by')
        .prefetch_related(
            Prefetch(
                'fixed_asset_entries',
                queryset=FixedAssetRegisterEntry.objects.select_related(
                    'asset_class',
                    'policy',
                ).prefetch_related(
                    Prefetch(
                        'depreciation_entries',
                        queryset=DepreciationEntry.objects.select_related('run', 'rate_version').order_by('-fiscal_year_start'),
                        to_attr='prefetched_depreciation_entries',
                    ),
                    Prefetch(
                        'adjustments',
                        queryset=AssetValueAdjustment.objects.order_by('-effective_date', '-created_at'),
                        to_attr='prefetched_adjustments',
                    ),
                ),
                to_attr='prefetched_fixed_asset_entries',
            )
        )
        .order_by('name', 'id')
    )
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

        if self.action == 'list':
            queryset = queryset.filter(is_provisional=False)

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
        if hasattr(self, '_standalone_location_counts'):
            context['standalone_location_counts'] = self._standalone_location_counts
        elif self.action == 'retrieve':
            item_ids = [self.kwargs.get('pk')]
            context['standalone_location_counts'] = self._build_standalone_location_counts(item_ids)
        if hasattr(self, '_delete_blockers_by_item'):
            context['delete_blockers_by_item'] = self._delete_blockers_by_item
        return context

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            item_ids = [item.id for item in page]
            self._standalone_location_counts = self._build_standalone_location_counts(item_ids)
            self._delete_blockers_by_item = bulk_item_delete_blockers(item_ids)
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        item_ids = list(queryset.values_list('id', flat=True))
        self._standalone_location_counts = self._build_standalone_location_counts(item_ids)
        self._delete_blockers_by_item = bulk_item_delete_blockers(item_ids)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            delete_with_policy(instance)
        except DeletionBlocked as exc:
            return Response(
                {'detail': 'Delete is blocked by existing dependencies.', 'delete_blockers': exc.blockers},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    # =========================================================================
    # COPILOT-ONLY hybrid catalog search.
    # =========================================================================
    # This endpoint is reached only from the frontend's copilot bridge when
    # the agent calls search_form_options for items.N.item on a Central
    # Register form. Human-facing dropdowns continue to hit the standard
    # `list` endpoint with `?search=...` which performs the existing keyword
    # filter — no behaviour change there.
    @action(
        detail=False,
        methods=['post'],
        url_path='copilot-search',
        # POST here is "search-as-RPC" not "create-an-item" — view permission
        # is the right gate. The agent-only call surface still requires the
        # signed-in user to have at least view_items.
        permission_classes=[permissions.IsAuthenticated, ItemCopilotSearchPermission],
    )
    def copilot_search(self, request):
        payload = request.data or {}

        if not item_search.is_supported():
            # Feature flag off or DB is not Postgres — caller should fall
            # back to the keyword resolver.
            return Response(
                {
                    'enabled': False,
                    'reason': 'hybrid_search_not_supported',
                    'hits': [],
                },
                status=status.HTTP_200_OK,
            )

        hits = item_search.hybrid_search_items(
            query_name=str(payload.get('item_name') or '').strip(),
            query_code=str(payload.get('item_code') or '').strip(),
            query_category=str(payload.get('item_category') or '').strip(),
            query_description=str(payload.get('item_description') or '').strip(),
            query_specifications=str(payload.get('item_specifications') or '').strip(),
            query_unit=str(payload.get('item_unit') or '').strip(),
            tracking_type=(payload.get('item_tracking_type') or None),
            category_type=(payload.get('item_category_type') or None),
            limit=int(payload.get('limit') or 10),
        )

        if hits is None:
            return Response(
                {
                    'enabled': False,
                    'reason': 'insufficient_query_signal',
                    'hits': [],
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                'enabled': True,
                'hits': [
                    {
                        'id': h.id,
                        'name': h.name,
                        'code': h.code,
                        'category_id': h.category_id,
                        'category_display': h.category_display,
                        'category_type': h.category_type,
                        'tracking_type': h.tracking_type,
                        'description': h.description,
                        'specifications': h.specifications,
                        'acct_unit': h.acct_unit,
                        'score': round(h.rrf_score, 6),
                        'signals': h.signals,
                    }
                    for h in hits
                ],
            },
            status=status.HTTP_200_OK,
        )
