from django.utils import timezone
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from ..models.stock_register_model import StockRegister
from ..serializers.stock_register_serializer import StockRegisterSerializer
from ..permissions import StockRegisterPermission
from notifications.services import notify_stock_register_closed, notify_stock_register_reopened


class StockRegisterViewSet(viewsets.ModelViewSet):
    """
    CRUD ViewSet for Stock Registers.
    Scoped to the user's accessible store locations.
    """
    serializer_class = StockRegisterSerializer
    permission_classes = [permissions.IsAuthenticated, StockRegisterPermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ['register_number', 'store__name']

    def get_queryset(self):
        user = self.request.user
        queryset = StockRegister.objects.select_related('store', 'created_by', 'closed_by').all()

        # Scope to accessible locations
        if not user.is_superuser and not user.groups.filter(name='System Admin').exists():
            if hasattr(user, 'profile'):
                accessible = user.profile.get_stock_register_scope_locations()
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

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        register = self.get_object()
        reason = str(request.data.get('reason', '')).strip()
        register.is_active = False
        register.closed_at = timezone.now()
        register.closed_by = request.user
        register.closed_reason = reason
        register.save(update_fields=['is_active', 'closed_at', 'closed_by', 'closed_reason', 'updated_at'])
        notify_stock_register_closed(register, request.user)
        serializer = self.get_serializer(register)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def reopen(self, request, pk=None):
        register = self.get_object()
        reason = str(request.data.get('reason', '')).strip()
        register.is_active = True
        register.reopened_at = timezone.now()
        register.reopened_by = request.user
        register.reopened_reason = reason
        register.save(update_fields=['is_active', 'reopened_at', 'reopened_by', 'reopened_reason', 'updated_at'])
        notify_stock_register_reopened(register, request.user)
        serializer = self.get_serializer(register)
        return Response(serializer.data, status=status.HTTP_200_OK)
