from django.utils import timezone
import logging
from rest_framework import viewsets, permissions, filters, serializers

logger = logging.getLogger(__name__)
from rest_framework.decorators import action
from rest_framework.response import Response
from ..models.person_model import Person
from ..models.correction_model import CorrectionResolutionType, StockCorrectionRequest
from ..models.stockentry_model import StockEntry
from ..serializers.stockentry_serializer import PersonSerializer, StockEntrySerializer
from ..services.stock_correction_service import (
    apply_correction,
    approve_correction,
    build_correction_preview,
    create_correction_request,
    reject_correction,
    serialize_correction,
)
from ams.permissions import StrictDjangoModelPermissions
from ..permissions import StockEntryPermission
from notifications.services import (
    notify_correction_applied,
    notify_correction_approved,
    notify_correction_rejected,
    notify_correction_requested,
    notify_stock_entry_acknowledged,
)

from .utils import ScopedViewSetMixin

class PersonViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for Persons.
    Optimized to avoid N+1 in get_parent_standalone loop.
    """
    queryset = Person.objects.filter(is_active=True).prefetch_related('standalone_locations')
    serializer_class = PersonSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        from django.db.models import Q
        from ..models.location_model import Location
        
        queryset = super().get_queryset()
        user = self.request.user
        
        if user.is_superuser:
            return queryset
            
        if not hasattr(user, 'profile'):
            return queryset.none()
            
        profile = user.profile
        if profile.power_level == 0:
            return queryset
        
        # Optimized: Get accessible locations first, then find standalone parents in bulk
        accessible_locs = profile.get_descendant_locations()
        
        # Get all unique standalone locations in one query
        # Walk up hierarchy to find standalone parents
        all_location_ids = set(accessible_locs.values_list('id', flat=True))
        
        # Also include parent locations that are standalone
        parent_standalone_ids = accessible_locs.exclude(
            parent_location__isnull=True
        ).filter(
            parent_location__is_standalone=True
        ).values_list('parent_location_id', flat=True)
        
        standalone_ids = set(parent_standalone_ids)
        
        # Also include locations that ARE standalone themselves
        direct_standalone_ids = accessible_locs.filter(
            is_standalone=True
        ).values_list('id', flat=True)
        standalone_ids.update(direct_standalone_ids)
        
        if not standalone_ids:
            return queryset.none()
            
        return queryset.filter(standalone_locations__id__in=standalone_ids).distinct()

class StockEntryViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for Stock Entries.
    Optimized with select_related and prefetch_related.
    """
    queryset = StockEntry.objects.select_related(
        'from_location', 'to_location', 'issued_to', 'created_by', 'cancelled_by', 'reference_entry'
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
                accepted_map = {str(item['id']): item for item in accepted_items_data}
            else:
                accepted_map = {}
                 
            for entry_item in instance.items.all():
                accepted_info = accepted_map.get(str(entry_item.id))
                if not accepted_info:
                    if instance.entry_type == 'RETURN':
                        accepted_info = {
                            'id': entry_item.id,
                            'quantity': entry_item.quantity,
                            'instances': list(entry_item.instances.values_list('id', flat=True)),
                            'ack_stock_register': None,
                            'ack_page_number': None,
                        }
                    elif accepted_items_data:
                        return Response({'detail': f'Missing acknowledgement details for item {entry_item.id}.'}, status=400)
                    else:
                        accepted_info = {
                            'id': entry_item.id,
                            'quantity': entry_item.quantity,
                            'instances': list(entry_item.instances.values_list('id', flat=True)),
                            'ack_stock_register': entry_item.ack_stock_register_id,
                            'ack_page_number': entry_item.ack_page_number,
                        }

                accepted_quantity = entry_item.quantity if instance.entry_type == 'RETURN' else int(accepted_info.get('quantity', entry_item.quantity))
                if accepted_quantity < 1 or accepted_quantity > entry_item.quantity:
                    return Response({'detail': f'Accepted quantity for item {entry_item.id} must be between 1 and {entry_item.quantity}.'}, status=400)

                accepted_instance_ids = accepted_info.get('instances', [])
                if (
                    not entry_item.instances.exists()
                    and instance.entry_type == 'RECEIPT'
                    and instance.reference_entry
                ):
                    source_item = instance.reference_entry.items.filter(
                        item=entry_item.item,
                        batch=entry_item.batch,
                        quantity=entry_item.quantity,
                    ).first() or instance.reference_entry.items.filter(
                        item=entry_item.item,
                        batch=entry_item.batch,
                    ).first()
                    if source_item and source_item.instances.exists():
                        entry_item.instances.set(source_item.instances.all())

                current_instance_ids = set(entry_item.instances.values_list('id', flat=True))
                if current_instance_ids:
                    accepted_instance_ids = set(map(int, accepted_instance_ids)) if accepted_instance_ids else current_instance_ids
                    if not accepted_instance_ids.issubset(current_instance_ids):
                        return Response({'detail': f'Accepted instances for item {entry_item.id} must belong to the entry item.'}, status=400)
                    if len(accepted_instance_ids) != accepted_quantity:
                        return Response({'detail': f'Accepted quantity for item {entry_item.id} must match selected instances.'}, status=400)
                else:
                    accepted_instance_ids = set()

                try:
                    ack_register = None
                    if accepted_info.get('ack_stock_register'):
                        ack_register = StockRegister.objects.get(id=accepted_info['ack_stock_register'])
                    elif entry_item.ack_stock_register_id:
                        ack_register = entry_item.ack_stock_register
                    else:
                        return Response({'detail': f'Invalid ack_stock_register or ack_page_number for item {entry_item.id}.'}, status=400)

                    ack_page_number = int(accepted_info.get('ack_page_number') or entry_item.ack_page_number)
                    if ack_page_number < 1:
                        raise ValueError()
                except (StockRegister.DoesNotExist, ValueError, TypeError):
                    return Response({'detail': f'Invalid ack_stock_register or ack_page_number for item {entry_item.id}.'}, status=400)

                entry_item.ack_stock_register = ack_register
                entry_item.ack_page_number = ack_page_number
                entry_item.accepted_quantity = accepted_quantity
                entry_item.save(update_fields=['ack_stock_register', 'ack_page_number', 'accepted_quantity'])
                if current_instance_ids:
                    entry_item.accepted_instances.set(entry_item.instances.filter(id__in=accepted_instance_ids))
                else:
                    entry_item.accepted_instances.clear()

                if instance.entry_type != 'RETURN' and accepted_quantity < entry_item.quantity:
                    rejected_instance_ids = current_instance_ids - accepted_instance_ids
                    rejected_items.append({
                        'item': entry_item.item,
                        'batch': entry_item.batch,
                        'quantity': entry_item.quantity - accepted_quantity,
                        'instances': list(entry_item.instances.filter(id__in=rejected_instance_ids)) if rejected_instance_ids else [],
                        'stock_register': entry_item.stock_register,
                        'page_number': entry_item.page_number,
                    })

            # 3. Create automatic RETURN if there are discrepancies
            # CRITICAL: Do NOT create a return for a RETURN entry (prevent infinite loops)
            if rejected_items and instance.entry_type != 'RETURN':
                return_entry = StockEntry.objects.create(
                    entry_type='RETURN',
                    from_location=instance.to_location,
                    to_location=instance.from_location,
                    status='PENDING_ACK',
                    reference_purpose='REJECTION_RETURN',
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
        notify_stock_entry_acknowledged(instance, user)
        return Response(serializer.data)

    def _correction_target_and_payload(self, instance, payload):
        if not (
            instance.entry_type == 'RECEIPT'
            and instance.reference_entry_id
            and instance.reference_purpose == 'AUTO_RECEIPT'
            and instance.reference_entry.entry_type == 'ISSUE'
        ):
            return instance, payload, False

        source_entry = instance.reference_entry
        mapped_payload = dict(payload)
        mapped_lines = []

        for raw_line in payload.get('lines') or []:
            try:
                receipt_item_id = int(raw_line.get('id'))
            except (TypeError, ValueError):
                raise serializers.ValidationError({'lines': 'Each correction line must include a valid stock entry item id.'})

            try:
                receipt_item = instance.items.select_related('item', 'batch').get(id=receipt_item_id)
            except instance.items.model.DoesNotExist:
                raise serializers.ValidationError({'lines': f'Line {receipt_item_id} does not belong to this stock entry.'})

            source_item = source_entry.items.filter(
                item=receipt_item.item,
                batch=receipt_item.batch,
            ).order_by('id').first()
            if not source_item:
                raise serializers.ValidationError({'lines': f'Line {receipt_item_id} cannot be matched to the source issue.'})

            mapped_line = dict(raw_line)
            mapped_line['id'] = source_item.id
            mapped_lines.append(mapped_line)

        mapped_payload['lines'] = mapped_lines
        return source_entry, mapped_payload, True

    @action(detail=True, methods=['post'], url_path='correction-preview')
    def correction_preview(self, request, pk=None):
        instance = self.get_object()
        correction_entry, correction_payload, _ = self._correction_target_and_payload(instance, request.data)
        preview = build_correction_preview(correction_entry, correction_payload)
        return Response({
            'resolution_type': preview['resolution_type'],
            'message': preview['message'],
            'lines': [
                {
                    'id': line.entry_item.id,
                    'item': line.entry_item.item_id,
                    'item_name': line.entry_item.item.name,
                    'original_quantity': line.original_quantity,
                    'corrected_quantity': line.corrected_quantity,
                    'delta': line.delta,
                    'resolution_type': line.resolution_type,
                    'message': line.message,
                    'affected_instances': line.affected_instance_ids,
                }
                for line in preview['lines']
            ],
        })

    @action(detail=True, methods=['post'], url_path='request-correction')
    def request_correction(self, request, pk=None):
        instance = self.get_object()
        correction_entry, correction_payload, projected_from_receipt = self._correction_target_and_payload(instance, request.data)
        correction = create_correction_request(
            correction_entry,
            correction_payload,
            request.user,
            auto_apply=not projected_from_receipt,
        )
        if correction.status == 'REQUESTED':
            notify_correction_requested(correction, request.user)
        elif correction.status == 'APPLIED':
            notify_correction_applied(correction, request.user)
        return Response(serialize_correction(correction), status=201)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        from django.db import transaction
        
        instance = self.get_object()
        reason = request.data.get('reason')
        
        if not reason:
            return Response({'detail': 'Cancellation reason is required.'}, status=400)
        
        if instance.status == 'COMPLETED':
            return Response({'detail': 'Completed entries cannot be cancelled.'}, status=400)
            
        if instance.status == 'CANCELLED':
            return Response({'detail': 'Entry is already cancelled.'}, status=400)

        with transaction.atomic():
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
            accessible_locations = user.profile.get_stock_entry_scope_locations()

            # Stock entries are visible by workflow role:
            # 1. ISSUE rows only to the source location
            # 2. RECEIPT rows only to the destination location
            # 3. RETURN rows only to the destination location
            queryset = queryset.filter(
                Q(entry_type='ISSUE', from_location__in=accessible_locations) |
                Q(entry_type='RECEIPT', to_location__in=accessible_locations) |
                Q(entry_type='RETURN', to_location__in=accessible_locations)
            ).distinct()
        else:
            return queryset.none()

        entry_type = self.request.query_params.get('entry_type')
        if entry_type:
            queryset = queryset.filter(entry_type=entry_type)
        return queryset


class StockCorrectionViewSet(viewsets.GenericViewSet):
    queryset = StockCorrectionRequest.objects.select_related(
        'original_entry',
        'original_entry__from_location',
        'original_entry__to_location',
        'requested_by',
        'approved_by',
        'rejected_by',
    ).prefetch_related(
        'lines__original_item__item', 'lines__affected_instances', 'generated_entries'
    )
    permission_classes = [permissions.IsAuthenticated]

    def _can_approve(self, request, correction=None):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser or user.groups.filter(name='Central Store Manager').exists():
            return True
        if not user.has_perm('inventory.approve_stock_corrections'):
            return False

        if correction and correction.resolution_type in {
            CorrectionResolutionType.ADDITIONAL_MOVEMENT,
            CorrectionResolutionType.REVERSAL,
        }:
            entry = correction.original_entry
            if entry.entry_type == 'ISSUE' and entry.from_location_id and entry.to_location_id and getattr(entry.to_location, 'is_store', False):
                approval_location = entry.to_location
                if correction.resolution_type == CorrectionResolutionType.ADDITIONAL_MOVEMENT:
                    approval_location = entry.from_location
                return bool(
                    hasattr(user, 'profile')
                    and user.profile.has_location_access(approval_location)
                )

        return True

    def retrieve(self, request, pk=None):
        correction = self.get_object()
        return Response(serialize_correction(correction))

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        correction = self.get_object()
        if not self._can_approve(request, correction):
            return Response({'detail': 'You do not have permission to approve stock corrections.'}, status=403)
        correction = approve_correction(correction, request.user)
        notify_correction_approved(correction, request.user)
        return Response(serialize_correction(correction))

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        correction = self.get_object()
        if not self._can_approve(request, correction):
            return Response({'detail': 'You do not have permission to reject stock corrections.'}, status=403)
        correction = reject_correction(correction, request.user, request.data.get('reason') or '')
        notify_correction_rejected(correction, request.user)
        return Response(serialize_correction(correction))

    @action(detail=True, methods=['post'])
    def apply(self, request, pk=None):
        correction = self.get_object()
        if not self._can_approve(request, correction):
            return Response({'detail': 'You do not have permission to apply stock corrections.'}, status=403)
        correction = apply_correction(correction, user=request.user)
        notify_correction_applied(correction, request.user)
        return Response(serialize_correction(correction))
