from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from .utils import ScopedViewSetMixin
from ..models.inspection_model import InspectionCertificate, InspectionItem, InspectionStage
from ..serializers.inspection_serializer import InspectionCertificateSerializer, InspectionItemSerializer
from ams.permissions import StrictDjangoModelPermissions

class InspectionViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = InspectionCertificate.objects.all().select_related('department', 'initiated_by')
    serializer_class = InspectionCertificateSerializer
    permission_classes = [permissions.IsAuthenticated, StrictDjangoModelPermissions]

    def get_queryset(self):
        queryset = super().get_queryset()
        # Filter based on user department/power level
        return self.get_scoped_queryset(queryset, location_field='department')

    @action(detail=True, methods=['post'])
    def initiate(self, request, pk=None):
        instance = self.get_object()
        if not request.user.has_perm('inventory.initiate_inspection'):
            return Response({'detail': 'You do not have permission to initiate inspections.'}, status=status.HTTP_403_FORBIDDEN)
            
        if instance.stage != InspectionStage.DRAFT:
            return Response({'detail': f'Cannot initiate an inspection that is in {instance.stage} stage.'}, status=status.HTTP_400_BAD_REQUEST)
        
        instance.stage = InspectionStage.INITIATED
        instance.status = 'IN_PROGRESS'
        instance.initiated_by = request.user
        instance.save()
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['post'])
    def submit_to_stock_details(self, request, pk=None):
        instance = self.get_object()
        
        # Level 0 locations skip STOCK_DETAILS
        if instance.department.hierarchy_level == 0:
            return Response({'detail': 'Main University inspections skip Stock Details stage.'}, status=status.HTTP_400_BAD_REQUEST)

        if not request.user.has_perm('inventory.fill_stock_details'):
            return Response({'detail': 'You do not have permission to fill stock details.'}, status=status.HTTP_403_FORBIDDEN)

        if instance.stage != InspectionStage.INITIATED:
            return Response({'detail': f'Cannot transition from {instance.stage} to STOCK_DETAILS.'}, status=status.HTTP_400_BAD_REQUEST)
        
        instance.stage = InspectionStage.STOCK_DETAILS
        instance.save()
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['post'])
    def submit_to_central_register(self, request, pk=None):
        instance = self.get_object()
        
        if not request.user.has_perm('inventory.fill_central_register'):
            return Response({'detail': 'You do not have permission to fill central register.'}, status=status.HTTP_403_FORBIDDEN)

        # Restriction: Must be "Stock In-charge" and assigned to a Level 1 Store
        is_stock_incharge = request.user.groups.filter(name='Stock In-charge').exists()
        has_l1_store = request.user.profile.assigned_locations.filter(is_store=True, hierarchy_level=1).exists()

        if not (is_stock_incharge and has_l1_store):
            return Response({
                'detail': 'Only a "Stock In-charge" assigned to the Central Store (Level 1) can perform this action.'
            }, status=status.HTTP_403_FORBIDDEN)

        allowed_stages = [InspectionStage.STOCK_DETAILS]
        if instance.department.hierarchy_level == 0:
            allowed_stages.append(InspectionStage.INITIATED)

        if instance.stage not in allowed_stages:
            return Response({'detail': f'Cannot transition from {instance.stage} to CENTRAL_REGISTER.'}, status=status.HTTP_400_BAD_REQUEST)
        
        instance.stage = InspectionStage.CENTRAL_REGISTER
        instance.stock_filled_by = request.user
        instance.stock_filled_at = timezone.now()
        instance.save()
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['post'])
    def submit_to_finance_review(self, request, pk=None):
        instance = self.get_object()
        if not request.user.has_perm('inventory.review_finance'):
            return Response({'detail': 'You do not have permission to perform finance review.'}, status=status.HTTP_403_FORBIDDEN)

        if instance.stage != InspectionStage.CENTRAL_REGISTER:
            return Response({'detail': f'Cannot transition from {instance.stage} to FINANCE_REVIEW.'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Validation: All items with accepted quantity must be linked to a system item
        unlinked = instance.items.filter(accepted_quantity__gt=0, item__isnull=True)
        if unlinked.exists():
            return Response({'detail': 'All items with accepted quantity must be linked to a system item before finance review.'}, status=status.HTTP_400_BAD_REQUEST)

        instance.stage = InspectionStage.FINANCE_REVIEW
        instance.central_store_filled_by = request.user
        instance.central_store_filled_at = timezone.now()
        instance.save()
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        instance = self.get_object()
        if instance.stage != InspectionStage.FINANCE_REVIEW:
            return Response({'detail': f'Cannot transition from {instance.stage} to COMPLETED.'}, status=status.HTTP_400_BAD_REQUEST)
        
        instance.stage = InspectionStage.COMPLETED
        instance.status = 'COMPLETED'
        instance.finance_reviewed_by = request.user
        instance.finance_reviewed_at = timezone.now()
        instance.save()
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
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
        return Response(self.get_serializer(instance).data)
