from collections import defaultdict

from django.db.models import Q, Prefetch
from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from ..models.allocation_model import AllocationStatus, StockAllocation
from ..models.depreciation_model import AssetValueAdjustment, DepreciationEntry
from ..models.instance_model import ItemInstance
from ..models.stockentry_model import StockEntryItem
from ..serializers.instance_serializer import ItemInstanceSerializer
from .utils import ScopedViewSetMixin, get_item_scope_locations
from ..permissions import ItemInstancePermission


class ItemInstanceViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for Item Instances.
    Supports read and update operations.
    """
    serializer_class = ItemInstanceSerializer
    permission_classes = [permissions.IsAuthenticated, ItemInstancePermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ['serial_number', 'qr_code']

    def get_queryset(self):
        # Base queryset with select_related for foreign keys (avoids N+1)
        queryset = ItemInstance.objects.select_related(
            'item',
            'item__category',
            'current_location',
            'current_location__parent_location',
            'created_by',
            'inspection_certificate',
            'fixed_asset_entry',
            'fixed_asset_entry__asset_class',
            'fixed_asset_entry__policy',
        ).order_by('-created_at')
        queryset = queryset.prefetch_related(
            Prefetch(
                'fixed_asset_entry__depreciation_entries',
                queryset=DepreciationEntry.objects.select_related('run', 'rate_version').order_by('-fiscal_year_start'),
                to_attr='prefetched_depreciation_entries',
            ),
            Prefetch(
                'fixed_asset_entry__adjustments',
                queryset=AssetValueAdjustment.objects.order_by('-effective_date', '-created_at'),
                to_attr='prefetched_adjustments',
            ),
        )
        
        item_id = self.request.query_params.get('item')
        if item_id:
            queryset = queryset.filter(item_id=item_id)
            
        location_id = self.request.query_params.get('location')
        if location_id:
            queryset = queryset.filter(current_location_id=location_id)
            
        status = self.request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)

        stock_entry_ids = self.request.query_params.get('stock_entry_ids')
        if stock_entry_ids:
            id_list = [sid.strip() for sid in stock_entry_ids.split(',') if sid.strip()]
            queryset = queryset.filter(stock_entry_items__stock_entry_id__in=id_list).distinct()

        return queryset.filter(current_location__in=get_item_scope_locations(self.request.user)).distinct()

    def _build_instance_serializer_maps(self, instances):
        instance_list = list(instances)
        instance_ids = [instance.id for instance in instance_list]
        item_ids = {
            instance.item_id
            for instance in instance_list
            if instance.status == 'ALLOCATED' and instance.item_id
        }

        allocation_by_item_batch = {}
        if item_ids:
            allocations = (
                StockAllocation.objects.filter(
                    item_id__in=item_ids,
                    batch__isnull=True,
                    status=AllocationStatus.ALLOCATED,
                )
                .filter(Q(allocated_to_person__isnull=False) | Q(allocated_to_location__isnull=False))
                .select_related('allocated_to_person', 'allocated_to_location', 'source_location')
                .order_by('-allocated_at')
            )
            for allocation in allocations:
                key = (allocation.item_id, allocation.batch_id)
                if key not in allocation_by_item_batch:
                    allocation_by_item_batch[key] = allocation

        stock_entry_ids_by_instance = defaultdict(list)
        if instance_ids:
            pairs = (
                StockEntryItem.objects.filter(instances__id__in=instance_ids)
                .values_list('instances__id', 'stock_entry_id')
                .distinct()
                .order_by('stock_entry_id')
            )
            for instance_id, stock_entry_id in pairs:
                stock_entry_ids_by_instance[instance_id].append(stock_entry_id)

        return {
            'allocation_by_item_batch': allocation_by_item_batch,
            'stock_entry_ids_by_instance': dict(stock_entry_ids_by_instance),
        }

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(getattr(self, '_instance_serializer_maps', {}))
        return context

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            self._instance_serializer_maps = self._build_instance_serializer_maps(page)
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        instances = list(queryset)
        self._instance_serializer_maps = self._build_instance_serializer_maps(instances)
        serializer = self.get_serializer(instances, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        self._instance_serializer_maps = self._build_instance_serializer_maps([instance])
        serializer = self.get_serializer(instance)
        return Response(serializer.data)
