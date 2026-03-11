from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Prefetch
from ..models.category_model import Category, CategoryRateHistory
from ..serializers.category_serializer import CategorySerializer
from ams.permissions import StrictDjangoModelPermissions

class CategoryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Categories.
    Optimized with select_related for parent relationships.
    """
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated, StrictDjangoModelPermissions]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'code']

    def get_queryset(self):
        # Add select_related to avoid N+1 on parent_category
        return Category.objects.select_related('parent_category').all()

    def perform_create(self, serializer):
        # Extract notes if provided for the audit trail
        audit_notes = self.request.data.get('notes')
        serializer.save(request_user=self.request.user, audit_notes=audit_notes)

    def perform_update(self, serializer):
        # Extract notes if provided for the audit trail
        audit_notes = self.request.data.get('notes')
        serializer.save(request_user=self.request.user, audit_notes=audit_notes)

    @action(detail=False, methods=['get'])
    def historical_rates(self, request):
        """
        Returns all categories with their effective rates at a specific date.
        Optimized to use prefetched rate history (avoids N+1 queries).
        Query Param: date (YYYY-MM-DD)
        """
        target_date_str = request.query_params.get('date')
        if not target_date_str:
            return Response({"error": "Date parameter is required"}, status=400)
            
        try:
            from django.utils.dateparse import parse_date
            target_date = parse_date(target_date_str)
            if not target_date: raise ValueError
        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)

        # Prefetch rate history to avoid N+1 queries
        categories = Category.objects.select_related('parent_category').prefetch_related(
            Prefetch(
                'rate_history',
                queryset=CategoryRateHistory.objects.order_by('-changed_at')
            )
        ).all()

        # Build parent lookup for inheritance resolution
        category_map = {cat.id: cat for cat in categories}
        
        data = []
        for cat in categories:
            # Resolve rate using prefetched data (no extra DB queries)
            effective_rate = self._resolve_rate_from_prefetch(cat, category_map, target_date)
            
            data.append({
                "id": cat.id,
                "name": cat.name,
                "code": cat.code,
                "resolved_category_type": cat.get_category_type(),
                "effective_rate": effective_rate
            })
            
        return Response(data)

    def _resolve_rate_from_prefetch(self, category, category_map, target_date):
        """
        Resolve rate from prefetched data without making DB queries.
        Uses memoization to cache results.
        """
        # Check memoization cache first
        if hasattr(category, '_resolved_rate_cache'):
            cache_key = str(target_date)
            if cache_key in category._resolved_rate_cache:
                return category._resolved_rate_cache[cache_key]
        
        # Initialize cache if needed
        if not hasattr(category, '_resolved_rate_cache'):
            category._resolved_rate_cache = {}
        
        # Get rate from prefetched history
        rate = None
        
        # Check local rate history (prefetched)
        if hasattr(category, '_prefetched_objects_cache') and 'rate_history' in category._prefetched_objects_cache:
            history_list = category._prefetched_objects_cache['rate_history']
            for history in history_list:
                if history.changed_at and history.changed_at <= target_date:
                    rate = history.rate
                    break
        
        # If no local rate, inherit from parent
        if rate is None and category.parent_category_id:
            parent = category_map.get(category.parent_category_id)
            if parent:
                rate = self._resolve_rate_from_prefetch(parent, category_map, target_date)
        
        # Fallback to current rate
        if rate is None:
            rate = category.get_depreciation_rate()
        
        # Cache result
        category._resolved_rate_cache[str(target_date)] = rate
        return rate
