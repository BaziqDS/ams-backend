from rest_framework import viewsets, permissions
from ..models.item_model import Item
from ..serializers.item_serializer import ItemSerializer
from ams.permissions import StrictDjangoModelPermissions

class ItemViewSet(viewsets.ModelViewSet):
    queryset = Item.objects.all().select_related('category', 'created_by')
    serializer_class = ItemSerializer
    permission_classes = [permissions.IsAuthenticated, StrictDjangoModelPermissions]

    def get_queryset(self):
        queryset = super().get_queryset()
        category_id = self.request.query_params.get('category')
        if category_id:
            queryset = queryset.filter(category_id=category_id)
        return queryset
