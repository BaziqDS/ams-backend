from rest_framework import viewsets, permissions
from django.db.models import Q, Sum, Value
from django.db.models.functions import Coalesce
from ..models.batch_model import ItemBatch
from ..serializers.batch_serializer import ItemBatchSerializer
from ..permissions import ItemReadPermission
from .utils import get_item_scope_locations

class ItemBatchViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ReadOnly ViewSet for Item Batches.
    Optimized with select_related for item relationship.
    """
    serializer_class = ItemBatchSerializer
    permission_classes = [permissions.IsAuthenticated, ItemReadPermission]

    def get_queryset(self):
        # Add select_related to avoid N+1 on item
        queryset = ItemBatch.objects.select_related(
            'item',
            'item__category',
            'created_by'
        ).order_by('-created_at')
        accessible_locations = get_item_scope_locations(self.request.user)
        
        item_id = self.request.query_params.get('item')
        if item_id:
            queryset = queryset.filter(item_id=item_id)

        location_id = self.request.query_params.get('location')
        if location_id:
            queryset = queryset.filter(stock_records__location_id=location_id)

        queryset = queryset.filter(stock_records__location__in=accessible_locations)
        stock_filter = Q(stock_records__location__in=accessible_locations)
        if location_id:
            stock_filter &= Q(stock_records__location_id=location_id)

        queryset = queryset.annotate(
            quantity=Coalesce(Sum('stock_records__quantity', filter=stock_filter), Value(0)),
            in_transit_quantity=Coalesce(Sum('stock_records__in_transit_quantity', filter=stock_filter), Value(0)),
            allocated_quantity=Coalesce(Sum('stock_records__allocated_quantity', filter=stock_filter), Value(0)),
        ).distinct()
            
        return queryset
