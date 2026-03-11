from rest_framework import viewsets, permissions
from ams.permissions import StrictDjangoModelPermissions
from ..models.batch_model import ItemBatch
from ..serializers.batch_serializer import ItemBatchSerializer

class ItemBatchViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ReadOnly ViewSet for Item Batches.
    Optimized with select_related for item relationship.
    """
    serializer_class = ItemBatchSerializer
    permission_classes = [permissions.IsAuthenticated, StrictDjangoModelPermissions]

    def get_queryset(self):
        # Add select_related to avoid N+1 on item
        queryset = ItemBatch.objects.select_related(
            'item',
            'item__category',
            'created_by'
        ).order_by('-created_at')
        
        item_id = self.request.query_params.get('item')
        if item_id:
            queryset = queryset.filter(item_id=item_id)
            
        return queryset
