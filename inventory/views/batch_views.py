from rest_framework import viewsets, permissions
from ..models.batch_model import ItemBatch
from ..serializers.batch_serializer import ItemBatchSerializer

class ItemBatchViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ReadOnly ViewSet for Item Batches.
    """
    queryset = ItemBatch.objects.all().order_by('-created_at')
    serializer_class = ItemBatchSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        
        item_id = self.request.query_params.get('item')
        if item_id:
            queryset = queryset.filter(item_id=item_id)
            
        return queryset
