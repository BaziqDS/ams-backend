from rest_framework import viewsets, permissions
from ams.permissions import StrictDjangoModelPermissions
from ..models.history_model import MovementHistory
from ..serializers.history_serializer import MovementHistorySerializer

class MovementHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ReadOnly ViewSet for Movement History.
    """
    queryset = MovementHistory.objects.all().order_by('-timestamp')
    serializer_class = MovementHistorySerializer
    permission_classes = [permissions.IsAuthenticated, StrictDjangoModelPermissions]

    def get_queryset(self):
        queryset = super().get_queryset()
        
        item_id = self.request.query_params.get('item')
        if item_id:
            queryset = queryset.filter(item_id=item_id)
            
        instance_id = self.request.query_params.get('instance')
        if instance_id:
            queryset = queryset.filter(instance_id=instance_id)
            
        batch_id = self.request.query_params.get('batch')
        if batch_id:
            queryset = queryset.filter(batch_id=batch_id)
            
        location_id = self.request.query_params.get('location')
        if location_id:
            from django.db.models import Q
            queryset = queryset.filter(Q(from_location_id=location_id) | Q(to_location_id=location_id))
            
        return queryset
