from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from ..models.person_model import Person
from ..models.stockentry_model import StockEntry
from ..serializers.stockentry_serializer import PersonSerializer, StockEntrySerializer
from ams.permissions import StrictDjangoModelPermissions

class PersonViewSet(viewsets.ModelViewSet):
    queryset = Person.objects.filter(is_active=True)
    serializer_class = PersonSerializer
    permission_classes = [permissions.IsAuthenticated]

class StockEntryViewSet(viewsets.ModelViewSet):
    queryset = StockEntry.objects.all().order_by('-entry_date')
    serializer_class = StockEntrySerializer
    permission_classes = [permissions.IsAuthenticated, StrictDjangoModelPermissions]

    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        from django.utils import timezone
        instance = self.get_object()
        if instance.status != 'PENDING_ACK':
            return Response({'detail': 'This entry does not require acknowledgment.'}, status=400)
        
        instance.status = 'COMPLETED'
        instance.acknowledged_by = request.user
        instance.acknowledged_at = timezone.now()
        instance.save()
        
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        # Security: Filter by location hierarchy
        if not user.is_superuser:
            if hasattr(user, 'profile'):
                from django.db.models import Q
                accessible_locs = user.profile.get_descendant_locations()
                
                # Senders see outgoing ISSUES from their locations
                # Receivers see incoming RECEIPTS to their locations
                queryset = queryset.filter(
                    Q(entry_type='ISSUE', from_location__in=accessible_locs) |
                    Q(entry_type='RECEIPT', to_location__in=accessible_locs)
                )
            else:
                queryset = queryset.none()

        entry_type = self.request.query_params.get('entry_type')
        if entry_type:
            queryset = queryset.filter(entry_type=entry_type)
        return queryset
