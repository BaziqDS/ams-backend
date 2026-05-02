from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from django.db import transaction, models
from .utils import ScopedViewSetMixin
from .distribution_views import build_hierarchical_distribution
from ..models.category_model import CategoryType, TrackingType
from ..models.inspection_model import InspectionCertificate, InspectionItem, InspectionStage
from ..models.batch_model import ItemBatch
from ..serializers.inspection_serializer import InspectionCertificateSerializer, InspectionItemSerializer
from ams.permissions import StrictDjangoModelPermissions
from notifications.services import (
    notify_inspection_completed,
    notify_inspection_initiated,
    notify_inspection_rejected,
    notify_inspection_submitted_to_central_register,
    notify_inspection_submitted_to_finance_review,
)


class InspectionWorkflowPermissions(StrictDjangoModelPermissions):
    """Allow inspection stage permissions to drive inspection workflow actions."""

    def has_permission(self, request, view):
        user = request.user
        action_name = getattr(view, 'action', None)

        if request.method == 'POST' and action_name == 'create':
            if user.has_perm('inventory.initiate_inspection'):
                return True

        if request.method in ('PUT', 'PATCH') and action_name in ('update', 'partial_update'):
            pk = getattr(view, 'kwargs', {}).get(getattr(view, 'lookup_url_kwarg', None) or view.lookup_field)
            if pk and user.has_perm('inventory.initiate_inspection'):
                if view.get_queryset().filter(pk=pk, stage=InspectionStage.DRAFT).exists():
                    return True

        if request.method == 'POST' and action_name == 'initiate':
            if user.has_perm('inventory.initiate_inspection'):
                return True

        return super().has_permission(request, view)


class InspectionViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = InspectionCertificate.objects.all().select_related(
        'department', 'initiated_by', 'stock_filled_by', 
        'central_store_filled_by', 'finance_reviewed_by', 'rejected_by'
    ).prefetch_related('items__item', 'stock_entries')
    serializer_class = InspectionCertificateSerializer
    permission_classes = [permissions.IsAuthenticated, InspectionWorkflowPermissions]
    filter_backends = [filters.SearchFilter]
    search_fields = ['contract_no', 'contractor_name', 'indenter']

    def perform_create(self, serializer):
        instance = serializer.save()
        if instance.stage != InspectionStage.DRAFT:
            transaction.on_commit(lambda: notify_inspection_initiated(instance, self.request.user))

    def perform_update(self, serializer):
        previous_stage = serializer.instance.stage
        instance = serializer.save()
        if previous_stage == InspectionStage.DRAFT and instance.stage != InspectionStage.DRAFT:
            transaction.on_commit(lambda: notify_inspection_initiated(instance, self.request.user))

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.stage != InspectionStage.DRAFT:
            return Response(
                {'detail': f'Cannot delete an inspection that has progressed beyond Draft stage (Current: {instance.stage}).'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        with transaction.atomic():
            return super().destroy(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if not hasattr(user, 'profile'):
            return queryset.none()

        accessible_locations = user.profile.get_user_management_locations()
        return queryset.filter(department__in=accessible_locations).distinct()

    @action(detail=True, methods=['post'])
    def initiate(self, request, pk=None):
        with transaction.atomic():
            instance = self.get_object()
            if not request.user.has_perm('inventory.initiate_inspection'):
                return Response({'detail': 'You do not have permission to initiate inspections.'}, status=status.HTTP_403_FORBIDDEN)
                
            if instance.stage != InspectionStage.DRAFT:
                return Response({'detail': f'Cannot initiate an inspection that is in {instance.stage} stage.'}, status=status.HTTP_400_BAD_REQUEST)
            
            # When initiating, go directly to STOCK_DETAILS or CENTRAL_REGISTER
            if instance.department.hierarchy_level == 0:
                instance.stage = InspectionStage.CENTRAL_REGISTER
            else:
                instance.stage = InspectionStage.STOCK_DETAILS
                
            instance.status = 'IN_PROGRESS'
            instance.initiated_by = request.user
            instance.save()
            transaction.on_commit(lambda: notify_inspection_initiated(instance, request.user))
            return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['post'])
    def submit_to_stock_details(self, request, pk=None):
        with transaction.atomic():
            instance = self.get_object()
            
            # Level 0 locations skip STOCK_DETAILS
            if instance.department.hierarchy_level == 0:
                return Response({'detail': 'Main University inspections skip Stock Details stage.'}, status=status.HTTP_400_BAD_REQUEST)

            if not request.user.has_perm('inventory.fill_stock_details'):
                return Response({'detail': 'You do not have permission to fill stock details.'}, status=status.HTTP_403_FORBIDDEN)

            # This action is now redundant if we initiate directly to STOCK_DETAILS,
            # but kept for compatibility or manual transitions.
            if instance.stage != InspectionStage.DRAFT:
                return Response({'detail': f'Cannot transition from {instance.stage} to STOCK_DETAILS (Must be in Draft).'}, status=status.HTTP_400_BAD_REQUEST)
            
            instance.stage = InspectionStage.STOCK_DETAILS
            instance.status = 'IN_PROGRESS'
            instance.save()
            return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['post'])
    def submit_to_central_register(self, request, pk=None):
        with transaction.atomic():
            instance = self.get_object()
            if (not request.user.has_perm('inventory.fill_stock_details') and 
                not (instance.department.hierarchy_level == 0 and request.user.has_perm('inventory.initiate_inspection'))):
                return Response({'detail': 'You do not have permission to submit to central register (requires fill_stock_details).'}, status=status.HTTP_403_FORBIDDEN)

            allowed_stages = [InspectionStage.STOCK_DETAILS]
            if instance.department.hierarchy_level == 0:
                allowed_stages.append(InspectionStage.DRAFT)

            if instance.stage not in allowed_stages:
                return Response({'detail': f'Cannot transition from {instance.stage} to CENTRAL_REGISTER.'}, status=status.HTTP_400_BAD_REQUEST)
            
            instance.stage = InspectionStage.CENTRAL_REGISTER
            instance.stock_filled_by = request.user
            instance.stock_filled_at = timezone.now()
            instance.save()
            transaction.on_commit(lambda: notify_inspection_submitted_to_central_register(instance, request.user))
            return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['post'])
    def submit_to_finance_review(self, request, pk=None):
        with transaction.atomic():
            instance = self.get_object()
            # Stage 3 submission is performed by the person filling the register
            if not request.user.has_perm('inventory.fill_central_register'):
                return Response({'detail': 'You do not have permission to submit inspections to finance (requires fill_central_register).'}, status=status.HTTP_403_FORBIDDEN)

            if instance.stage != InspectionStage.CENTRAL_REGISTER:
                return Response({'detail': f'Cannot transition from {instance.stage} to FINANCE_REVIEW.'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Validation: All items with accepted quantity must be linked to a system item
            # AND have central register info recorded.
            unlinked = instance.items.filter(accepted_quantity__gt=0, item__isnull=True)
            if unlinked.exists():
                return Response({'detail': 'All items with accepted quantity must be linked to a system item before finance review.'}, status=status.HTTP_400_BAD_REQUEST)

            missing_register = instance.items.filter(
                accepted_quantity__gt=0, 
                central_register__isnull=True
            )
            if missing_register.exists():
                return Response({'detail': 'All accepted items must have a Central Register assigned.'}, status=status.HTTP_400_BAD_REQUEST)

            missing_page = instance.items.filter(
                accepted_quantity__gt=0, 
                central_register_page_no__isnull=True
            ).exclude(central_register_page_no__gt='') # check if empty string or null
            
            # Validation: Ensure Central Register info is recorded (all workflows reach here)
            if instance.items.filter(accepted_quantity__gt=0).filter(
                models.Q(central_register__isnull=True) | 
                models.Q(central_register_page_no__isnull=True) | 
                models.Q(central_register_page_no='')
            ).exists():
                 return Response({'detail': 'All accepted items must have Central Register and Page Number recorded.'}, status=status.HTTP_400_BAD_REQUEST)

            # Validation: Ensure Stage 2 (Departmental) info is recorded if department is not Main University
            # Check if department code is 'NED-UET' or name contains 'university'
            if instance.department.hierarchy_level != 0:
                if instance.items.filter(accepted_quantity__gt=0).filter(
                    models.Q(stock_register__isnull=True) | 
                    models.Q(stock_register_page_no__isnull=True) | 
                    models.Q(stock_register_page_no='')
                ).exists():
                    return Response({'detail': 'All accepted items must have Departmental Stock Register and Page Number recorded.'}, status=status.HTTP_400_BAD_REQUEST)

            instance.stage = InspectionStage.FINANCE_REVIEW
            instance.central_store_filled_by = request.user
            instance.central_store_filled_at = timezone.now()
            instance.save()
            transaction.on_commit(lambda: notify_inspection_submitted_to_finance_review(instance, request.user))
            return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        with transaction.atomic():
            instance = self.get_object()
            if instance.stage != InspectionStage.FINANCE_REVIEW:
                return Response({'detail': f'Cannot transition from {instance.stage} to COMPLETED.'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Final Validation: Ensure Central Register info is present
            if instance.items.filter(accepted_quantity__gt=0).filter(
                models.Q(central_register__isnull=True) | 
                models.Q(central_register_page_no__isnull=True) | 
                models.Q(central_register_page_no='')
            ).exists():
                 return Response({'detail': 'All accepted items must have Central Register and Page Number recorded before completion.'}, status=status.HTTP_400_BAD_REQUEST)

            perishable_without_batch = [
                item.id
                for item in instance.items.filter(accepted_quantity__gt=0).select_related('item__category')
                if item.item
                and item.item.category.get_category_type() == CategoryType.PERISHABLE
                and item.item.category.get_tracking_type() == TrackingType.QUANTITY
                and not item.batch_number
            ]
            if perishable_without_batch:
                return Response({'detail': 'All accepted perishable quantity items must have a batch number before completion.'}, status=status.HTTP_400_BAD_REQUEST)

            # Final Validation: Ensure Stage 2 info is present if not Main University
            if instance.department.hierarchy_level != 0:
                if instance.items.filter(accepted_quantity__gt=0).filter(
                    models.Q(stock_register__isnull=True) | 
                    models.Q(stock_register_page_no__isnull=True) | 
                    models.Q(stock_register_page_no='')
                ).exists():
                    return Response({'detail': 'All accepted items must have Departmental Stock Register and Page Number recorded before completion.'}, status=status.HTTP_400_BAD_REQUEST)
            
            instance.stage = InspectionStage.COMPLETED
            instance.status = 'COMPLETED'
            instance.finance_reviewed_by = request.user
            instance.finance_reviewed_at = timezone.now()
            instance.save()
            transaction.on_commit(lambda: notify_inspection_completed(instance, request.user))
            return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        with transaction.atomic():
            instance = self.get_object()
            reason = request.data.get('reason')
            if not reason:
                return Response({'detail': 'Rejection reason is required.'}, status=status.HTTP_400_BAD_REQUEST)
            
            if instance.stage in [InspectionStage.COMPLETED, InspectionStage.REJECTED]:
                return Response({'detail': 'Cannot reject a completed or already rejected inspection.'}, status=status.HTTP_400_BAD_REQUEST)

            instance.rejection_stage = instance.stage
            instance.stage = InspectionStage.REJECTED
            instance.status = 'REJECTED'
            instance.rejection_reason = reason
            instance.rejected_by = request.user
            instance.rejected_at = timezone.now()
            instance.save()
            transaction.on_commit(lambda: notify_inspection_rejected(instance, request.user))
            return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['get'], url_path=r'items/(?P<item_id>[^/.]+)/distribution')
    def item_distribution(self, request, pk=None, item_id=None):
        instance = self.get_object()
        inspection_item = instance.items.select_related('item__category').filter(pk=item_id).first()
        if not inspection_item:
            return Response({'detail': 'Inspection item not found for this certificate.'}, status=status.HTTP_404_NOT_FOUND)

        if not inspection_item.item:
            return Response({'detail': 'Inspection item is not linked to a catalog item.'}, status=status.HTTP_400_BAD_REQUEST)

        if inspection_item.item.category.get_tracking_type() != TrackingType.QUANTITY:
            return Response({'detail': 'Distribution tracing is available only for quantity-tracked inspection items.'}, status=status.HTTP_400_BAD_REQUEST)

        if not inspection_item.batch_number:
            return Response({'detail': 'No tracking lot exists for this inspection item yet.'}, status=status.HTTP_400_BAD_REQUEST)

        batch = ItemBatch.objects.filter(
            item=inspection_item.item,
            batch_number=inspection_item.batch_number,
        ).first()
        if not batch:
            return Response({'detail': 'Tracking lot not found for this inspection item.'}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            'inspection': {
                'id': instance.id,
                'contract_no': instance.contract_no,
                'department_id': instance.department_id,
                'department_name': instance.department.name if instance.department else None,
                'stage': instance.stage,
                'status': instance.status,
            },
            'inspection_item': {
                'id': inspection_item.id,
                'item_id': inspection_item.item_id,
                'item_name': inspection_item.item.name,
                'item_code': inspection_item.item.code,
                'accepted_quantity': inspection_item.accepted_quantity,
                'tracking_type': inspection_item.item.category.get_tracking_type(),
                'tracking_lot': inspection_item.batch_number,
                'manufactured_date': inspection_item.manufactured_date,
                'expiry_date': inspection_item.expiry_date,
            },
            'batch': {
                'id': batch.id,
                'batch_number': batch.batch_number,
                'manufactured_date': batch.manufactured_date,
                'expiry_date': batch.expiry_date,
            },
            'units': build_hierarchical_distribution(
                request.user,
                inspection_item.item_id,
                batch_id=batch.id,
            ),
        })

    @action(detail=True, methods=['get'])
    def view_pdf(self, request, pk=None):
        instance = self.get_object()
        from io import BytesIO
        from django.http import HttpResponse
        from ..utils.pdf_generator import InspectionPDFGenerator
        
        buffer = BytesIO()
        generator = InspectionPDFGenerator(instance)
        generator.generate(buffer)
        
        buffer.seek(0)
        filename = f"Inspection_Certificate_{instance.contract_no}.pdf"
        
        # Use inline Content-Disposition so it opens in the browser's PDF viewer
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        return response
