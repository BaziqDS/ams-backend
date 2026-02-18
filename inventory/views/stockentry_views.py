from django.utils import timezone
import logging
from rest_framework import viewsets, permissions, filters

logger = logging.getLogger(__name__)
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
        'items__item', 'items__batch', 'items__stock_register', 'items__ack_stock_register', 'items__instances'
    ).order_by('-entry_date')
    serializer_class = StockEntrySerializer
    permission_classes = [permissions.IsAuthenticated, StockEntryPermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ['entry_number', 'remarks']

    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        from django.db import transaction
        from ..models.stockentry_model import StockEntryItem
        
        instance = self.get_object()
        user = request.user
        
        # 1. Basic type/status check
        if instance.status != 'PENDING_ACK' or instance.entry_type not in ['RECEIPT', 'RETURN']:
            return Response({'detail': 'This entry cannot be acknowledged.'}, status=400)
        
        # 2. Permission check
        if not user.is_superuser:
            if not user.has_perm('inventory.acknowledge_stockentry'):
                return Response({'detail': 'You do not have permission to acknowledge entries.'}, status=403)
            
            # 3. Location access check
            if not hasattr(user, 'profile') or not user.profile.has_location_access(instance.to_location):
                return Response({'detail': 'You do not have access to the destination location.'}, status=403)

        accepted_items_data = request.data.get('items', [])
        rejected_items = []
        is_partial = False

        # Validate that all accepted items have ack_stock_register and ack_page_number
        for item_data in accepted_items_data:
            if not item_data.get('ack_stock_register') or not item_data.get('ack_page_number'):
                return Response(
                    {'detail': 'Each item must include ack_stock_register and ack_page_number.'},
                    status=400
                )

        from ..models.stock_register_model import StockRegister
        
        with transaction.atomic():
            if accepted_items_data:
                # Map accepted items by ID for comparison
                accepted_map = {str(item['id']): item for item in accepted_items_data}
                
                for entry_item in instance.items.all():
                    accepted_info = accepted_map.get(str(entry_item.id))
                    
                    if accepted_info:
                        try:
                            ack_register = StockRegister.objects.get(id=accepted_info['ack_stock_register'])
                            entry_item.ack_stock_register = ack_register
                            entry_item.ack_page_number = int(accepted_info['ack_page_number'])
                            entry_item.save(update_fields=['ack_stock_register', 'ack_page_number'])
                        except (StockRegister.DoesNotExist, ValueError, KeyError):
                            return Response(
                                {'detail': f'Invalid ack_stock_register or ack_page_number for item {entry_item.id}.'},
                                status=400
                            )

                    if not accepted_info:
                        # Fully rejected item — use original entry's register for the return
                        rejected_items.append({
                            'item': entry_item.item,
                            'batch': entry_item.batch,
                            'quantity': entry_item.quantity,
                            'instances': list(entry_item.instances.all()),
                            'stock_register': entry_item.stock_register,
                            'page_number': entry_item.page_number,
                        })
                        is_partial = True
                    else:
                        # Check for partial quantity or instance rejection
                        acc_qty = accepted_info.get('quantity', entry_item.quantity)
                        acc_instances_ids = accepted_info.get('instances', []) # List of PKs (strings or ints)
                        
                        if acc_qty < entry_item.quantity:
                            rej_qty = entry_item.quantity - acc_qty
                            rej_instances = []
                            
                            if entry_item.instances.exists():
                                current_insts_ids = set(entry_item.instances.values_list('id', flat=True))
                                # Convert incoming IDs to ints for comparison if needed
                                acc_insts_ids_set = set(map(int, acc_instances_ids)) if acc_instances_ids else current_insts_ids
                                rej_instances_ids = list(current_insts_ids - acc_insts_ids_set)
                                rej_instances = list(entry_item.instances.filter(id__in=rej_instances_ids))
                            
                            rejected_items.append({
                                'item': entry_item.item,
                                'batch': entry_item.batch,
                                'quantity': rej_qty,
                                'instances': rej_instances,
                                'stock_register': entry_item.stock_register,
                                'page_number': entry_item.page_number,
                            })
                            is_partial = True

            # 3. Create automatic RETURN if there are discrepancies
            # CRITICAL: Do NOT create a return for a RETURN entry (prevent infinite loops)
            if rejected_items and instance.entry_type != 'RETURN':
                return_entry = StockEntry.objects.create(
                    entry_type='RETURN',
                    from_location=instance.to_location,
                    to_location=instance.from_location,
                    status='PENDING_ACK',
                    remarks=f"Automatic return for items rejected in {instance.entry_number}.",
                    reference_entry=instance,
                    created_by=user
                )
                for rej in rejected_items:
                    sei = StockEntryItem.objects.create(
                        stock_entry=return_entry,
                        item=rej['item'],
                        batch=rej['batch'],
                        quantity=rej['quantity'],
                        stock_register=rej['stock_register'],
                        page_number=rej['page_number'],
                    )
                    if rej['instances']:
                        sei.instances.set(rej['instances'])
                
                logger.info(f"[VIEW] Created automatic RETURN {return_entry.entry_number} for discrepancy.")

            # 4. Mark original entry as COMPLETED
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
