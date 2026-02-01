from django.utils import timezone
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from ..models.person_model import Person
from ..models.stockentry_model import StockEntry
from ..serializers.stockentry_serializer import PersonSerializer, StockEntrySerializer
from ams.permissions import StrictDjangoModelPermissions
from ..permissions import StockEntryPermission

from .utils import ScopedViewSetMixin

class PersonViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Person.objects.filter(is_active=True)
    serializer_class = PersonSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if not hasattr(user, 'profile'):
            return queryset.none()
            
        profile = user.profile
        if profile.power_level == 0:
            return queryset
            
        # Filter by department standalone name
        # (This is a simplified departmental check based on the current model)
        accessible_locs = profile.get_descendant_locations()
        standalone_names = set()
        for loc in accessible_locs:
            sa = loc.get_parent_standalone()
            if sa: standalone_names.add(sa.name)
            
        if not standalone_names:
            return queryset.none()
            
        return queryset.filter(department__in=standalone_names)

class StockEntryViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = StockEntry.objects.all().select_related(
        'from_location', 'to_location', 'issued_to', 'created_by', 'cancelled_by'
    ).prefetch_related(
        'items__item', 'items__batch'
    ).order_by('-entry_date')
    serializer_class = StockEntrySerializer
    permission_classes = [permissions.IsAuthenticated, StockEntryPermission]

    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        instance = self.get_object()
        user = request.user
        
        # 1. Basic type/status check
        if instance.status != 'PENDING_ACK' or instance.entry_type != 'RECEIPT':
            return Response({'detail': 'This entry cannot be acknowledged.'}, status=400)
        
        # 2. Permission check
        if not user.is_superuser:
            if not user.has_perm('inventory.acknowledge_stockentry'):
                return Response({'detail': 'You do not have permission to acknowledge entries.'}, status=403)
            
            # 3. Location access check
            if not hasattr(user, 'profile') or not user.profile.has_location_access(instance.to_location):
                return Response({'detail': 'You do not have access to the destination location.'}, status=403)

        instance.status = 'COMPLETED'
        instance.acknowledged_by = user
        instance.acknowledged_at = timezone.now()
        instance.save()
        
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        instance = self.get_object()
        reason = request.data.get('reason')
        
        if not reason:
            return Response({'detail': 'Cancellation reason is required.'}, status=400)
        
        if instance.status == 'COMPLETED':
            return Response({'detail': 'Completed entries cannot be cancelled.'}, status=400)
            
        if instance.status == 'CANCELLED':
            return Response({'detail': 'Entry is already cancelled.'}, status=400)

        instance.status = 'CANCELLED'
        instance.cancellation_reason = reason
        instance.cancelled_by = request.user
        instance.cancelled_at = timezone.now()
        instance.save()
        
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def get_queryset(self):
        from django.db.models import Q
        user = self.request.user
        queryset = super().get_queryset()

        if user.is_superuser or user.groups.filter(name='Central Store Manager').exists():
            # Global/Central managers see everything
            pass 
        elif hasattr(user, 'profile'):
            accessible_locations = user.profile.get_descendant_locations()
            
            # Refined Filtering:
            # 1. Show if the user's location is the SOURCE (Sender)
            # 2. Show if the user's location is the TARGET (Receiver) AND it's NOT an 'ISSUE'
            #    (Level 2 managers should only see the 'RECEIPT' generated for them, not the sender's 'ISSUE')
            queryset = queryset.filter(
                Q(from_location__in=accessible_locations) |
                (Q(to_location__in=accessible_locations) & ~Q(entry_type='ISSUE'))
            ).distinct()
        else:
            return queryset.none()

        entry_type = self.request.query_params.get('entry_type')
        if entry_type:
            queryset = queryset.filter(entry_type=entry_type)
        return queryset
