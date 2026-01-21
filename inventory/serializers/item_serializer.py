from rest_framework import serializers
from ..models.item_model import Item
from .category_serializer import CategorySerializer

class ItemSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='category.name', read_only=True)
    category_type = serializers.CharField(source='category.get_category_type', read_only=True)
    tracking_type = serializers.CharField(source='category.get_tracking_type', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Item
        fields = (
            'id', 'name', 'code', 'category', 'category_display', 
            'category_type', 'tracking_type', 'description', 
            'acct_unit', 'specifications', 'total_quantity', 
            'is_active', 'created_at', 'updated_at', 'created_by_name'
        )
        read_only_fields = ('created_at', 'updated_at', 'created_by')

    def create(self, validated_data):
        request = self.context.get('request')
        if request and request.user:
            validated_data['created_by'] = request.user
        return super().create(validated_data)
