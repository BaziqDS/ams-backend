from rest_framework import viewsets
from django.db.models import Q


def get_item_scope_locations(user):
    """
    Locations visible through the items module.

    Module capability decides whether the user can enter the items surface.
    This helper then applies location scope so item totals, distribution rows,
    and instances are limited to the user's assigned hierarchy.
    """
    from ..models.location_model import Location

    if not hasattr(user, 'profile'):
        return Location.objects.none()

    if (
        user.is_superuser
        or user.groups.filter(name='System Admin').exists()
        or user.has_perm('inventory.view_global_distribution')
        or user.has_perm('inventory.manage_all_locations')
    ):
        return Location.objects.filter(is_active=True)

    location_ids = set()
    for loc in user.profile.assigned_locations.all():
        descendants = loc.get_descendants(include_self=True)
        location_ids.update(descendants.values_list('id', flat=True))

        if loc.is_store:
            standalone = loc.get_parent_standalone()
            if standalone:
                department_locs = Location.objects.filter(
                    hierarchy_path__startswith=standalone.hierarchy_path,
                    is_active=True,
                )
                location_ids.update(department_locs.values_list('id', flat=True))

    return Location.objects.filter(id__in=location_ids, is_active=True).distinct()

class ScopedViewSetMixin:
    """
    Standardized Row-Level Security Mixin for AMS.
    Filters the queryset based on the user's hierarchical scope.
    """
    
    def get_scoped_queryset(self, queryset, location_field='location'):
        user = self.request.user
        if not hasattr(user, 'profile'):
            return queryset.none()
            
        # Bypass scoping for central roles and workflow administrators
        if (user.is_superuser or 
            user.groups.filter(name='Central Store Manager').exists() or
            user.has_perm('inventory.fill_central_register') or
            user.has_perm('inventory.review_finance')):
            return queryset

        accessible_locations = user.profile.get_descendant_locations()
        
        # Handle multi-field filtering (e.g. StockEntry from/to)
        if isinstance(location_field, (list, tuple)):
            q_objects = Q()
            for field in location_field:
                q_objects |= Q(**{f"{field}__in": accessible_locations})
            return queryset.filter(q_objects).distinct()
            
        return queryset.filter(**{f"{location_field}__in": accessible_locations}).distinct()
