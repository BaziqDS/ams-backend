from rest_framework import viewsets, permissions
from ..models.item_model import Item
from ..serializers.item_serializer import ItemSerializer
from ams.permissions import StrictDjangoModelPermissions

class ItemViewSet(viewsets.ModelViewSet):
    queryset = Item.objects.all().select_related('category__parent_category', 'created_by')
    serializer_class = ItemSerializer
    permission_classes = [permissions.IsAuthenticated, StrictDjangoModelPermissions]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if not hasattr(user, 'profile'):
            return queryset.none()
            
        profile = user.profile
        from django.db.models import Sum, Q, Value
        from django.db.models.functions import Coalesce

        # 1. Row-Level Visibility Filtering
        if profile.power_level == 3:
            # Tier 3 (Staff/Faculty) only see items allocated to them
            queryset = queryset.filter(
                allocations__allocated_to_person__user=user, 
                allocations__status='ALLOCATED'
            ).distinct()
        # Tiers 0, 1, 2 can see all items for browsing/requesting

        # 2. Scoped Stock Annotations
        accessible_locs = profile.get_descendant_locations()
        # If level 0 (Central), they see global totals. 
        # But get_descendant_locations for level 0 already returns all active locations.
        
        filter_q = Q(stock_records__location__in=accessible_locs)
        
        queryset = queryset.annotate(
            restricted_total=Coalesce(Sum(
                'stock_records__quantity',
                filter=filter_q
            ), Value(0)),
            restricted_in_transit=Coalesce(Sum(
                'stock_records__in_transit_quantity',
                filter=filter_q
            ), Value(0))
        )

        category_id = self.request.query_params.get('category')
        if category_id:
            queryset = queryset.filter(category_id=category_id)
        return queryset
