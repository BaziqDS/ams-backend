from rest_framework import viewsets
from django.db.models import Q

class ScopedViewSetMixin:
    """
    Standardized Row-Level Security Mixin for AMS.
    Filters the queryset based on the user's hierarchical scope.
    """
    
    def get_scoped_queryset(self, queryset, location_field='location'):
        user = self.request.user
        if not hasattr(user, 'profile'):
            return queryset.none()
            
        if user.is_superuser or user.groups.filter(name='Central Store Manager').exists():
            return queryset

        accessible_locations = user.profile.get_descendant_locations()
        
        # Handle multi-field filtering (e.g. StockEntry from/to)
        if isinstance(location_field, (list, tuple)):
            q_objects = Q()
            for field in location_field:
                q_objects |= Q(**{f"{field}__in": accessible_locations})
            return queryset.filter(q_objects).distinct()
            
        return queryset.filter(**{f"{location_field}__in": accessible_locations}).distinct()
