from rest_framework import viewsets, permissions
from ..models.stock_record_model import StockRecord
from ..serializers.distribution_serializer import StockRecordSerializer
from ams.permissions import StrictDjangoModelPermissions

class StockRecordViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing item distribution (stock records).
    """
    queryset = StockRecord.objects.all()
    serializer_class = StockRecordSerializer
    permission_classes = [permissions.IsAuthenticated, StrictDjangoModelPermissions]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        # Security: Filter by location hierarchy
        if not user.is_superuser:
            if hasattr(user, 'profile'):
                accessible_locs = user.profile.get_descendant_locations()
                queryset = queryset.filter(location__in=accessible_locs)
            else:
                # Users without profiles shouldn't see anything for safety
                queryset = queryset.none()

        item_id = self.request.query_params.get('item')
        location_id = self.request.query_params.get('location')
        
        if item_id:
            queryset = queryset.filter(item_id=item_id)
        if location_id:
            queryset = queryset.filter(location_id=location_id)
            
        return queryset
