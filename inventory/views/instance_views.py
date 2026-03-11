from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q, Prefetch
from ..models.instance_model import ItemInstance
from ..models.allocation_model import StockAllocation, AllocationStatus
from ..serializers.instance_serializer import ItemInstanceSerializer
from .utils import ScopedViewSetMixin


class HasChangeItemInstancePermission(permissions.BasePermission):
    """
    Custom permission to check if user can change item instance.
    """
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        # Check if user has change_item_instance permission
        return request.user.has_perm('inventory.change_item_instance') or request.user.is_superuser


class ItemInstanceViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for Item Instances.
    Supports read and update operations.
    """
    serializer_class = ItemInstanceSerializer
    permission_classes = [permissions.IsAuthenticated, HasChangeItemInstancePermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ['serial_number', 'batch_number']

    def get_queryset(self):
        # Base queryset with select_related for foreign keys (avoids N+1)
        queryset = ItemInstance.objects.select_related(
            'item',
            'item__category',
            'current_location',
            'current_location__parent_location',
            'batch',
            'created_by',
            'inspection_certificate'
        ).prefetch_related(
            # Prefetch active allocations for serializer optimization (avoids triple query)
            Prefetch(
                'stockallocation_set',
                queryset=StockAllocation.objects.filter(
                    status=AllocationStatus.ALLOCATED
                ).select_related(
                    'allocated_to_person',
                    'allocated_to_location',
                    'source_location'
                ),
                to_attr='_prefetched_allocations'
            )
        ).order_by('-created_at')
        
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

        return self.get_scoped_queryset(queryset, location_field='current_location')
