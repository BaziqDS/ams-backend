from rest_framework import serializers
from ..models.item_model import Item
from .category_serializer import CategorySerializer

class ItemSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='category.name', read_only=True)
    category_type = serializers.CharField(source='category.get_category_type', read_only=True)
    tracking_type = serializers.CharField(source='category.get_tracking_type', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    total_quantity = serializers.SerializerMethodField()
    in_transit_quantity = serializers.SerializerMethodField()
    available_quantity = serializers.SerializerMethodField()
    is_low_stock = serializers.SerializerMethodField()
    standalone_location_count = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = (
            'id', 'name', 'code', 'category', 'category_display', 
            'category_type', 'tracking_type', 'description', 
            'acct_unit', 'specifications', 'low_stock_threshold',
            'total_quantity', 
            'in_transit_quantity', 'available_quantity',
            'is_low_stock', 'standalone_location_count', 'is_active', 'created_at', 'updated_at',
            'created_by_name'
        )
        read_only_fields = ('created_at', 'updated_at', 'created_by')


    def create(self, validated_data):
        request = self.context.get('request')
        if request and request.user:
            validated_data['created_by'] = request.user
        return super().create(validated_data)

    def get_total_quantity(self, obj):
        return getattr(obj, 'restricted_total', 0)

    def get_in_transit_quantity(self, obj):
        return getattr(obj, 'restricted_in_transit', 0)

    def get_available_quantity(self, obj):
        total = getattr(obj, 'restricted_total', 0)
        in_transit = getattr(obj, 'restricted_in_transit', 0)
        return max(0, total - in_transit)

    def get_is_low_stock(self, obj):
        total = getattr(obj, 'restricted_total', 0)
        threshold = obj.low_stock_threshold or 0
        return threshold > 0 and total > 0 and total <= threshold

    def get_standalone_location_count(self, obj):
        counts = self.context.get('standalone_location_counts') or {}
        return counts.get(obj.id, 0)


