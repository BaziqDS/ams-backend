from rest_framework import viewsets, permissions, filters
from ..models.instance_model import ItemInstance
from ..serializers.instance_serializer import ItemInstanceSerializer
from .utils import ScopedViewSetMixin

class ItemInstanceViewSet(ScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    ReadOnly ViewSet for Item Instances.
    Filtered by hierarchical scope and query params.
    """
    queryset = ItemInstance.objects.all().order_by('-created_at')
    serializer_class = ItemInstanceSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['serial_number', 'batch_number']

    def get_queryset(self):
        queryset = super().get_queryset()
        
        item_id = self.request.query_params.get('item')
        if item_id:
            queryset = queryset.filter(item_id=item_id)
            
        location_id = self.request.query_params.get('location')
        if location_id:
            queryset = queryset.filter(current_location_id=location_id)
            
        status = self.request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)
            
        return self.get_scoped_queryset(queryset, location_field='current_location')
