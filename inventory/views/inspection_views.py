from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from django.db import transaction, models
from .utils import ScopedViewSetMixin
from ..models.inspection_model import InspectionCertificate, InspectionItem, InspectionStage
from ..serializers.inspection_serializer import InspectionCertificateSerializer, InspectionItemSerializer
from ams.permissions import StrictDjangoModelPermissions

class InspectionViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = InspectionCertificate.objects.all().select_related(
        'department', 'initiated_by', 'stock_filled_by', 
        'central_store_filled_by', 'finance_reviewed_by', 'rejected_by'
    ).prefetch_related('items__item')
    serializer_class = InspectionCertificateSerializer
    permission_classes = [permissions.IsAuthenticated, StrictDjangoModelPermissions]
    filter_backends = [filters.SearchFilter]
    search_fields = ['contract_no', 'contractor_name', 'indenter']

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
        # Filter based on user department/power level
        return self.get_scoped_queryset(queryset, location_field='department')

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
            is_main_uw = instance.department.code == 'NED-UET' or 'university' in instance.department.name.lower()
            if not is_main_uw:
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

            # Final Validation: Ensure Stage 2 info is present if not Main University
            is_main_uw = instance.department.code == 'NED-UET' or 'university' in instance.department.name.lower()
            if not is_main_uw:
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
            return Response(self.get_serializer(instance).data)
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
