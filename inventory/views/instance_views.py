from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from ..models.instance_model import ItemInstance
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

        return queryset.filter(current_location__in=get_item_scope_locations(self.request.user)).distinct()
