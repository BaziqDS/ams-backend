from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from ..models.category_model import Category
from ..serializers.category_serializer import CategorySerializer
from ams.permissions import StrictDjangoModelPermissions

class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated, StrictDjangoModelPermissions]

    def get_queryset(self):
        return Category.objects.all()

    def perform_create(self, serializer):
        # Extract notes if provided for the audit trail
        audit_notes = self.request.data.get('notes')
        serializer.save(request_user=self.request.user, audit_notes=audit_notes)

    def perform_update(self, serializer):
        # Extract notes if provided for the audit trail
        audit_notes = self.request.data.get('notes')
        serializer.save(request_user=self.request.user, audit_notes=audit_notes)

    @action(detail=False, methods=['get'])
    def historical_rates(self, request):
        """
        Returns all categories with their effective rates at a specific date.
        Query Param: date (YYYY-MM-DD)
        """
        target_date_str = request.query_params.get('date')
        if not target_date_str:
            return Response({"error": "Date parameter is required"}, status=400)
            
        try:
            from django.utils.dateparse import parse_date
            target_date = parse_date(target_date_str)
            if not target_date: raise ValueError
        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)

        categories = Category.objects.all()
        data = []
        for cat in categories:
            data.append({
                "id": cat.id,
                "name": cat.name,
                "code": cat.code,
                "resolved_category_type": cat.get_category_type(),
                "effective_rate": cat.get_rate_at_date(target_date)
            })
            
        return Response(data)
