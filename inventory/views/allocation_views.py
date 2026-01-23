from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from ..models.allocation_model import StockAllocation, AllocationStatus
from ..models.stock_record_model import StockRecord
from ..serializers.allocation_serializer import StockAllocationSerializer
from ams.permissions import StrictDjangoModelPermissions

from .utils import ScopedViewSetMixin

class StockAllocationViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = StockAllocation.objects.all().order_by('-allocated_at')
    serializer_class = StockAllocationSerializer
    permission_classes = [permissions.IsAuthenticated, StrictDjangoModelPermissions]

    @action(detail=True, methods=['post'])
    def return_to_stock(self, request, pk=None):
        """
        Action to return allocated items back to the source store's available stock.
        """
        instance = self.get_object()
        
        if instance.status != AllocationStatus.ALLOCATED:
            return Response(
                {'detail': f'This allocation is already in {instance.status} status.'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        from django.db import transaction
        with transaction.atomic():
            # 1. Update StockRecord: reduce allocated_quantity (this increases available count)
            StockRecord.update_balance(
                item=instance.item,
                location=instance.source_location,
                batch=instance.batch,
                allocated_change=-instance.quantity
            )
            
            # 2. Update instances status if applicable
            if instance.stock_entry:
                from ..models.stockentry_model import StockEntryItem
                try:
                    entry_item = StockEntryItem.objects.get(
                        stock_entry=instance.stock_entry,
                        item=instance.item,
                        batch=instance.batch
                    )
                    entry_item.instances.all().update(status='AVAILABLE')
                except StockEntryItem.DoesNotExist:
                    pass

            # 3. Update allocation status
            instance.status = AllocationStatus.RETURNED
            instance.return_date = timezone.now()
            instance.remarks = f"{instance.remarks or ''}\nReturned to stock by {request.user.username} on {instance.return_date.strftime('%Y-%m-%d %H:%M')}"
            instance.save()
            
        return Response(self.get_serializer(instance).data)

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Security: Filter by source store visibility
        queryset = self.get_scoped_queryset(queryset, location_field='source_location')
                
        # Optional filters
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
            
        person_id = self.request.query_params.get('person')
        if person_id:
            queryset = queryset.filter(allocated_to_person_id=person_id)
            
        location_id = self.request.query_params.get('location')
        if location_id:
            queryset = queryset.filter(allocated_to_location_id=location_id)
            
        source_loc_id = self.request.query_params.get('source_location')
        if source_loc_id:
            queryset = queryset.filter(source_location_id=source_loc_id)
            
        return queryset
