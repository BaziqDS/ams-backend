from rest_framework import viewsets, permissions, status, filters
from rest_framework.response import Response
from ..models.stock_register_model import StockRegister
from ..serializers.stock_register_serializer import StockRegisterSerializer


class StockRegisterViewSet(viewsets.ModelViewSet):
    """
    CRUD ViewSet for Stock Registers.
    Scoped to the user's accessible store locations.
    """
    serializer_class = StockRegisterSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['register_number', 'store__name']

    def get_queryset(self):
        user = self.request.user
        queryset = StockRegister.objects.select_related('store', 'created_by').all()

        # Scope to accessible locations
        if not user.is_superuser and not user.groups.filter(name='System Admin').exists():
            if hasattr(user, 'profile'):
                accessible = user.profile.get_accessible_locations()
                queryset = queryset.filter(store__in=accessible)
            else:
                queryset = queryset.none()

        # Optional store filter
        store_id = self.request.query_params.get('store')
        if store_id:
            queryset = queryset.filter(store_id=store_id)

        return queryset.order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save()
